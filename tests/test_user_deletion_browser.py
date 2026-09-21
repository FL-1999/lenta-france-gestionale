import os
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import User, RoleEnum
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_delete_profile_confirmation_and_list(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        actor=db.query(User).filter_by(email='smoke-manager@example.com').one();actor.role=RoleEnum.admin
        from main import _sync_user_roles
        _sync_user_roles(db,actor,[RoleEnum.admin])
        target=User(email='profile-to-delete@example.com',full_name='Profilo da eliminare',hashed_password='unused',role=RoleEnum.driver,is_active=True)
        db.add(target);db.commit();uid=target.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/utenti');page.locator(f'a[href="/manager/utenti/{uid}/elimina"]').click()
        expect(page.get_by_role('heading',name='Elimina profilo')).to_be_visible()
        page.locator('#conferma-email').fill('wrong@example.com');page.get_by_role('button',name='Elimina definitivamente').click()
        expect(page.get_by_role('alert')).to_contain_text('email esatta')
        page.locator('#conferma-email').fill('profile-to-delete@example.com')
        page.get_by_role('button',name='Elimina definitivamente').click();page.wait_for_url('**/manager/utenti?eliminato=1')
        expect(page.get_by_role('status')).to_have_text('Profilo eliminato con successo.')
        expect(page.get_by_role('cell',name='profile-to-delete@example.com',exact=True)).to_have_count(0)
        browser.close()
