import os
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site, User, RoleEnum, UserRole
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_site_delete_confirmation_and_real_list_removal(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        admin=db.query(User).filter_by(email='smoke-manager@example.com').one()
        admin.role=RoleEnum.admin
        db.query(UserRole).filter_by(user_id=admin.id).delete()
        name=db.get(Site,ids['site']).name
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page()
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login')
        page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f"/manager/cantieri/{ids['site']}")
        assert page.locator('[name=conferma_nome]').count(), page.locator('body').inner_text()
        form=page.locator('form').filter(has=page.locator('[name=conferma_nome]'))
        page.get_by_text('Eliminazione cantiere',exact=True).click()
        form.locator('[name=conferma_nome]').fill(name)
        page.once('dialog',lambda d:d.dismiss())
        form.locator('button[type=submit]').click()
        with Session(engine) as db: assert db.get(Site,ids['site']) is not None
        page.once('dialog',lambda d:d.accept())
        form.locator('button[type=submit]').click()
        page.wait_for_url('**/manager/cantieri?deleted=1')
        expect(page.get_by_role('status')).to_contain_text('Cantiere eliminato correttamente')
        assert page.get_by_role('link',name=name,exact=True).count()==0
        with Session(engine) as db: assert db.get(Site,ids['site']) is None
        browser.close()
