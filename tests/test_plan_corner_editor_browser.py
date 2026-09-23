import json
import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import SitePlan
from test_operations_live import live_operations
from test_plan_corners import layout
from test_site_plans import vector_pdf
from services.site_plan_import import import_pdf

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_corner_editor_constraints_join_split_and_reload(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    data = layout()
    # Imported arms have a small gap, repaired without stretching either arm.
    data['panels'][0]['points'] = [[x+2, y] for x,y in data['panels'][0]['points']]
    for p in data['panels']:
        p.pop('corner_group'); p['corner_net_confirmed'] = False
    _, preview = import_pdf(vector_pdf())
    with Session(engine) as db:
        db.add(SitePlan(site_id=ids['site'], filename='corner.pdf', pdf_data=vector_pdf(), preview_data=preview, draft=json.dumps(data)))
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width':1680,'height':1100})
        errors=[];page.on('pageerror', lambda error:errors.append(str(error)))
        page.on('dialog', lambda dialog:dialog.accept())
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/cantieri/{ids["site"]}/pianta'
        page.goto(url)
        expect(page.locator('[data-geometry-tools]')).to_be_visible()
        # A rotated edge follows its local axis; inverted geometry is rejected.
        geometry=page.evaluate('''()=>{
          const p=[[0,0],[80,60],[68,76],[-12,16]];
          return {locked:PlanGeometry.moveEdge(p,'end',5,true),
            resized:PlanGeometry.moveEdge(p,'end',5,false),
            invalid:PlanGeometry.moveEdge(p,'end',-101,false)};
        }''')
        assert geometry['locked']==[[4,3],[84,63],[72,79],[-8,19]]
        assert geometry['resized']==[[0,0],[84,63],[72,79],[-12,16]]
        assert geometry['invalid'] is None
        outlines=page.evaluate('''()=>{
          const a=[[100,130],[200,130],[200,150],[100,150]],b=[[100,50],[100,150],[80,150],[80,50]];
          const area=p=>Math.abs(p.reduce((s,v,i)=>s+v[0]*p[(i+1)%p.length][1]-p[(i+1)%p.length][0]*v[1],0))/2;
          const rotate=p=>p.map(([x,y])=>[.8*x-.6*y,.6*x+.8*y]);
          const mirror=p=>p.map(([x,y])=>[-x,y]);
          return {plain:PlanGeometry.unionOutline(a,b),areas:[area(PlanGeometry.unionOutline(a,b)),area(PlanGeometry.unionOutline(rotate(a),rotate(b))),area(PlanGeometry.unionOutline(mirror(a),mirror(b)))],
          gap:PlanGeometry.unionOutline(a.map(([x,y])=>[x+2,y]),b),
          overlap:area(PlanGeometry.unionOutline(a.map(([x,y])=>[x-10,y]),b))};
        }''')
        assert len(outlines['plain'])==6
        assert outlines['areas']==pytest.approx([4000,4000,4000])
        assert outlines['gap'] is None
        assert outlines['overlap']==pytest.approx(3800)
        page.locator('[data-original-toggle]').click()
        page.locator('[data-find-corners]').click()
        expect(page.locator('[data-corner-label]')).to_have_text('P3 A/B')
        def points(key='a'):
            return page.locator(f'[data-clean-shapes] polygon[data-key="{key}"]').evaluate('(e)=>[...e.points].map(p=>[p.x,p.y])')
        initial=points()
        page.locator('[data-nudge="1"]').click()
        moved=points()
        assert moved==[[x+2,y] for x,y in initial]
        expect(page.locator('[name=width_m]')).to_have_value('2.5')
        page.locator('[data-undo-edit]').click();assert points()==initial
        page.locator('[data-lock-width]').uncheck()
        page.locator('[data-nudge="1"]').click()
        expect(page.locator('[name=width_m]')).to_have_value('2.55')
        assert points()[0]==initial[0] and points()[1][0]==initial[1][0]+2
        page.locator('[data-undo-edit]').click();page.locator('[data-lock-width]').check()
        # Moving the body moves the whole angle, including its second branch.
        before_b=points('b')
        svg=page.locator('[data-clean-svg]')
        center=svg.evaluate('(e)=>{const p=new DOMPoint(150,140).matrixTransform(e.getScreenCTM());return {x:p.x,y:p.y}}')
        page.mouse.move(center['x'],center['y']);page.mouse.down();page.mouse.move(center['x']+12,center['y']+5,steps=4);page.mouse.up()
        dx=points()[0][0]-initial[0][0];dy=points()[0][1]-initial[0][1]
        assert abs(dx)>1
        assert points('b')[0]==pytest.approx([before_b[0][0]+dx,before_b[0][1]+dy])
        page.locator('[data-undo-edit]').click()
        page.locator('[data-join-corner]').click()
        assert points()[0][0]==pytest.approx(100)
        expect(page.locator('[data-clean-shapes] .sp-unified')).to_have_count(1)
        expect(page.locator('[data-clean-shapes] .sp-panel')).to_have_count(1)
        expect(page.locator('[data-clean-shapes] [data-unit-label]')).to_have_text('P3 A/B')
        expect(page.locator('[data-select] option')).to_have_count(1)
        expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        page.locator('[data-arm]').select_option('b')
        expect(page.locator('[data-label]')).to_have_text('P3 A/B')
        page.locator('[data-arm]').select_option('a')
        expect(page.locator('[name=width_m]')).to_have_value('2.5')
        # Lower geometry box and separate information inspector.
        tools=page.locator('[data-geometry-tools]').bounding_box();board=svg.bounding_box()
        assert tools['y']>=board['y']+board['height']
        assert page.locator('.sp-detail').bounding_box()['x']>board['x']+board['width']-1
        page.locator('[name=corner_net_confirmed]').check()
        page.locator('[data-review-all]').click();page.locator('[data-approve]').click()
        expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        saved=page.request.get(url+'/data').json()['plan']['layout']['panels']
        assert all(p['corner_group']=='a' for p in saved)
        expect(page.locator('[data-clean-shapes] .sp-unified')).to_have_count(1)
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto')
        card=page.locator('[data-coupe-card]').first
        expect(card.locator('.coupe-panel-grid button')).to_have_text(['P3 A/B'])
        expect(card.locator('.coupe-plan polygon')).to_have_count(1)
        card.locator('.coupe-panel-grid button').click()
        expect(card.locator('[name=coupe_paratie]')).to_have_value(','.join(str(p['element']) for p in saved))
        expect(card.locator('[data-selection-summary]')).to_have_text('1 pannello')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}')
        expect(page.locator('.sw-panel-list button')).to_have_text(['P3 A/B'])
        expect(page.locator('#sw-plan .sw-panel')).to_have_count(1)
        page.locator('.sw-panel-list button').click()
        expect(page.locator('#sw-panel-detail strong')).to_have_text('P3 A/B')
        page.goto(url)
        page.reload();page.locator('[data-edit]').click()
        expect(page.locator('[data-corner-info]')).to_be_visible()
        page.locator('[data-remove]').click();page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-counter]')).to_have_text('0 pannelli')
        page.locator('[data-undo-removal]').click()
        expect(page.locator('[data-select] option')).to_have_count(1)
        page.locator('[data-original-toggle]').click()
        page.evaluate("document.documentElement.dataset.theme='dark'")
        page.locator('#site-plan-app').screenshot(path=str(artifacts/'corner-editor-it.png'))
        page.locator('.sp-board').filter(has=page.locator('[data-clean-svg]')).screenshot(path=str(artifacts/'corner-unified.png'))
        # French interface and responsive editor, including all editing controls.
        page.context.add_cookies([{'name':'lang','value':'fr','url':origin}]);page.reload();page.locator('[data-edit]').click()
        expect(page.locator('[data-join-corner]')).to_have_text('Raccorder l’angle')
        for theme in ['dark','light']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            for width in [1680,1024,390,320]:
                page.set_viewport_size({'width':width,'height':1100})
                assert page.locator('#site-plan-app').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'), (theme,width)
            page.set_viewport_size({'width':1680,'height':1400})
            page.locator('[data-original-toggle]').click() if page.locator('#site-plan-app').get_attribute('data-original')=='true' else None
            page.locator('#site-plan-app').screenshot(path=str(artifacts/f'corner-editor-{theme}.png'))
        page.locator('[data-split-corner]').click()
        expect(page.locator('[data-corner-info]')).to_be_hidden()
        expect(page.locator('[data-clean-shapes] .sp-unified')).to_have_count(0)
        expect(page.locator('[data-select] option')).to_have_count(2)
        page.locator('[data-review-all]').click();page.locator('[data-approve]').click()
        expect(page.locator('[data-state]')).to_have_text('Plan validé')
        split=page.request.get(url+'/data').json()['plan']['layout']['panels']
        assert not any(p.get('corner_group') for p in split)
        assert [p['element'] for p in split]==[p['element'] for p in saved]
        assert not errors,errors
        print('Screenshots:',artifacts)
        browser.close()
