import json
import os
from pathlib import Path
from datetime import datetime

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from models import SitePlan, SiteWorksMap, Site
from test_operations_live import live_operations
from test_site_works import layout
from test_site_plans import vector_pdf

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def click_point(page,selector,p):
    xy=page.locator(selector).evaluate('(svg,p)=>{const q=new DOMPoint(...p).matrixTransform(svg.getScreenCTM());return [q.x,q.y]}',p)
    page.mouse.click(*xy)


def test_general_map_persisted_workflow_and_reader(live_operations):
    origin,engine,ids,password,out=live_operations
    with Session(engine) as db:
        db.get(Site,ids['site']).numero_totale_paratie=2
        db.add(SitePlan(site_id=ids['site'],filename='reference.pdf',pdf_data=vector_pdf(),preview_data=b'png',
            draft=json.dumps(layout()),approved=json.dumps(layout()),revision=1,approved_revision=1,approved_at=datetime.utcnow()))
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/cantieri/{ids["site"]}/avanzamento';page.goto(url)
        expect(page.locator('#wm-map [data-kind=panel]')).to_have_count(2)
        page.locator('#wm-add-level').click();page.locator('#wm-fields [name=axis_ngf]').fill('6')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        level1=page.locator('#wm-level').input_value()
        page.locator('#wm-add-strut').click();click_point(page,'#wm-map',[15,70]);click_point(page,'#wm-map',[185,70])
        expect(page.locator('#wm-editor')).to_be_visible();page.locator('#wm-fields [name=label]').fill('B1-A')
        page.locator('#wm-fields [name=status]').select_option('installed');page.locator('#wm-fields [name=length_m]').fill('16')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(1)
        expect(page.locator('#wm-level-count')).to_contain_text('1 / 1')
        page.locator('#wm-add-level').click();page.locator('#wm-fields [name=axis_ngf]').fill('3')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(0)
        page.locator('#wm-level').select_option(level1);expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(1)
        page.locator('#wm-add-well').click();click_point(page,'#wm-map',[90,120]);page.locator('#wm-fields [name=status]').select_option('pumping')
        page.locator('#wm-form button[type=submit]').click();expect(page.locator('#wm-editor')).not_to_be_visible()
        expect(page.locator('#wm-map [data-kind=well]')).to_have_count(1)
        page.locator('#wm-delete').click();page.locator('#wm-confirm [value=cancel]').click();expect(page.locator('#wm-map [data-kind=well]')).to_have_count(1)
        page.locator('#wm-delete').click();page.locator('#wm-confirm [value=confirm]').click();expect(page.locator('#wm-map [data-kind=well]')).to_have_count(0)
        click_point(page,'#wm-map',[15,130]);page.locator('#wm-treat').click();expect(page.locator('#wm-detail')).to_contain_text('Completato')
        for selector in ['#wm-struts','#wm-wells']:page.locator(selector).uncheck()
        page.locator('#wm-rabotage').check();expect(page.locator('#wm-map [data-kind=panel]')).to_have_count(2)
        page.reload();expect(page.locator('#wm-phases')).to_contain_text('1 / 2 pannelli')
        page.locator('#wm-read').click()
        with page.expect_response('**/avanzamento/leggi-pdf') as uploaded:
            page.locator('#wm-upload [name=file]').set_input_files({'name':'butons.pdf','mimeType':'application/pdf','buffer':vector_pdf().replace(b'(P7a)',b'(B12)')})
            page.locator('#wm-upload button').click()
        proposal=uploaded.value.json();assert len(proposal['struts'])==1
        expect(page.locator('#wm-proposals tr')).to_have_count(1)
        page.locator('#wm-pdf-mode').select_option('align')
        raw=proposal['struts'][0]
        assert raw['a'] and raw['b']
        click_point(page,'#wm-pdf',raw['a']);click_point(page,'#wm-pdf',raw['b'])
        click_point(page,'#wm-target',[15,140]);click_point(page,'#wm-target',[185,140])
        page.locator('#wm-proposals [data-prop=panel_a]').select_option('left')
        page.locator('#wm-proposals [data-prop=panel_b]').select_option('right')
        page.locator('#wm-proposals [data-prop=reviewed]').check();page.locator('#wm-import-reviewed').check()
        page.locator('#wm-import').click();expect(page.locator('#wm-reader')).not_to_be_visible()
        expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(2)
        expect(page.locator('#wm-level-count')).to_contain_text('1 / 2')
        # Re-reading/reviewing a new source must not silently discard the first strut.
        page.reload();expect(page.locator('#wm-map [data-kind=strut]')).to_have_count(2)
        for theme in ['dark','light']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            for width in [1440,390,320]:
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(theme,width)
            page.set_viewport_size({'width':1440,'height':1100})
            page.screenshot(path=str(out/f'works-{theme}.png'),full_page=True)
        with Session(engine) as db:
            state=json.loads(db.get(SiteWorksMap,ids['site']).payload)
            assert len(state['levels'][0]['struts'])==2 and state['levels'][1]['struts']==[]
            assert state['rabotage']==[1] and state['wells']==[]
            assert json.loads(db.query(SitePlan).one().approved)==layout()
        assert not errors,errors
        browser.close()
