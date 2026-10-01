import json
import os
from datetime import datetime

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import SitePlan, SiteStrutLevel, SiteCoupe, Site
from test_operations_live import live_operations
from test_site_plans import vector_pdf
from test_site_works import layout
from test_site_works_browser import click_point

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_unified_progress_configuration_and_editable_automatic_metres(live_operations):
    origin,engine,ids,password,out=live_operations
    with Session(engine) as db:
        db.get(Site,ids['site']).numero_totale_paratie=2
        db.add(SitePlan(site_id=ids['site'],filename='reference.pdf',pdf_data=vector_pdf(),preview_data=b'png',
            draft=json.dumps(layout()),approved=json.dumps(layout()),revision=1,approved_revision=1,approved_at=datetime.utcnow()))
        db.add(SiteStrutLevel(site_id=ids['site'],level_index=1,total_struts_level=6,done_struts_level=2))
        db.add(SiteCoupe(site_id=ids['site'],nome='Coupe 1',drawing_info={'reviewed':True,'struts':[12],
            'treatment':{'state':'present','top':3.3,'bottom':None}}))
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/cantieri/{ids["site"]}/avanzamento';page.goto(url)
        expect(page.locator('#wm-phases [data-phase=guides]')).to_contain_text('0 / 32 m')
        expect(page.locator('#wm-phases [data-phase=struts]')).to_contain_text('2 / 6 posati')
        expect(page.locator('#wm-level')).to_contain_text('12 NGF')
        expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(0)
        assert page.locator('#wm-config').get_attribute('open') is None
        assert page.locator('#wm-coupe-info').get_attribute('open') is None
        expect(page.locator('#wm-coupe-info .coupe-site-info')).not_to_be_visible()
        page.screenshot(path=str(out/'works-unified-overview.png'))
        assert page.locator('#wm-map').bounding_box()['y']<750

        page.locator('#wm-phases [data-phase=guides]').click()
        expect(page.locator('#wm-fields [name=guide_auto]')).to_be_checked()
        expect(page.locator('#wm-fields [name=cordoli_total_m]')).to_be_disabled()
        page.locator('#wm-fields [name=cordoli_done_m]').fill('8')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-phases [data-phase=guides] strong')).to_have_text('25%')
        page.locator('#wm-phases [data-phase=installation]').click()
        page.locator('#wm-fields [name=installazione_cantiere_pct]').fill('30')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        page.reload();expect(page.locator('#wm-phases [data-phase=installation] strong')).to_have_text('30%')
        expect(page.locator('#wm-phases [data-phase=guides]')).to_contain_text('8 / 32 m')
        page.locator('#wm-phases [data-phase=guides]').click()
        page.locator('#wm-fields [name=guide_auto]').uncheck()
        page.locator('#wm-fields [name=cordoli_total_m]').fill('40')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        page.reload();expect(page.locator('#wm-phases [data-phase=guides]')).to_contain_text('8 / 40 m')
        page.locator('#wm-phases [data-phase=guides]').click();page.locator('#wm-fields [name=guide_auto]').check()
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-phases [data-phase=guides]')).to_contain_text('8 / 32 m')

        page.locator('#wm-phases [data-phase=struts]').click()
        expect(page.locator('#wm-config-data')).to_be_visible()
        expect(page.locator('#wm-config-data')).to_contain_text('2 / 6 posati')
        page.locator('#wm-config-data [data-config-level]').click()
        page.locator('#wm-fields [name=planned_count]').fill('8')
        page.locator('#wm-fields [name=completed_count]').fill('3')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        page.reload();expect(page.locator('#wm-phases [data-phase=struts]')).to_contain_text('3 / 8 posati')
        expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(0)
        page.locator('#wm-add-strut').click();click_point(page,'#wm-map',[15,70]);click_point(page,'#wm-map',[185,70])
        page.locator('#wm-fields [name=label]').fill('B1-A')
        page.locator('#wm-fields [name=status]').select_option('installed')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-phases [data-phase=struts]')).to_contain_text('1 / 1 posati')
        page.locator('#wm-config summary').click()
        expect(page.locator('#wm-config-data')).to_contain_text('conteggio dalla mappa')
        page.locator('#wm-config-data [data-config-level]').click()
        expect(page.locator('#wm-fields [name=planned_count]')).to_have_count(0)
        page.locator('#wm-editor [data-close]').click()
        page.locator('#wm-config summary').click()
        page.locator('#wm-phases [data-phase=struts]').click()
        expect(page.locator('#wm-detail')).to_contain_text('B1-A')
        page.locator('#wm-phases [data-phase=rabotage]').click()
        expect(page.locator('#wm-rabotage')).to_be_checked()
        click_point(page,'#wm-map',[15,130]);page.locator('#wm-treat').click()
        expect(page.locator('#wm-phases [data-phase=rabotage] strong')).to_have_text('50%')
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()


def test_configure_level_and_progress_without_a_plan(live_operations):
    origin,engine,ids,password,out=live_operations
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/avanzamento#configuration')
        expect(page.locator('#wm-config-level')).to_be_visible()
        page.locator('#wm-config-level').click()
        page.locator('#wm-fields [name=planned_count]').fill('6')
        page.locator('#wm-fields [name=completed_count]').fill('2')
        page.locator('#wm-fields [name=axis_ngf]').fill('12')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        page.reload();expect(page.locator('#wm-config-data')).to_contain_text('2 / 6 posati')
        expect(page.locator('#wm-phases [data-phase=struts] strong')).to_have_text('33%')
        expect(page.locator('#wm-empty')).to_be_visible()
        page.locator('#wm-phases [data-phase=guides]').click()
        page.locator('#wm-fields [name=guide_auto]').uncheck()
        page.locator('#wm-fields [name=cordoli_total_m]').fill('40')
        page.locator('#wm-fields [name=cordoli_done_m]').fill('10')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-phases [data-phase=guides] strong')).to_have_text('25%')
        assert not errors,errors
        browser.close()
