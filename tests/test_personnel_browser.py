"""Real login, private workspace, office approval and roster on desktop and mobile."""
import os
from datetime import timedelta
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from auth import hash_password
from models import User, Role, UserRole, RoleEnum, Personale, PersonnelTeam, PersonnelAssignment, PersonalePresenza
from services.personnel import today
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_personal_leave_office_and_team_on_mobile(live_operations):
    origin,engine,ids,password,out=live_operations
    day=today();leave=day+timedelta(days=7)
    while leave.weekday()>4:leave+=timedelta(days=1)
    with Session(engine) as db:
        role=db.query(Role).filter_by(name=RoleEnum.personale).first()
        if not role:role=Role(name=RoleEnum.personale);db.add(role);db.flush()
        staff=User(email='personal-browser@example.test',full_name='Luca Collaudo',role=RoleEnum.personale,hashed_password=hash_password(password),is_active=True)
        staff.user_roles=[UserRole(role=role)];db.add(staff);db.flush()
        worker=Personale(nome='Luca',cognome='Collaudo',user_id=staff.id,attivo=True);db.add(worker);db.flush()
        capo=db.query(User).filter_by(email='smoke-capo@example.com').one()
        team=PersonnelTeam(name='Squadra collaudo',site_id=ids['site'],lead_id=capo.id);db.add(team);db.flush()
        db.add(PersonnelAssignment(person_id=worker.id,team_id=team.id,start_date=day,end_date=leave));db.commit()
        worker_id=worker.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':390,'height':844})
        manager_context=browser.new_context(viewport={'width':1440,'height':1000})
        staff=context.new_page();manager=manager_context.new_page();errors=[]
        for page in (staff,manager):
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        def login(page,email,destination):
            page.goto(origin+'/login');page.locator('#email').fill(email);page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click();page.wait_for_url('**'+destination)
        login(staff,'personal-browser@example.test','/mio-spazio')
        expect(staff.locator('#pw-content')).to_contain_text('Cantiere Collaudo')
        staff.screenshot(path=str(out/'spazio-mobile.png'),full_page=True)
        staff.locator('[data-action=leave]').click()
        form=staff.locator('[data-form=request]')
        form.locator('[name=start_date]').fill(str(leave));form.locator('[name=end_date]').fill(str(leave))
        form.locator('[type=submit]').click();expect(staff.locator('#pw-status')).to_contain_text('Salvato')
        expect(staff.locator('#pw-detail')).to_contain_text('In attesa')
        login(manager,'smoke-manager@example.com','/manager/dashboard')
        manager.goto(origin+'/manager/personale/richieste');manager.locator('[data-request]').first.click()
        form=manager.locator('[data-form=decision]');form.locator('[name=classification]').select_option('FERIE');form.locator('[name=response]').fill('Confermato')
        form.locator('[type=submit]').click();expect(manager.locator('#pw-status')).to_contain_text('Salvato')
        manager.screenshot(path=str(out/'ufficio-desktop.png'),full_page=True)
        staff.reload();expect(staff.locator('#pw-content')).to_contain_text('Approvata')
        for width in [390,320]:
            staff.set_viewport_size({'width':width,'height':844})
            for tab in ['home','hours','sites','requests']:
                staff.locator('[data-tab='+tab+']').click()
                assert staff.locator('#personnel-workspace').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),(width,tab)
        manager.goto(origin+'/manager/personale/presenze?week_start='+str(leave))
        expect(manager.locator('.attendance-table')).to_contain_text('Ferie')
        manager.goto(origin+'/manager/personale/squadre');expect(manager.locator('#pw-content')).to_contain_text('Squadra collaudo')
        manager.screenshot(path=str(out/'squadre-desktop.png'),full_page=True)
        capo_context=browser.new_context(viewport={'width':390,'height':844})
        capo=capo_context.new_page();capo.on('pageerror',lambda e:errors.append(str(e)))
        capo.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        login(capo,'smoke-capo@example.com','/capo/dashboard')
        capo.goto(origin+'/capo/rapportini/nuovo')
        expect(capo.locator('#rapportino-form')).not_to_have_attribute('inert','')
        capo.locator('#data').fill(str(day));capo.locator('#cantiere_id').select_option(str(ids['site']))
        capo.locator('#load-planned-team').click();expect(capo.locator('#planned-team')).to_contain_text('Luca Collaudo')
        capo.on('dialog',lambda dialog:dialog.accept())
        capo.locator('#apply-planned-team').click();expect(capo.locator('.worker-row')).to_have_count(2)
        capo.locator('#attivita').fill('Attività di collaudo squadra')
        capo.locator('#rapportino-form button[type=submit]').click()
        capo.wait_for_url('**/capo/dashboard?rapportino_created=1')
        with Session(engine) as db:
            assert db.query(PersonalePresenza).filter_by(personale_id=worker_id,status='FERIE').count()==1
            assert db.query(PersonalePresenza).filter_by(personale_id=worker_id,status='WORK').count()==1
            assert db.query(PersonnelAssignment).filter_by(person_id=worker_id).count()==1
        assert not errors,errors
        browser.close()
