import os
from datetime import date

import pypdfium2 as pdfium
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import Fiche, FicheStratigrafia, FicheTypeEnum, SitePour, SitePourPanel, User
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_angle_curve_stays_on_one_a4_and_preserves_details(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
        fiche = Fiche(site_id=ids['site'], created_by_id=manager.id, date=date(2026, 10, 26),
            fiche_type=FicheTypeEnum.produzione, numero_pannello=11, panel_name='P11 A/B',
            description='Collaudo angolo', tipologia_scavo='paratia', responsable_pdf='Federico Lenta',
            profondita_totale=11, larghezza_pannello=5.9, altezza_pannello=.42, metri_cubi_gettati=32.5,
            quota_partenza=13.8, quota_tn=14.5, quota_testa_getto=13.8, quota_ngf_fondo=2.8,
            type_beton='C30/37', terreno_teorico='0-1.3 m: Remblais\n1.3-9.3 m: Gravier\n9.3-11 m: Limon',
            courbe_beton_active=True, courbe_beton_volume_total=27.26, courbe_beton_hauteur_initiale=11,
            courbe_beton_realisee='[{"volume":0,"hauteur":11},{"volume":32.5,"hauteur":0}]')
        db.add(fiche); db.flush(); fid = fiche.id
        group = SitePour(site_id=ids['site'], kind='angle', label='P11 A/B', total_m3=32.5)
        db.add(group); db.flush()
        db.add_all([SitePourPanel(site_id=ids['site'], pour_id=group.id, number=n,
                    label=label, fiche_id=fid, snapshot='{}') for n,label in [(11,'P11a'),(12,'P11b')]])
        db.add_all([FicheStratigrafia(fiche_id=fid, da_profondita=0, a_profondita=1, materiale='riporto'),
                    FicheStratigrafia(fiche_id=fid, da_profondita=1, a_profondita=11, materiale='ghiaia')])
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        page = context.new_page()
        page.route('**/*', lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login'); page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password); page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        url = origin+f'/manager/fiches/{fid}'
        for lang in ('fr','it'):
            page.goto(url+f'?report_lang={lang}')
            expect(page.locator('[data-report-model]')).to_have_attribute('data-report-model','B2')
            expect(page.locator('.b-annex')).to_have_count(0)
            expect(page.locator('.b-group-details')).to_contain_text('P11a + P11b')
            page.emulate_media(media='print')
            bounds = page.evaluate('''() => {
                const r = s => document.querySelector(s).getBoundingClientRect();
                return {notes:r('.b-notes').bottom,curve:r('.b-curve').top,
                    bottom:r('.b-curve').bottom,signatures:r('.b-signatures').top,wall:r('.b-drawing').height};
            }''')
            assert bounds['notes'] < bounds['curve'] and bounds['bottom'] < bounds['signatures'], bounds
            assert bounds['wall'] == pytest.approx(225.4*96/25.4, abs=1)
            page.emulate_media(media='screen')
            response = page.request.get(url+f'/pdf?report_lang={lang}', timeout=60000)
            assert response.status == 200
            (out/f'fiche-angle-curve-{lang}.pdf').write_bytes(response.body())
            doc = pdfium.PdfDocument(response.body()); assert len(doc) == 1
            text = doc[0].get_textpage().get_text_range()
            for value in ('P11 A/B','P11a','P11b','32,50','5,90','13,80','2,80'):
                assert value in text, (lang,value)
            assert ('COURBE DE BÉTONNAGE' if lang=='fr' else 'CURVA DI GETTO') in text
            assert ('largeur nette totale' if lang=='fr' else 'larghezza netta complessiva') in ' '.join(text.split())
            assert doc[0].get_width() == pytest.approx(595.28,abs=1)
            assert doc[0].get_height() == pytest.approx(841.89,abs=1)
            doc[0].render(scale=1.5).to_pil().save(out/f'fiche-angle-curve-{lang}.png'); doc.close()
            dossier = page.request.get(origin+f'/manager/cantieri/{ids["site"]}/fiches-pdf/tutte?report_lang={lang}',timeout=60000)
            assert dossier.status == 200
            doc = pdfium.PdfDocument(dossier.body()); assert len(doc)==2; doc.close()  # cover + fiche
        # A short observation shares the first page; truly long notes are retained in full.
        for notes in ('Contrôle avant coulage.', 'Observation détaillée. '*40+'FIN DES OBSERVATIONS'):
            with Session(engine) as db:
                db.get(Fiche,fid).notes=notes;db.commit()
            page.goto(url)
            page.emulate_media(media='print')
            bounds=page.evaluate('''() => ({notes:document.querySelector('.b-notes').getBoundingClientRect().bottom,
                curve:document.querySelector('.b-curve').getBoundingClientRect().top})''')
            assert bounds['notes'] < bounds['curve'], bounds
            page.emulate_media(media='screen')
            response=page.request.get(url+'/pdf',timeout=60000)
            doc=pdfium.PdfDocument(response.body());assert len(doc)==(2 if len(notes)>100 else 1)
            text=' '.join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
            assert ('FIN DES OBSERVATIONS' if len(notes)>100 else notes) in text
            doc.close()
        context.close();browser.close()
