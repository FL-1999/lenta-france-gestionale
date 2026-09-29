import os
import json
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import SitePlan
from services.site_plan_import import import_pdf
from test_operations_live import live_operations
from test_site_plans import vector_pdf
from test_plan_corners import layout

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_oblique_fit_keeps_far_ends_and_widths_undo_approve_reload(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    data=layout();a,b=data['panels']
    a.update(label='P10a',points=[[70,30],[100,130],[80,136],[50,36]],width_m=2.5)
    b.update(label='P10b',points=[[90,125],[218,125],[218,145],[90,145]],width_m=3.2)
    for p in (a,b):p.update(reference_points=p['points'],corner_manual=True,corner_net_confirmed=False,reviewed=False)
    with Session(engine) as db:
        _,preview=import_pdf(vector_pdf())
        db.add(SitePlan(site_id=ids['site'],filename='oblique-junction.pdf',pdf_data=vector_pdf(),preview_data=preview,draft=json.dumps(data)));db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda d:d.accept())
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/cantieri/{ids["site"]}/pianta';page.goto(url)
        # Real geometry function: rotation/reflection, repeated fit, and unsuitable input.
        result=page.evaluate('''([a,b])=>{
          const fit=PlanGeometry.fitCorner(a,b),mirror=p=>p.map(([x,y])=>[-x,y]),rotate=p=>p.map(([x,y])=>[x*.8-y*.6,x*.6+y*.8]);
          return {fit,again:PlanGeometry.fitCorner(fit.first,fit.second),mirror:PlanGeometry.fitCorner(mirror(a),mirror(b)),rotate:PlanGeometry.fitCorner(rotate(a),rotate(b)),far:PlanGeometry.fitCorner(a,b.map(([x,y])=>[x+500,y])),parallel:PlanGeometry.fitCorner(b,b.map(([x,y])=>[x,y+20]))};
        }''',[a['points'],b['points']])
        fit=result['fit'];assert fit and result['mirror'] and result['rotate']
        assert result['far'] is None and result['parallel'] is None
        assert fit['first'][0]==a['points'][0] and fit['first'][3]==a['points'][3]
        assert fit['second'][1:3]==b['points'][1:3]
        assert result['again']['score']<1e-8
        page.locator('[data-fit-corner]').click();page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-message]')).to_contain_text('Giunzione rifinita')
        expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        page.locator('[data-undo-edit]').click()
        page.locator('[data-fit-corner]').click();page.locator('[data-confirm-action]').click()
        page.locator('[name=corner_net_confirmed]').check()
        page.locator('[data-review-all]').click()
        with page.expect_response(lambda r:'/convalida' in r.url and r.request.method=='PUT') as response:
            page.locator('[data-approve]').click()
        assert response.value.status==200,response.value.text()
        page.reload();expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        saved=page.request.get(url+'/data',max_retries=2).json()['plan']['layout']['panels']
        assert [p['width_m'] for p in saved]==[2.5,3.2]
        assert all(p['corner_fitted'] for p in saved)
        assert saved[0]['points'][0]==a['points'][0] and saved[1]['points'][1:3]==b['points'][1:3]
        page.locator('[data-zoom]').click();page.locator('.sp-board').filter(has=page.locator('[data-clean-svg]')).screenshot(path=str(artifacts/'oblique-junction.png'))
        assert not errors,errors
        browser.close()
