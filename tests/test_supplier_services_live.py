import os
import json
from datetime import date
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Supplier, Veicolo, ServiceRecord, SiteEconomicEntry, SitePlan
from test_operations_live import live_operations
from test_site_plans import vector_pdf
from test_plan_corners import layout
from services.site_plan_import import import_pdf

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_services_fleet_and_manual_corner(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        supplier=Supplier(name='Officina e laboratorio');db.add(supplier)
        vehicle=Veicolo(marca='Peugeot',modello='Expert',targa='FR-TEST',visibile_trasporti=True)
        db.add(vehicle);db.flush();sid,vid=supplier.id,vehicle.id
        plan=layout();plan['panels'][1]['points']=[[45,140],[95,145],[93,165],[43,160]]
        plan['panels'][1]['width_m']=(50**2+5**2)**.5/40
        for p in plan['panels']:p['corner_group']=None;p['corner_net_confirmed']=False;p['reference_points']=[v[:] for v in p['points']]
        _,preview=import_pdf(vector_pdf())
        db.add(SitePlan(site_id=ids['site'],filename='oblique.pdf',pdf_data=vector_pdf(),preview_data=preview,draft=json.dumps(plan)))
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/veicoli/{vid}')
        page.get_by_role('link',name='Registra intervento',exact=True).click()
        form=page.locator('#service-form');expect(form).to_be_visible()
        form.locator('[name=title]').fill('Tagliando di controllo')
        form.locator('[name=category]').fill('Manutenzione')
        form.locator('[name=price]').fill('380')
        form.locator('[name=site_id]').select_option(str(ids['site']))
        form.locator('[name=quantity]').fill('1')
        form.locator('[name=meter]').fill('85000')
        form.locator('[name=next_meter]').fill('105000')
        expect(form.locator('[name=maintenance]')).to_be_checked()
        form.locator('[name=status]').select_option('executed')
        form.get_by_role('button',name='Salva',exact=True).click()
        expect(page.locator('#service-feedback')).to_contain_text('Salvato')
        with Session(engine) as db:
            assert db.query(ServiceRecord).count()==1 and db.query(SiteEconomicEntry).one().amount==380
        page.goto(origin+f'/manager/veicoli/{vid}')
        expect(page.locator('.fleet-history')).to_contain_text('Tagliando di controllo')
        expect(page.locator('.fleet-history')).to_contain_text('105000')
        page.screenshot(path=str(artifacts/'vehicle-services.png'),full_page=True)
        page.get_by_role('link',name='Pianifica trasporto',exact=True).click()
        expect(page.locator('select[name=mezzo_id]')).to_have_value(str(vid))
        page.goto(origin+'/manager/servizi');page.get_by_role('button',name='Nuova registrazione',exact=True).click()
        form=page.locator('#service-form');form.locator('[name=kind]').select_option('rental')
        form.locator('[name=title]').fill('Container ufficio');form.locator('[name=price]').fill('180')
        form.locator('[name=start]').fill('2026-10-01');form.locator('[name=end]').fill('2026-09-01')
        form.get_by_role('button',name='Salva',exact=True).click()
        expect(page.locator('#service-feedback')).to_contain_text('noleggio')
        expect(form.locator('[name=title]')).to_have_value('Container ufficio')
        form.locator('[name=end]').fill('2026-12-31');form.locator('[name=quantity]').fill('3')
        form.locator('[name=unit]').fill('mese');form.get_by_role('button',name='Salva',exact=True).click()
        expect(page.locator('#service-feedback')).to_contain_text('Salvato')
        page.screenshot(path=str(artifacts/'services-list.png'),full_page=True)
        page.goto(origin+'/manager/veicoli');expect(page.locator('.fleet-grid')).to_contain_text('FR-TEST')
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('.fleet-grid').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.screenshot(path=str(artifacts/'fleet-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1100})
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        expect(page.locator('[data-manual-corner]')).to_be_visible()
        page.locator('[data-manual-corner] summary').click()
        page.locator('[data-corner-target]').select_option('b')
        page.locator('[data-link-corner]').click()
        expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        expect(page.locator('[data-clean-shapes] .sp-unified')).to_have_count(1)
        page.locator('[name=corner_net_confirmed]').check()
        page.locator('[data-review-all]').click();page.locator('[data-approve]').click()
        expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        page.reload();expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        page.screenshot(path=str(artifacts/'manual-angle.png'),full_page=True)
        assert not errors,errors
        browser.close()
