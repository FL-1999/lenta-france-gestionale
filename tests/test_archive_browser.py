"""Owner archive selection and explicit deletion over real HTTP in an isolated DB."""
import os

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import CloudAsset, Role, RoleEnum, User, UserRole
from services.cloud_archive import enqueue
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


@pytest.fixture(autouse=True)
def archive_owner(monkeypatch):
    monkeypatch.setenv('CLOUD_ARCHIVE_OWNER_EMAIL', 'smoke-manager@example.com')
    monkeypatch.setenv('SHAREPOINT_SYNC_ENABLED', 'false')


def test_owner_can_exclude_restore_and_explicitly_delete(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        user = db.query(User).filter_by(email='smoke-manager@example.com').one()
        user.role = RoleEnum.admin
        db.add(UserRole(user_id=user.id, role_id=db.query(Role).filter_by(name=RoleEnum.admin).one().id))
        enqueue(db, 'plan', 900, 'prova.pdf', b'trial-pdf')
        enqueue(db, 'plan_preview', 900, 'preview.png', b'trial-preview')
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page.goto(origin + '/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin + '/admin/sharepoint#archive')
        expect(page.locator('button[value=exclude]')).to_be_disabled()
        page.locator('#archive-select-all').check()
        page.locator('button[value=exclude]').click()
        expect(page.get_by_role('status')).to_contain_text('Copie escluse')
        page.goto(origin + '/admin/sharepoint?view=excluded#archive')
        page.locator('#archive-select-all').check()
        page.locator('button[value=trash]').click()
        page.goto(origin + '/admin/sharepoint?view=trash#archive')
        page.locator('#archive-select-all').check()
        page.locator('button[value=restore]').click()
        expect(page.get_by_role('status')).to_contain_text('Copie recuperate tra gli esclusi')
        page.goto(origin + '/admin/sharepoint?view=excluded#archive')
        page.locator('#archive-select-all').check()
        page.locator('button[value=trash]').click()
        page.goto(origin + '/admin/sharepoint?view=trash#archive')
        page.locator('#archive-select-all').check()
        page.screenshot(path=str(artifacts / 'archive-trash.png'), full_page=True)
        page.locator('button[value=purge_review]').click()
        expect(page.locator('h1')).to_have_text('Eliminare queste copie definitivamente?')
        page.locator('#purge-confirmation').fill('NO')
        page.locator('button[type=submit]').click()
        expect(page.locator('#purge-confirmation')).to_be_visible()
        with Session(engine) as db:
            assert db.query(CloudAsset).filter_by(status='deleted').count() == 0
        page.locator('#purge-confirmation').fill('ELIMINA DEFINITIVAMENTE')
        page.locator('button[type=submit]').click()
        expect(page.get_by_role('status')).to_contain_text('eliminate definitivamente')
        with Session(engine) as db:
            assert all(row.status == 'deleted' and row.payload == b'' for row in db.query(CloudAsset))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(origin + '/admin/sharepoint?view=trash#archive')
        expect(page.locator('#archive')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        assert not errors
        browser.close()
