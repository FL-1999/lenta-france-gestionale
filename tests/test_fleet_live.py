import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from auth import hash_password
from models import User, Role, UserRole, RoleEnum, Depot, Attrezzatura, AttrezzaturaStatoEnum, FleetJourney
from models.veicoli import Veicolo
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_real_fleet_creation_and_driver_checklist(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        driver=User(email='fleet-live@example.com',full_name='Autista Prova',role=RoleEnum.driver,is_active=True,hashed_password=hash_password(password))
        db.add(driver);db.flush()
        role=db.query(Role).filter_by(name=RoleEnum.driver).one_or_none()
        if role is None:
            role=Role(name=RoleEnum.driver)
            db.add(role);db.flush()
        db.add(UserRole(user_id=driver.id,role_id=role.id))
        depot=Depot(name='Deposito Prova',is_active=True)
        vehicle=Veicolo(marca='Test',modello='Camion',targa='FLEETLIVE',categoria='camion',visibile_trasporti=True)
        equipment=Attrezzatura(codice='GEN-LIVE',qr_code='GEN-LIVE',nome='Gruppo Prova',tipo='Generatori',stato=AttrezzaturaStatoEnum.manutenzione,posizione_attuale='Deposito Prova')
        db.add_all([depot,vehicle,equipment]);db.commit()
        key=f'equipment:{equipment.id}';start=f'depot:{depot.id}';vehicle_id=vehicle.id;driver_id=driver.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1280,'height':1100});page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def login(email):
            page.goto(origin+'/login');page.locator('#email').fill(email);page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click();page.wait_for_url(lambda url:'/login' not in url)
        login('smoke-manager@example.com');page.goto(origin+'/manager/parco')
        page.locator(f'[data-pick="{key}"]').check();page.locator('[data-act="prepare"]').click()
        page.locator('[data-move="destination"]').select_option(f'site:{ids["site"]}')
        page.locator('[data-field="start"]').select_option(start);page.locator('[data-act="preview"]').click()
        page.locator('[data-field="vehicle"]').select_option(str(vehicle_id));page.locator('[data-field="driver"]').select_option(str(driver_id))
        page.locator('[data-field="day"]').fill('2026-10-06');page.locator('[data-field="day"]').press('Tab')
        for width in [1280,736,390]:
            page.set_viewport_size({'width':width,'height':1100})
            assert page.locator('#fleet-workspace').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.locator('[data-act="create"]').click();page.wait_for_url('**/logistica/viaggi/*')
        url=page.url
        expect(page.locator('#fleet-workspace')).to_contain_text('Viaggio creato')
        with Session(engine) as db:
            assert db.query(Attrezzatura).filter_by(codice='GEN-LIVE').one().posizione_attuale=='Deposito Prova'
        context.clear_cookies();login('fleet-live@example.com');page.goto(url)
        page.locator('[data-act="failure"]').click();page.locator('[name="reason"]').fill('Non pronto al ritiro')
        page.locator('[data-failure] button[type="submit"]').click()
        expect(page.locator('#fleet-workspace')).to_contain_text('Non pronto al ritiro')
        page.reload();expect(page.locator('#fleet-workspace')).to_contain_text('✕ Non fatto')
        page.locator('[data-act="next"]').click();page.locator('[data-act="next"]').click();page.locator('[data-act="next"]').click()
        expect(page.locator('#fleet-workspace')).to_contain_text('Viaggio terminato')
        if os.getenv('FLEET_PREVIEW_DIR'):
            dest=Path(os.environ['FLEET_PREVIEW_DIR']);dest.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(dest/'fleet-driver.png'),full_page=True)
        assert not errors,errors
        browser.close()
