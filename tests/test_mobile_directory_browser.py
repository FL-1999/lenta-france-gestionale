"""Compact phone directories use the existing routes, filters and form controls."""
import os
from datetime import date

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from auth import hash_password
from models import (User, RoleEnum, Site, Personale, Report, Fiche, FicheTypeEnum,
                    MagazzinoItem, Machine)
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_compact_directories_actions_filters_and_desktop(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        capo = db.query(User).filter_by(email='smoke-capo@example.com').one()
        site = db.get(Site, ids['site'])
        site.name, site.code, site.city = 'NISSA CAMPUS', '26-340', 'Nice'
        db.get(Site, ids['other']).name = 'Cantiere riservato altra squadra'
        db.get(Machine, ids['machine']).site_id = site.id
        third = Site(name='Résidence Les Jardins de Saint-Laurent', code='26-341', city='Antibes', is_active=True)
        person = Personale(nome='Giovanni', cognome='De Santis', ruolo='meccanico / operatore',
                           telefono='+33 6 12 34 56 78', email='giovanni@example.test', attivo=True)
        article = MagazzinoItem(nome='Catena di sollevamento a quattro bracci', codice='SOL-104',
                                unita_misura='pz', quantita_disponibile=12, soglia_minima=4, attivo=True)
        archived = MagazzinoItem(nome='Articolo archiviato collaudo', codice='ARC-1', attivo=False)
        report = Report(date=date.today(), site_id=site.id, site_name_or_code=site.name,
                        total_hours=16, workers_count=2, activities='Preparazione muretti guida', created_by_id=capo.id)
        fiche = Fiche(date=date.today(), site_id=site.id, numero_pannello=2, panel_name='2 A',
                      tipologia_scavo='paratia', fiche_type=FicheTypeEnum.produzione,
                      description='Fiche di collaudo', created_by_id=capo.id, review_status='pending')
        confirmed = Fiche(date=date.today(), site_id=site.id, numero_pannello=3, panel_name='3 A',
                          tipologia_scavo='paratia', fiche_type=FicheTypeEnum.produzione,
                          description='Produzione confermata', created_by_id=capo.id, review_status='confirmed')
        db.add_all([third, person, article, archived, report, fiche, confirmed]); db.commit()
        person_id, fiche_id, archived_id = person.id, fiche.id, archived.id
    with sync_playwright() as pw:
        engine_name = os.getenv('MOBILE_BROWSER_ENGINE', 'chromium')
        launch_options = {'channel': os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None} if engine_name == 'chromium' else {}
        browser = getattr(pw, engine_name).launch(**launch_options)
        context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True,
                                      has_touch=True, reduced_motion='reduce')
        page = context.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin+'/') else r.abort())

        def login(email, destination):
            page.goto(origin+'/login'); page.locator('#email').fill(email); page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click(); page.wait_for_url('**'+destination)

        def fits():
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), page.url
            issues = page.locator('.mobile-directory-row:visible').evaluate_all('''rows => rows.flatMap(row => {
                const name=row.querySelector('.mobile-directory-name').getBoundingClientRect();
                return row.scrollWidth<=row.clientWidth+1 && name.width>=175 && row.getBoundingClientRect().height<200 ? [] :
                    [{text:row.innerText,nameWidth:name.width,width:row.clientWidth,scroll:row.scrollWidth,height:row.getBoundingClientRect().height}];
            })''')
            if issues: page.screenshot(path=str(out/'layout-issue.png'),full_page=True)
            assert not issues, (page.url, issues)

        login('smoke-manager@example.com', '/manager/dashboard')
        for width in [390, 320]:
            page.set_viewport_size({'width':width, 'height':844})
            page.goto(origin+'/manager/cantieri?stato=tutti')
            expect(page.locator('.mobile-directory-row')).to_have_count(3)
            expect(page.locator('.list-cards')).not_to_be_visible()
            expect(page.locator('table[data-mobile-directory]')).not_to_be_visible()
            fits()
            row = page.locator('.mobile-directory-row').filter(has_text='NISSA CAMPUS')
            expect(row).to_contain_text('26-340'); expect(row).to_contain_text('Nice')
            expect(row).to_contain_text('Progetto da configurare')
            assert row.locator('.mobile-directory-name').get_attribute('href').endswith(f"/manager/sites/{ids['site']}")
            row.locator('.mobile-directory-more').click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_contain_text('Capo Collaudo')
            expect(dialog.get_by_role('link', name='Avanzamento', exact=False)).to_be_visible()
            assert dialog.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            page.screenshot(path=str(out/f'cantieri-menu-{width}.png'))
            page.keyboard.press('Escape'); expect(dialog).not_to_be_visible()
            expect(row.locator('.mobile-directory-more')).to_be_focused()
            row.locator('.mobile-directory-more').click()
            dialog.get_by_role('button', name='Mappa', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(page.locator('#site-map-preview-modal')).to_have_attribute('aria-hidden','false')
            page.locator('#site-map-preview-modal button[data-site-map-close]').click()
            page.locator('#list-search').fill('residence')
            expect(page.locator('.mobile-directory-row:visible')).to_have_count(1)
            expect(page.locator('.mobile-directory-row:visible')).to_contain_text('Résidence')
            page.locator('#list-search').fill('impossibile trovare')
            expect(page.locator('.mobile-directory-row:visible')).to_have_count(0)
            page.locator('#list-search').fill('')
            expect(page.locator('.mobile-directory-row:visible')).to_have_count(3)
            page.locator('.mobile-directory').scroll_into_view_if_needed()
            page.screenshot(path=str(out/f'cantieri-compatto-{width}.png'))
        # The same DOM retains the desktop table and all its original actions.
        page.locator('.mobile-directory-more').first.click()
        page.set_viewport_size({'width':1440, 'height':1000})
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.locator('table[data-mobile-directory]')).to_be_visible()
        expect(page.locator('.mobile-directory')).not_to_be_visible()
        assert page.locator('table[data-mobile-directory]').evaluate('(e)=>getComputedStyle(e).display') == 'table'
        expect(page.locator('table .btn-site-map')).to_have_count(3)
        page.screenshot(path=str(out/'cantieri-desktop.png'), full_page=True)
        page.emulate_media(media='print')
        expect(page.locator('table[data-mobile-directory]')).to_be_visible()
        expect(page.locator('.mobile-directory')).not_to_be_visible()
        page.emulate_media(media='screen')
        page.set_viewport_size({'width':390, 'height':844})
        page.goto(origin+'/manager/personale')
        row = page.locator('.mobile-directory-row').filter(has_text='De Santis Giovanni')
        row.locator('.mobile-directory-more').click()
        expect(page.get_by_role('dialog')).to_contain_text('+33 6 12 34 56 78')
        expect(page.get_by_role('dialog')).to_contain_text('giovanni@example.test')
        expect(page.get_by_role('dialog').get_by_role('button', name='Elimina', exact=False)).to_have_count(0)
        page.keyboard.press('Escape')
        row.locator('.mobile-directory-name').click()
        page.wait_for_url(f'**/manager/personale/{person_id}/edit')
        # Other office directories, including their empty states, remain usable at 320px.
        for path in ['/manager/personale', '/manager/rapportini', f'/manager/fiches?site_id={ids["site"]}',
                     '/manager/magazzino?view=all', '/manager/magazzino/archiviati',
                     '/manager/magazzino/sotto-soglia', '/manager/magazzino/movimenti',
                     '/manager/magazzino/richieste', '/manager/macchinari', '/manager/attrezzature',
                     '/manager/trasporti', '/manager/depositi', '/manager/report/produzione',
                     f'/manager/cantieri/{ids["site"]}/documenti', '/gabbie']:
            page.set_viewport_size({'width':320,'height':844})
            response = page.goto(origin+path); assert response.ok, (path,response.status)
            fits()
            if path == '/manager/magazzino?view=all':
                expect(page.get_by_role('link', name='Catena di sollevamento a quattro bracci', exact=True)).to_be_visible()
                assert page.locator('.warehouse-row-name').evaluate('(e)=>e.getBoundingClientRect().width>=190')
                expect(page.locator('.warehouse-row-stock')).to_contain_text('12')
            if path == '/manager/magazzino/archiviati':
                page.locator('.mobile-directory-more').click()
                page.get_by_role('dialog').get_by_role('button',name='Riattiva articolo',exact=False).click()
                page.wait_for_load_state('networkidle')
                with Session(engine) as db:
                    assert db.get(MagazzinoItem, archived_id).attivo
            if path == '/manager/report/produzione':
                expect(page.locator('.mobile-directory')).to_contain_text('TOTALE')
            if path.endswith('/documenti'):
                expect(page.locator('.mobile-directory-name')).to_have_attribute('target','_blank')
                expect(page.locator('.mobile-directory')).to_contain_text('originale.txt')
            page.screenshot(path=str(out/('office-'+path.split('?')[0].split('/')[-1]+'.png')),full_page=True)
        page.goto(origin+f'/manager/fiches?site_id={ids["site"]}')
        fiche_link = page.locator(f'.mobile-directory-name[href$="/fiches/{fiche_id}?report_lang=fr"]')
        expect(fiche_link).to_be_visible()
        fiche_link.click()
        expect(page.locator('#fiche-report-lang')).to_have_value('fr')
        page.goto(origin+'/set-language/fr'); page.goto(origin+'/manager/cantieri?stato=tutti')
        expect(page.locator('.mobile-directory')).to_contain_text('Projet à configurer')
        page.locator('.mobile-directory-more').first.click()
        expect(page.get_by_role('button',name='Fermer',exact=True)).to_be_visible()
        page.keyboard.press('Escape'); fits()
        # Both themes, and the original no-JS fallback.
        page.locator('#theme-toggle').click(); fits()
        page.screenshot(path=str(out/'cantieri-fr-alt-theme.png'),full_page=True)
        fallback = browser.new_context(java_script_enabled=False, storage_state=context.storage_state(),
                                       viewport={'width':390,'height':844})
        fallback_page = fallback.new_page(); fallback_page.goto(origin+'/manager/cantieri?stato=tutti')
        expect(fallback_page.locator('.list-cards')).to_be_visible(); fallback.close()
        context.close()
        context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
        page = context.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*', lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        login('smoke-capo@example.com','/capo/dashboard')
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            for path in ['/capo/dashboard','/capo/rapportini','/capo/fiches', '/capo/cantiere/attrezzature',
                         '/capo/magazzino', '/capo/magazzino/richieste']:
                response=page.goto(origin+path); assert response.ok, (path,response.status)
                fits()
                expect(page.locator('main')).not_to_contain_text('Cantiere riservato altra squadra')
                if path == '/capo/magazzino':
                    expect(page.locator('.mobile-directory')).to_contain_text('12.0 pz')
                    page.locator('.mobile-directory-more').first.click()
                    expect(page.get_by_role('dialog')).to_contain_text('Soglia minima')
                    page.keyboard.press('Escape')
                page.screenshot(path=str(out/f'capo-{path.split("/")[-1]}-{width}.png'),full_page=True)
        assert not errors, errors
        print('COMPACT_SCREENSHOTS='+str(out))
        browser.close()
