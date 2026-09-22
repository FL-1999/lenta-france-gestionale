import json, os, math
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site, SitePlan, SiteProgressGridName
from test_operations_live import live_operations
from test_site_plans import vector_pdf
from services.site_plan_import import import_pdf

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_french_coupe_errors_soil_and_plan_actions(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    layout,preview=import_pdf(vector_pdf());layout['scale_ppm']=140/5.2
    panel=layout['panels'][0];panel.update(points=[[50,100],[190,100],[190,125],[50,125]],width_m=5.2,label='P10',element=1,reviewed=False)
    panel['reference_points']=[p[:] for p in panel['points']]
    other={**panel,'key':'neighbour','label':'P2','element':2,'points':[[194,100],[334,100],[334,125],[194,125]]}
    other['reference_points']=[p[:] for p in other['points']];layout['panels'].append(other)
    with Session(engine) as db:
        db.get(Site,ids['site']).numero_totale_paratie=3
        for n,label in [(1,'P10'),(2,'P2'),(3,'P7A')]:db.add(SiteProgressGridName(site_id=ids['site'],tipologia_scavo='paratia',numero_elemento=n,nome_personalizzato=label))
        db.add(SitePlan(site_id=ids['site'],filename='Plan.pdf',pdf_data=vector_pdf(),preview_data=preview,draft=json.dumps(layout)))
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.context.add_cookies([{'name':'lang','value':'fr','url':origin}])
        config=origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto';page.goto(config)
        card=page.locator('[data-coupe-card]').first
        expect(card.locator('.coupe-panel-grid button')).to_have_text(['P2','P7A','P10'])
        card.get_by_role('button',name='P2',exact=True).click()
        for name,value in {'coupe_nome':'Coupe française','coupe_quota_tn':'10','coupe_quota_fondo_teorica':'-5','coupe_profondita_teorica':'8','coupe_note':'Conserver mes observations'}.items():card.locator(f'[name={name}]').fill(value)
        soil=card.locator('[data-theoretical-layer]').first
        soil.locator('[data-layer-da]').fill('0');soil.locator('[data-layer-a]').fill('2');soil.locator('select').select_option('Sable')
        card.locator('[data-add-theoretical-layer]').click()
        soil=card.locator('[data-theoretical-layer]').nth(1)
        expect(soil.locator('[data-layer-da]')).to_have_value('2')
        soil.locator('[data-layer-a]').fill('15');soil.locator('select').select_option('Argile')
        page.get_by_role('button',name='Enregistrer la configuration du projet',exact=True).click()
        expect(page.locator('#coupe-errors')).to_contain_text('Cotes incohérentes')
        card=page.locator('[data-coupe-card]').first
        expect(card.locator('[name=coupe_note]')).to_have_value('Conserver mes observations')
        expect(card.locator('[name=coupe_paratie]')).to_have_value('2')
        expect(card.locator('[name=coupe_profondita_teorica]')).to_have_attribute('aria-invalid','true')
        expect(card.locator('[data-theoretical-layer]')).to_have_count(2)
        output=Path('.venv/coupe-qa');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'validation-fr.png'),full_page=True)
        card.locator('[name=coupe_profondita_teorica]').fill('15')
        page.get_by_role('button',name='Enregistrer la configuration du projet',exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('enregistrée')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        expect(page.locator('[data-snap-target]')).to_have_count(1)
        corner=page.evaluate('''() => PlanGeometry.snap(
            [[0,0],[100,0],[100,20],[0,20]],
            [[104,0],[124,0],[124,120],[104,120]])''')
        assert corner['distance']==pytest.approx(4)
        assert corner['points']==[[4,0],[104,0],[104,20],[4,20]]
        page.on('dialog',lambda dialog:dialog.accept())
        page.locator('.sp-snap summary').click();page.locator('[data-snap-target]').select_option('neighbour')
        page.locator('[data-snap]').click();expect(page.locator('[data-message]')).to_contain_text('Bords raccordés')
        page.locator('[data-undo-snap]').click()
        page.locator('[data-snap]').click()
        page.locator('[data-review-all-top]').click();page.locator('[data-approve]').click()
        expect(page.locator('[data-state]')).to_have_text('Plan validé')
        state=page.request.get(origin+f'/manager/cantieri/{ids["site"]}/pianta/data').json()
        first,second=state['plan']['layout']['panels']
        assert first['reviewed'] and second['reviewed'] and first['extent_confirmed']
        assert first['points'][1]==second['points'][0]
        assert math.dist(first['points'][0],first['points'][1])==pytest.approx(140)
        page.goto(config)
        page.locator('.coupe-editor').first.evaluate('(e)=>e.open=true')
        page.add_style_tag(content='*,*::before,*::after{transition:none!important;animation:none!important}')
        for theme in ['dark','light']:
            page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(output/f'coupe-{theme}-{width}.png'),full_page=True)
        page.goto(origin+f'/manager/cantieri/{ids["site"]}')
        expect(page.locator('#sw-groups')).to_contain_text('Sélectionnez les panneaux')
        page.locator('.sw-panel-list [data-panel="2"]').click()
        expect(page.locator('#sw-panel-detail')).to_contain_text('Créer une fiche')
        assert '${tr(' not in page.locator('#site-workspace').inner_text()
        assert not errors,errors
        browser.close()
