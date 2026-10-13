"""Admin provisions an existing person, real login and reversible attendance filter."""
import os
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from auth import hash_password
from models import User, Role, UserRole, RoleEnum, Personale
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_account_from_personnel_and_attendance_options(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        role=db.query(Role).filter_by(name=RoleEnum.admin).first()
        if not role:role=Role(name=RoleEnum.admin);db.add(role);db.flush()
        admin=User(email='admin-personnel@example.com',full_name='Admin Personale',role=RoleEnum.admin,
                   hashed_password=hash_password(password),is_active=True,user_roles=[UserRole(role=role)])
        person=Personale(nome='Mario',cognome='Accesso',ruolo='manovale',attivo=True)
        db.add_all([admin,person]);db.commit();person_id=person.id;count=db.query(Personale).count()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        def login(target,email,destination):
            target.goto(origin+'/login');target.locator('#email').fill(email);target.locator('#password').fill(password)
            target.locator('#login-form button[type=submit]').click();target.wait_for_url('**'+destination)
        login(page,'admin-personnel@example.com','/manager/dashboard')
        page.goto(f'{origin}/manager/personale/{person_id}/edit')
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.locator('.pw-admin-controls').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.screenshot(path=str(out/'accesso-personale-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        form=page.locator('[data-admin-action=create]')
        form.locator('[name=email]').fill('direct-personnel@example.com')
        form.locator('[name=language]').select_option('it')
        form.locator('[name=password]').fill(password);form.locator('[name=password_confirm]').fill(password)
        with page.expect_navigation(wait_until='domcontentloaded'):
            form.locator('[type=submit]').click()
        expect(page.locator('.pw-admin-controls')).to_contain_text('Account già collegato')
        assert page.locator('[data-admin-action=create]').count()==0
        with Session(engine) as db:
            assert db.query(Personale).count()==count
            assert db.get(Personale,person_id).user_id is not None
        personal_context=browser.new_context(viewport={'width':390,'height':844})
        personal=personal_context.new_page()
        personal.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        login(personal,'direct-personnel@example.com','/mio-spazio')
        expect(personal.locator('h1')).to_have_text('Il mio spazio')
        expect(personal.locator('[data-tab=hours]')).to_be_visible()
        role_form=page.locator('[data-admin-action=role]')
        role_form.locator('[name=role]').select_option('caposquadra')
        with page.expect_navigation(wait_until='domcontentloaded'):
            role_form.locator('[type=submit]').click()
        expect(page.locator('[data-admin-action=role] [name=role]')).to_have_value('caposquadra')
        with Session(engine) as db:
            account=db.get(User,db.get(Personale,person_id).user_id)
            # Wait for the reload to reflect the persisted permission change.
            assert account.role==RoleEnum.caposquadra
        flag=page.locator('[data-attendance-person]');flag.uncheck()
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('[data-admin-action=attendance] [type=submit]').click()
        expect(page.locator('[data-attendance-person]')).not_to_be_checked()
        page.goto(origin+'/manager/personale/presenze')
        expect(page.locator('.attendance-table')).not_to_contain_text('Accesso Mario')
        page.locator('.pw-admin-controls summary').click()
        page.locator(f'[data-attendance-person="{person_id}"]').check()
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('[data-admin-action=attendance] [type=submit]').click()
        expect(page.locator('.attendance-table')).to_contain_text('Accesso Mario')
        page.screenshot(path=str(out/'presenze-opzione-admin.png'),full_page=True)
        personal_context.close();browser.close()
        assert not errors
