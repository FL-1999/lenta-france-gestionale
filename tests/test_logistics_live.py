"""Vehicle editor and driver code entry with real login, HTTP and local assets."""
import os
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from auth import hash_password
from models import (User, RoleEnum, Attrezzatura, AttrezzaturaStatoEnum,
                    TrasportoViaggio, TrasportoTappa, MovimentoAttrezzatura)
from models.veicoli import Veicolo
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1', reason='Browser opt-in')


def test_vehicle_and_driver_scanner(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        driver=User(email='browser-driver@example.com',role=RoleEnum.driver,is_active=True,hashed_password=hash_password(password))
        equipment=Attrezzatura(codice='POMPA-BROWSER',qr_code='QR-BROWSER',tipo='pompa',nome='Pompa browser',stato=AttrezzaturaStatoEnum.disponibile)
        db.add_all([driver,equipment]);db.flush()
        trip=TrasportoViaggio(codice_viaggio='BROWSER-A-B',data_partenza=date(2026,9,16),origine='Deposito',destinazione='B',autista_id=driver.id)
        db.add(trip);db.flush()
        a=TrasportoTappa(viaggio_id=trip.id,ordine=1,destinazione='A',site_id=ids['site'])
        b=TrasportoTappa(viaggio_id=trip.id,ordine=2,destinazione='B',site_id=ids['other'])
        db.add_all([a,b]);db.commit();trip_id,a_id=trip.id,a.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1050})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def login(email):
            page.goto(origin+'/login')
            page.locator('#email').fill(email);page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_url(lambda url:'/login' not in url)
        login('smoke-manager@example.com')
        page.goto(origin+'/manager/veicoli/nuovo')
        expect(page.locator('.vehicle-editor .workspace-context')).to_have_count(4)
        for theme in ('dark','light'):
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.screenshot(path=str(artifacts/f'vehicle-{theme}.png'),full_page=True)
        page.get_by_label('Marca *',exact=True).fill('Collaudo')
        page.get_by_label('Modello *',exact=True).fill('Flotta')
        page.get_by_label('Targa *',exact=True).fill('browser01')
        page.get_by_label('Chilometraggio',exact=True).fill('0')
        page.locator('#visibile_trasporti').check()
        page.get_by_role('button',name='Salva veicolo',exact=True).click()
        page.wait_for_url('**/manager/veicoli')
        with Session(engine) as db:
            vehicle=db.query(Veicolo).filter_by(targa='BROWSER01').one();vehicle_id=vehicle.id
            assert vehicle.km==0 and vehicle.visibile_trasporti
        page.goto(origin+f'/manager/veicoli/{vehicle_id}/modifica')
        page.set_viewport_size({'width':390,'height':844})
        expect(page.locator('#vehicle-km')).to_have_value('0')
        assert page.locator('#vehicle-marca').bounding_box()['width']>=250
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(artifacts/'vehicle-mobile.png'),full_page=True)
        context.clear_cookies();login('browser-driver@example.com')
        page.goto(origin+f'/driver/trasporti/viaggi/{trip_id}')
        page.locator('#scan-stop').select_option(str(a_id))
        page.locator('#scan-code').fill('POMPA-BROWSER')
        page.get_by_role('button',name='Conferma codice').click()
        expect(page.locator('#scan-result')).to_contain_text('CARICATO')
        page.locator('#scan-next').click()
        page.locator('#scan-action').select_option('scarico')
        page.get_by_role('button',name='Conferma codice').click()
        expect(page.locator('#scan-result')).to_contain_text('SCARICATO')
        page.locator('#scan-refresh').click()
        expect(page.get_by_text('POMPA-BROWSER · Consegnato')).to_be_visible()
        with Session(engine) as db:
            movement=db.query(MovimentoAttrezzatura).filter_by(viaggio_id=trip_id).one()
            assert movement.destinazione_site_id==ids['site']
        assert not errors, errors
        if os.getenv('LOGISTICS_PREVIEW_DIR'):
            import shutil
            dest=Path(os.environ['LOGISTICS_PREVIEW_DIR']);dest.mkdir(parents=True,exist_ok=True)
            for file in artifacts.glob('vehicle-*.png'):shutil.copyfile(file,dest/file.name)
        browser.close()
