import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site, SiteCoupe, SiteCoupeAssignment, Fiche
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_depth_and_elevation_roundtrip_and_partial_fiche(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        db.get(Site, ids['site']).numero_totale_paratie = 1
        coupe = SiteCoupe(site_id=ids['site'], nome='Coupe 1', quota_tn=14.5, quota_testa=13.5,
                          scavo_da_tn=False, quota_partenza_scavo=13.5, quota_fondo_teorica=2.8,
                          profondita_teorica=10.7, spessore=.42)
        db.add(coupe); db.flush()
        cid = coupe.id
        db.add(SiteCoupeAssignment(site_id=ids['site'], coupe_id=cid, tipologia_scavo='paratia', numero_elemento=1))
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login'); page.locator('#email').fill('smoke-manager@example.com'); page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click(); page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto')
        card = page.locator('[data-coupe-card]').first
        card.locator('.coupe-editor').evaluate('(el)=>el.open=true')
        card.locator('[data-soil-mode]').select_option('elevation')
        row = card.locator('[data-theoretical-layer]').first
        row.locator('[data-soil-elevation=start]').fill('13.5')
        row.locator('[data-soil-elevation=end]').fill('12.5')
        row.locator('select').select_option('Remblais')
        card.locator('[data-add-theoretical-layer]').click()
        row = card.locator('[data-theoretical-layer]').nth(1)
        expect(row.locator('[data-soil-elevation=start]')).to_have_value('12.50')
        row.locator('[data-soil-elevation=end]').fill('-1')
        row.locator('select').select_option('Sable')
        for _ in range(3):
            card.locator('[data-soil-mode]').select_option('depth')
            expect(row.locator('[data-layer-a]')).to_have_value('14.5')
            card.locator('[data-soil-mode]').select_option('elevation')
            expect(row.locator('[data-soil-elevation=end]')).to_have_value('-1.00')
        expect(card.locator('[data-soil-summary]')).to_contain_text('13.50 → 12.50 NGF')
        card.locator('[name=coupe_quota_partenza_scavo]').fill('0')
        expect(card.locator('[data-soil-origin]')).to_contain_text('0.00 NGF')
        expect(row.locator('[data-soil-elevation=end]')).to_have_value('-14.50')
        card.locator('[name=coupe_quota_partenza_scavo]').fill('13.5')
        expect(card.locator('[name=coupe_profondita_teorica]')).to_have_value('10.7')
        for width in [390, 1440]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        card.locator('[data-theoretical-soil]').screenshot(path=str(Path(artifacts)/'soil-editor.png'))
        page.locator('.project-config-form button[type=submit]').click()
        page.wait_for_url('**/*saved*')
        with Session(engine) as db:
            assert db.get(SiteCoupe, cid).terreno_teorico.replace('\r\n', '\n') == '0-1 m: Remblais\n1-14.5 m: Sable'
        page.goto(origin+f'/manager/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=1&tipologia_scavo=paratia')
        expect(page.locator('#quota_partenza')).to_have_value('13.5')
        expect(page.locator('#scavo_da_tn')).to_have_value('0')
        page.locator('#data_scavo').fill('2026-09-30'); page.locator('#operatore').fill('Squadra')
        page.locator('#larghezza_pannello').fill('2.5'); page.locator('#profondita_totale').fill('2')
        expect(page.locator('#quota_ngf_fondo')).to_have_value('11.50')
        assert not errors, errors
        page.locator('[data-fiche-soil] [data-soil-mode]').select_option('elevation')
        page.locator('[data-soil-elevation=start]').fill('13.5'); page.locator('[data-soil-elevation=end]').fill('12.5')
        page.locator('[name=strato_materiale]').select_option('riporto')
        page.locator('#add-strato-btn').click()
        added = page.locator('.strato-row').last
        added.locator('[data-soil-elevation=start]').fill('12.5'); added.locator('[data-soil-elevation=end]').fill('11.5')
        added.locator('[name=strato_materiale]').select_option('sabbia')
        page.locator('[data-fiche-form] button[type=submit]').click()
        assert page.evaluate('''() => [...document.querySelectorAll('input,select')].filter(e=>!e.validity.valid).map(e=>({name:e.name,value:e.value,error:e.validationMessage}))''') == []
        assert page.locator('[role=alert]:visible').all_text_contents() == []
        page.wait_for_url('**/manager/fiches/*')
        with Session(engine) as db:
            item = db.query(Fiche).one(); fid = item.id
            assert item.profondita_totale == 2 and item.quota_partenza == 13.5 and item.quota_ngf_fondo == 11.5
            assert sorted(layer.a_profondita for layer in item.stratigrafie) == [1, 2]
        page.goto(origin+f'/manager/fiches/{fid}/modifica')
        expect(page.locator('#quota_partenza')).to_have_value('13.5')
        page.locator('#profondita_totale').fill('3'); page.locator('[data-strato-a]').last.fill('3')
        page.locator('[data-fiche-form] button[type=submit]').click()
        page.wait_for_url(f'**/manager/fiches/{fid}')
        expect(page.locator('[data-fiche-level-summary]')).to_contain_text('12.50 → 10.50')
        page.locator('[data-fiche-level-summary]').screenshot(path=str(Path(artifacts)/'soil-levels.png'))
        assert not errors, errors
        browser.close()
