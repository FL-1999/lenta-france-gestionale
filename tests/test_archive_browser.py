"""Owner archive selection and explicit deletion over real HTTP in an isolated DB."""
import os
import json
from datetime import datetime

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from models import CloudAsset, Role, RoleEnum, User, UserRole, SitePlan
from services.cloud_archive import enqueue
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


@pytest.fixture(autouse=True)
def archive_owner(monkeypatch):
    monkeypatch.setenv('CLOUD_ARCHIVE_OWNER_EMAIL', 'smoke-manager@example.com')
    monkeypatch.setenv('SHAREPOINT_SYNC_ENABLED', 'false')


def make_archive_owner(db):
    # The server's background bootstrap may still be populating roles when the
    # login page first responds. Seed this test identity atomically ourselves.
    db.execute(insert(Role).values(name=RoleEnum.admin).on_conflict_do_nothing(index_elements=['name']))
    user = db.query(User).filter_by(email='smoke-manager@example.com').one()
    user.role = RoleEnum.admin
    role_id = db.query(Role).filter_by(name=RoleEnum.admin).one().id
    db.execute(insert(UserRole).values(user_id=user.id, role_id=role_id)
               .on_conflict_do_nothing(index_elements=['user_id', 'role_id']))


def test_owner_can_exclude_restore_and_explicitly_delete(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        make_archive_owner(db)
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


def test_current_and_latest_pdf_are_distinct_and_open_the_exact_drawing(live_operations):
    from services.site_plan_import import import_pdf
    from test_site_plans import vector_pdf
    origin, engine, ids, password, artifacts = live_operations
    pdf = vector_pdf()
    layout, preview = import_pdf(pdf)
    with Session(engine) as db:
        make_archive_owner(db)
        old = SitePlan(site_id=ids['site'], filename='same.pdf', pdf_data=pdf, preview_data=preview,
                       draft=json.dumps(layout), approved=json.dumps(layout),
                       created_at=datetime(2026,9,20,8,15), approved_at=datetime(2026,9,20,9))
        new = SitePlan(site_id=ids['site'], filename='same.pdf', pdf_data=pdf, preview_data=preview,
                       draft=json.dumps(layout), created_at=datetime(2026,9,21,8,30))
        db.add_all([old, new]); db.commit()
        old_id, new_id = old.id, new.id
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width':1440,'height':1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page.goto(origin + '/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin + '/admin/sharepoint#archive')
        expect(page.locator('[data-plan-state=current]')).to_have_count(2)
        expect(page.locator('[data-latest-upload]')).to_have_count(2)
        latest = page.locator(f'.cloud-file-identity[data-plan-id="{new_id}"]')
        current = page.locator(f'.cloud-file-identity[data-plan-id="{old_id}"]')
        expect(latest.first).to_contain_text('Ultimo PDF caricato')
        expect(latest.first).to_contain_text('21/09/2026 08:30 UTC')
        expect(current.first).to_contain_text('Pianta attualmente in uso')
        expect(current.first).to_contain_text('Cantiere Collaudo')
        with page.expect_popup() as popup:
            latest.first.get_by_role('link',name='Apri questo disegno').click()
        drawing = popup.value
        expect(drawing.locator('[data-version]')).to_have_value(str(new_id))
        drawing.goto(origin + f'/manager/cantieri/{ids["site"]}/pianta')
        expect(drawing.locator('[data-version]')).to_have_value(str(old_id))
        drawing.close()
        page.locator('#archive').screenshot(path=str(artifacts / 'archive-identity.png'))
        page.set_viewport_size({'width':390,'height':844})
        expect(latest.first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        assert not errors
        browser.close()
