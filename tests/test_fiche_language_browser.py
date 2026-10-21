import os
import sys
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from models import Fiche, FicheStratigrafia, FicheTypeEnum, Site, User
from main import _load_style_css, _wrap_sheet_document
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_languages_preview_print_pdf_dossier_and_phone(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    out = Path(artifacts)
    with Session(engine) as db:
        manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
        db.get(Site, ids['site']).code = 'TEST-LANG'
        fiche = Fiche(site_id=ids['site'], created_by_id=manager.id, date=date(2026, 10, 21),
                      fiche_type=FicheTypeEnum.produzione, numero_pannello=5, panel_name='P5',
                      description='Collaudo lingua', tipologia_scavo='paratia',
                      profondita_totale=10.7, larghezza_pannello=6.3, altezza_pannello=.42,
                      quota_partenza=13.5, quota_tn=14.5, quota_ngf_fondo=2.8,
                      quota_testa_getto=13.5, metri_cubi_gettati=38, type_beton='C30/37',
                      notes='Nota originale: controllare prima del getto.',
                      terreno_teorico='0-1 m: Remblais\n1-9 m: Gravier\n9-10.7 m: Limon')
        db.add(fiche); db.flush(); fid = fiche.id
        db.add_all([FicheStratigrafia(fiche_id=fid, da_profondita=0, a_profondita=1, materiale='riporto'),
                    FicheStratigrafia(fiche_id=fid, da_profondita=1, a_profondita=10.7, materiale='ciottoli grossi · senza frazione fine')])
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login'); page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password); page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        context.add_cookies([{'name': 'lang', 'value': 'fr', 'url': origin}])
        url = origin+f'/manager/fiches/{fid}'
        page.goto(url)
        expect(page.locator('#fiche-report-lang')).to_have_value('fr')
        for lang, heading, soil in [('it', 'RAPPORTO DI ESECUZIONE PANNELLO', 'ciottoli grossi'),
                                     ('fr', 'RAPPORT D’EXÉCUTION DE PANNEAU', 'Gros cailloux')]:
            page.locator('#fiche-report-lang').select_option(lang)
            page.wait_for_url(f'**report_lang={lang}#fiche-report-options')
            expect(page.locator('#technical-sheet-export')).to_have_attribute('lang', lang)
            expect(page.locator('.technical-sheet__header-title')).to_have_text(heading)
            expect(page.locator('#technical-sheet-export')).to_contain_text(soil)
            # Native print receives the selected document language.
            context.add_init_script('window.print = () => {}; window.close = () => {};')
            with page.expect_popup() as pending:
                page.locator('[data-print-technical-sheet]').click()
            printed = pending.value; printed.wait_for_load_state()
            expect(printed.locator('html')).to_have_attribute('lang', lang)
            expect(printed.locator('.technical-sheet__header-title')).to_have_text(heading)
            printed.emulate_media(media='print')
            printed.evaluate('document.fonts.ready')
            bounds = printed.evaluate('''() => ({last:document.querySelector('.technical-soil-block:last-child').getBoundingClientRect().bottom,
                footer:document.querySelector('.technical-visa-block').getBoundingClientRect().top})''')
            printed.screenshot(path=str(out/f'print-{lang}.png'), full_page=True)
            assert bounds['last'] <= bounds['footer'], bounds
            printed.close()
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 844 if width < 1000 else 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.locator('#fiche-report-options').scroll_into_view_if_needed()
                assert page.locator('#fiche-report-lang').bounding_box()['height'] >= 44
                if width == 390:
                    page.screenshot(path=str(out/f'fiche-language-{lang}-iphone.png'))
            response = page.request.get(url+f'/pdf?report_lang={lang}', timeout=60000)
            assert response.status == 200
            (out/f'fiche-{lang}.pdf').write_bytes(response.body())
            doc = pdfium.PdfDocument(response.body()); assert len(doc) == 1
            text = doc[0].get_textpage().get_text_range()
            assert heading.upper() in text.upper() and soil in text
            for value in ('P5', '13,50', '12,50', '2,80', '10.70', 'C30/37', 'Nota originale:'):
                assert value in text, (lang, value)
            assert doc[0].get_width() == pytest.approx(595.28, abs=1)
            assert doc[0].get_height() == pytest.approx(841.89, abs=1)
            doc[0].render(scale=1.5).to_pil().save(out/f'fiche-{lang}.png'); doc.close()
            if sys.platform != 'win32':
                from weasyprint import HTML
                article = page.locator('#technical-sheet-export').evaluate('el=>el.outerHTML')
                fallback = HTML(string=_wrap_sheet_document(article, _load_style_css(), lang), base_url=origin).write_pdf()
                (out/f'fiche-{lang}-weasyprint.pdf').write_bytes(fallback)
                doc = pdfium.PdfDocument(fallback); assert len(doc) == 1
                assert soil in doc[0].get_textpage().get_text_range()
                doc.close()
            response = page.request.get(origin+f'/manager/cantieri/{ids["site"]}/fiches-pdf/tutte?report_lang={lang}', timeout=60000)
            assert response.status == 200
            (out/f'dossier-{lang}.pdf').write_bytes(response.body())
            doc = pdfium.PdfDocument(response.body()); assert len(doc) == 2
            assert ('SCHEDE DI SCAVO' if lang == 'it' else 'FICHES DE FORAGES') in doc[0].get_textpage().get_text_range()
            doc[0].render(scale=1).to_pil().save(out/f'dossier-{lang}.png'); doc.close()
        # Annexes, pile labels and concrete curve also follow the language.
        with Session(engine) as db:
            fiche = db.get(Fiche, fid)
            fiche.tipologia_scavo = 'palo'; fiche.diametro_palo = 1.2
            fiche.terreno_teorico = '\n'.join(f'{i}-{i+1} m: Gravier {i+1}' for i in range(10))
            fiche.notes = 'Nota originale. '*30 + 'FINE ANNOTAZIONI'
            fiche.courbe_beton_active = True
            fiche.courbe_beton_volume_total = 20; fiche.courbe_beton_hauteur_initiale = 10.7
            db.commit()
        response = page.request.get(url+'/pdf?report_lang=it', timeout=60000)
        assert response.status == 200
        (out/'fiche-palo-it.pdf').write_bytes(response.body())
        doc = pdfium.PdfDocument(response.body())
        assert len(doc) == 3  # main fiche, concrete curve, complete soil/notes annex
        assert 'CURVA DI GETTO' not in doc[0].get_textpage().get_text_range()
        assert 'CURVA DI GETTO' in doc[1].get_textpage().get_text_range()
        text = '\n'.join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        for label in ('RAPPORTO DI ESECUZIONE PALO', 'CURVA DI GETTO', 'Allegato', 'Ghiaia 10', 'FINE ANNOTAZIONI'):
            assert label in text
        for i in range(len(doc)):
            assert doc[i].get_width() == pytest.approx(595.28, abs=1)
            assert doc[i].get_height() == pytest.approx(841.89, abs=1)
            doc[i].render(scale=1).to_pil().save(out/f'fiche-palo-it-{i+1}.png')
        doc.close()
        page.goto(origin+f'/manager/fiches?site_id={ids["site"]}&report_lang=it')
        expect(page.locator('#fiche-report-lang')).to_have_value('it')
        page.locator('#fiche-report-lang').select_option('fr')
        page.wait_for_url('**report_lang=fr#fiche-report-options')
        assert 'site_id='+str(ids['site']) in page.url
        assert not errors, errors
        browser.close()
