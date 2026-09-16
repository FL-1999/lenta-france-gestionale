"""Populated-page visual/interaction regressions for the reported screenshots."""
import os
import re
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import Fiche, FicheStratigrafia, FicheTypeEnum, PersonalePresenza, User
from models.veicoli import Veicolo
from main import _wrap_sheet_document
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Live browser checks opt-in')


def test_feedback_pages_with_real_records(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
        fiche = Fiche(date=date(2026,9,16),numero_pannello=1,site_id=ids['site'],created_by_id=manager.id,
                      fiche_type=FicheTypeEnum.produzione,description='Scheda di collaudo',tipologia_scavo='paratia',
                      quota_tn=25,quota_partenza=25,quota_ngf_testa=25,quota_ngf_fondo=8,
                      profondita_totale=17,larghezza_pannello=5,altezza_pannello=.62,
                      terreno_teorico='0-1 m: Riporto\n1-9 m: Sabbia\n9-17 m: Argilla')
        fiche.stratigrafie=[FicheStratigrafia(da_profondita=a,a_profondita=b,materiale=m) for a,b,m in [(0,1,'Riporto'),(1,10,'Sabbia'),(10,17,'Argilla')]]
        db.add(fiche)
        db.add(Veicolo(marca='Camion',modello='Prova',targa='TEST-FEEDBACK',visibile_trasporti=True))
        db.add(PersonalePresenza(personale_id=ids['person'],attendance_date=date(2026,9,14),status='WORK',hours=8))
        db.commit(); fiche_id=fiche.id
    output = Path(os.getenv('WORKSPACE_SCREENSHOTS',str(artifacts))); output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login'); page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password); page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        for path in ['/manager/veicoli','/manager/trasporti','/manager/personale','/manager/ordini','/manager/fiches']:
            assert page.goto(origin+path).status == 200
            expect(page.locator('h1')).not_to_contain_text('👥')
            expect(page.locator('h1')).not_to_contain_text('🚐')
        page.goto(origin+'/manager/personale')
        expect(page.locator('.page-title svg')).to_have_count(1)
        expect(page.locator('.table-actions .btn').first.locator('svg')).to_have_count(1)
        page.goto(origin+'/manager/personale/presenze?week_start=2026-09-14')
        expect(page.locator('.attendance-day')).to_have_count(5)
        page.get_by_label('Sabato',exact=True).check()
        page.locator('.week-selector button[type=submit]').click()
        expect(page.locator('.attendance-day')).to_have_count(6)
        page.locator('.attendance-person form button').click()
        expect(page.locator('.attendance-day')).to_have_count(6)
        with Session(engine) as db:
            rows=db.query(PersonalePresenza).filter_by(personale_id=ids['person']).all()
            assert {row.attendance_date.weekday() for row in rows} == set(range(5))
        page.goto(origin+f'/manager/fiches/{fiche_id}')
        expect(page.locator('#technical-sheet-export')).to_be_visible()
        expect(page.locator('.stratigrafia-technical-panel')).to_have_count(0)
        expect(page.locator('.technical-ground-bars')).to_be_visible()
        for theme in ['light','dark']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            for width in [1440,1024,390]:
                page.set_viewport_size({'width':width,'height':1000})
                page.wait_for_function('''() => {
                  const sheet=document.querySelector('#technical-sheet-export').getBoundingClientRect();
                  const wrap=document.querySelector('[data-sheet-viewport]').getBoundingClientRect();
                  return sheet.right <= wrap.right+1 && Math.abs(sheet.height-wrap.height)<2;
                }''')
                bounds=page.locator('#technical-sheet-export').evaluate('''sheet=>{
                  const b=sheet.getBoundingClientRect();
                  const bars=sheet.querySelector('.technical-ground-bars').getBoundingClientRect();
                  return {fits:bars.right<=b.right+1,ink:getComputedStyle(sheet.querySelector('h3')).color,overflow:document.documentElement.scrollWidth>innerWidth+1};
                }''')
                assert bounds == {'fits':True,'ink':'rgb(17, 17, 17)','overflow':False}, bounds
                page.locator('.technical-coupe-card').screenshot(path=str(output/f'fiche-{theme}-{width}.png'))
        # Exercise the same paper CSS/wrapper as the PDF exporter with the
        # populated technical article, independently of the screen transform.
        article = page.locator('#technical-sheet-export').evaluate('(sheet)=>sheet.outerHTML')
        paper = browser.new_page()
        html = _wrap_sheet_document(article,Path('static/css/style.css').read_text(encoding='utf-8'))
        paper.set_content(html.replace('<head>',f'<head><base href="{origin}">'),wait_until='networkidle')
        paper.emulate_media(media='print')
        assert paper.locator('#technical-sheet-export').evaluate('''sheet=>{
          const r=sheet.getBoundingClientRect();
          const parts=['.technical-ground-column','.technical-sheet__header-top','.technical-visa-block'];
          return r.width<=198*96/25.4+1 && parts.every(s=>sheet.querySelector(s).getBoundingClientRect().right<=r.right);
        }''')
        pdf = paper.pdf(path=str(output/'fiche-print.pdf'),format='A4',print_background=True,prefer_css_page_size=True)
        assert len(re.findall(rb'/Type\s*/Page\b',pdf)) == 1
        paper.close()
        for path,name in [('/manager/fiches','fiches'),('/manager/personale','personale'),('/manager/personale/presenze?week_start=2026-09-14','presenze'),('/manager/ordini','ordini')]:
            page.set_viewport_size({'width':1440,'height':1000});page.goto(origin+path)
            page.evaluate("document.documentElement.dataset.theme='dark'")
            page.screenshot(path=str(output/f'{name}-dark.png'),full_page=True)
        assert not errors,errors
        browser.close()
