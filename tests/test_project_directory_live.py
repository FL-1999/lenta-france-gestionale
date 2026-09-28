import os
import re
from datetime import date, timedelta
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Supplier, ServiceRecord, SiteEconomicEntry, ProjectPartner
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_rental_site_without_vehicle_and_directory_roundtrip(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        db.add(Supplier(name='Location bungalows'));db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/servizi?new=1&site_id={ids["site"]}')
        form=page.locator('#service-form');expect(form).to_be_visible()
        form.locator('[name=kind]').select_option('rental')
        expect(form.locator('[name=site_id]')).to_have_value(str(ids['site']))
        expect(form.locator('[data-maintenance-controls]')).to_be_hidden()
        form.locator('[name=title]').fill('Baracca ufficio cantiere')
        form.locator('[name=price]').fill('180');form.locator('[name=quantity]').fill('2')
        form.locator('[name=start]').fill(str(date.today()-timedelta(days=60)))
        form.locator('[name=end]').fill(str(date.today()))
        form.locator('[name=status]').select_option('executed')
        page.screenshot(path=str(artifacts/'rental-site-form.png'),full_page=True)
        form.get_by_role('button',name='Salva',exact=True).click()
        expect(page.locator('#service-feedback')).to_contain_text('Salvato')
        with Session(engine) as db:
            r=db.query(ServiceRecord).one();assert r.site_id==ids['site'] and r.vehicle_id is None and r.machine_id is None
            assert db.query(SiteEconomicEntry).one().amount==360
        page.goto(origin+f'/manager/rubrica/nuovo?site_id={ids["site"]}')
        form=page.locator('#directory-form');form.locator('[name=name]').fill('Bâtisseurs Méditerranée')
        form.locator('[name=contact_name]').fill('Camille Martin');form.locator('[name=city]').fill('Nice')
        form.locator('[name=phone]').fill('+33 4 00 00 00 00');form.locator('[name=email]').fill('camille@example.com')
        form.locator('[name=categories][value=moe]').check();form.locator('[name=categories][value=gros_oeuvre]').check()
        form.get_by_role('button',name='Salva scheda',exact=True).click()
        expect(page.locator('#directory-feedback')).to_contain_text('ruolo')
        expect(form.locator('[name=contact_name]')).to_have_value('Camille Martin')
        form.locator('[data-role][value=moe]').check()
        form.get_by_role('button',name='Collega cantiere').click()
        form.locator('[data-site]').nth(1).select_option(str(ids['other']))
        form.get_by_role('button',name='Salva scheda',exact=True).click()
        page.wait_for_url(re.compile(r'/manager/rubrica/\d+\?saved=1'))
        detail=page.url;expect(page.get_by_role('heading',name='Bâtisseurs Méditerranée',exact=True)).to_be_visible()
        expect(page.locator('.directory-project')).to_have_count(2)
        page.screenshot(path=str(artifacts/'directory-detail.png'),full_page=True)
        page.get_by_role('link',name='Cantiere Collaudo',exact=True).click()
        expect(page.locator('#site-partners')).to_contain_text('Bâtisseurs Méditerranée')
        page.locator('#site-partners').get_by_role('link',name='Bâtisseurs Méditerranée',exact=True).click()
        page.get_by_role('link',name='Modifica scheda e cantieri',exact=True).click()
        form=page.locator('#directory-form');expect(form.locator('[data-site]')).to_have_count(2)
        form.locator('[name=notes]').fill('Collaborazione continuativa')
        form.get_by_role('button',name='Salva scheda',exact=True).click();page.wait_for_url(detail)
        page.context.add_cookies([{'name':'lang','value':'fr','url':origin}]);page.reload()
        expect(page.get_by_role('heading',name='Informations générales',exact=True)).to_be_visible()
        page.get_by_role('link',name='Tout l’annuaire',exact=True).click()
        page.locator('[name=category]').select_option('moe');page.get_by_role('button',name='Filtrer',exact=True).click()
        expect(page.locator('.directory-card')).to_have_count(1)
        page.screenshot(path=str(artifacts/'directory-list-fr.png'),full_page=True)
        for theme in ['light','dark']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('.directory-grid').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            page.screenshot(path=str(artifacts/f'directory-mobile-{theme}.png'),full_page=True)
        with Session(engine) as db:
            assert len(db.query(ProjectPartner).one().projects)==2
        assert not errors,errors
        print('Directory screenshots:',artifacts)
        browser.close()
