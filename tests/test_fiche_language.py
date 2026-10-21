import re
from html import unescape
import main
from models import Fiche, CloudAsset
from services.fiche_language import technical_text
from test_operations import operations
from test_site_pours import setup, fiche as create_fiche


def visible_text(html):
    return ' '.join(unescape(re.sub('<[^>]*>', ' ', html)).split())


def test_document_language_is_independent_of_ui_and_does_not_change_data(operations, monkeypatch):
    o = operations
    setup(o, ('P5',))
    assert create_fiche(o, 1).status_code == 303
    o['db'].expire_all()
    fiche = o['db'].query(Fiche).one()
    fiche.notes = 'Annotation originale <verificare> & "ok". Sabbia fine.'
    fiche.terreno_teorico = '0-10 m: Gravier'
    o['db'].commit()
    client = o['client']
    url = f'/manager/fiches/{fiche.id}'
    for ui_lang in ('it', 'fr'):
        client.cookies.set('lang', ui_lang)
        default = client.get(url).text
        assert 'value="fr" selected' in default
        assert 'id="technical-sheet-export" lang="fr"' in default
        for language, title, soil in (('it', 'RAPPORTO DI ESECUZIONE PANNELLO', 'Ghiaia'),
                                      ('fr', 'RAPPORT D’EXÉCUTION DE PANNEAU', 'Gravier')):
            response = client.get(url, params={'report_lang': language})
            assert response.status_code == 200
            report = main._extract_technical_sheet(response.text)
            assert f'id="technical-sheet-export" lang="{language}"' in report
            text = visible_text(report)
            assert title in text and soil in text and 'P5' in text
            assert fiche.notes in text
            assert '/pdf?report_lang='+language in response.text
            assert client.cookies.get('lang') == ui_lang
    o['db'].refresh(fiche)
    assert fiche.review_status == 'pending'
    assert fiche.terreno_teorico == '0-10 m: Gravier'
    assert fiche.stratigrafie[0].materiale == 'sabbia'
    captured = []
    def fake_pdf(html):
        captured.append(html)
        return html.encode()  # isolated renderer spy: verifies export/archival paths
    monkeypatch.setattr(main, '_html_to_pdf', fake_pdf)
    for language in ('fr', 'it'):
        for path in (url+'/pdf', f'/manager/cantieri/{fiche.site_id}/fiches-pdf/tutte'):
            response = client.get(path, params={'report_lang': language})
            assert response.status_code == 200
            assert '_'+language.upper()+'.pdf' in response.headers['content-disposition']
            doc = captured[-1]
            assert f"<html lang='{language}'>" in doc
            assert f'id="technical-sheet-export" lang="{language}"' in doc
            if 'fiches-pdf' in path:
                assert f'class="pdf-cover" lang="{language}"' in doc
                assert ('SCHEDE DI SCAVO' if language == 'it' else 'FICHES DE FORAGES') in visible_text(doc)
    o['db'].expire_all()
    assert o['db'].query(Fiche).count() == 1
    assert o['db'].query(CloudAsset).filter(CloudAsset.kind.in_(['fiche_pdf', 'dossier_pdf'])).count() == 4
    for path in (url, url+'/pdf', f'/manager/cantieri/{fiche.site_id}/fiches-pdf/tutte'):
        assert client.get(path, params={'report_lang': 'de'}).status_code == 422
        o['actor'][0] = o['capo']
        assert client.get(path, params={'report_lang': 'it'}).status_code == 403
        o['actor'][0] = o['manager']


def test_list_and_site_exports_keep_language_and_site_filter(operations):
    o = operations
    setup(o, ('P5',))
    assert create_fiche(o, 1).status_code == 303
    for path in (f'/manager/fiches?site_id={o["site"].id}&report_lang=it',
                 f'/manager/cantieri/{o["site"].id}?report_lang=it'):
        response = o['client'].get(path)
        assert response.status_code == 200
        dom = response.text
        assert 'value="it" selected' in dom
        links = [href for href in re.findall(r'href="([^"]+)"', dom) if 'fiches-pdf' in href or '/pdf?report_lang' in href]
        assert links
        assert all('report_lang=it' in link for link in links)
        if 'site_id=' in path:
            assert f'name="site_id" value="{o["site"].id}"' in dom


def test_technical_vocabulary_translates_whole_terms_without_changing_numbers():
    assert technical_text('Gros cailloux · Grossier · 50-100 mm · Sans fines', 'it') == (
        'Ciottoli grossi · Grossolano · 50-100 mm · Senza frazione fine')
    assert technical_text('ciottoli grossi · molto fine', 'fr') == 'Gros cailloux · Très fin'
    assert technical_text('Confine P5 13.50 NGF', 'fr') == 'Confine P5 13.50 NGF'
    assert technical_text('finition du panneau', 'it') == 'finition du panneau'
