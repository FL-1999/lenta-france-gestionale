import json
import pytest
from fastapi import HTTPException
from models import Fiche, FicheTranslation, RoleEnum
from services import fiche_translation as svc
from services.fiche_review import review_token
from test_operations import operations
from test_site_pours import setup, fiche as create_fiche
import main


def test_translation_is_explicit_owner_only_cached_and_invalidated(operations, monkeypatch):
    o=operations; setup(o, ('P5',)); assert create_fiche(o, 1).status_code == 303
    db=o['db']; f=db.query(Fiche).one(); f.notes='Controllare P5 a 13.50 m NGF.'; db.commit()
    monkeypatch.setenv('NOTES_OPENAI_API_KEY', 'test-key-not-real')
    monkeypatch.setenv('NOTES_AI_USER_IDS', str(o['manager'].id))
    calls=[]
    def generate(text, language, key):
        calls.append((text, language)); return 'Contrôler P5 à 13.50 m NGF.'
    monkeypatch.setattr(svc, 'generate', generate)
    url=f'/manager/fiches/{f.id}'
    body={'csrf':review_token(f,o['manager']), 'source_hash':svc.digest(f.notes), 'report_lang':'fr'}
    c=o['client']
    assert c.get(url).status_code==200 and calls==[]
    assert c.post(url+'/translate-notes', data=body).status_code==403  # manager cannot spend AI quota
    o['manager'].role=RoleEnum.admin; db.commit()
    assert c.post(url+'/translate-notes', data={**body,'csrf':'bad'}).status_code==409
    assert c.post(url+'/translate-notes', data=body, headers={'origin':'https://evil.example'}).status_code==403
    assert c.post(url+'/translate-notes', data=body, headers={'authorization':'Bearer other'}).status_code==403
    assert c.post(url+'/translate-notes', data=body).status_code==200
    assert c.post(url+'/translate-notes', data=body).status_code==200 and len(calls)==1
    assert db.query(FicheTranslation).count()==1
    db.refresh(f); assert f.notes=='Controllare P5 a 13.50 m NGF.' and f.review_status=='pending'
    assert 'Contrôler P5' in main._extract_technical_sheet(c.get(url).text)
    assert 'Controllare P5' in main._extract_technical_sheet(c.get(url+'?report_lang=it').text)
    monkeypatch.setattr(main, '_html_to_pdf', lambda html:html.encode())
    assert 'Contrôler P5' in c.get(url+'/pdf').content.decode()
    assert 'Contrôler P5' in c.get(f'/manager/cantieri/{f.site_id}/fiches-pdf/tutte').content.decode()
    f.notes='Nuovo testo P7 a 12.00 NGF.'; db.commit()
    assert 'Contrôler P5' not in main._extract_technical_sheet(c.get(url).text)
    assert c.post(url+'/translate-notes', data=body).status_code==409
    assert db.query(FicheTranslation).one().original=='Controllare P5 a 13.50 m NGF.'
    o['actor'][0]=o['capo']
    assert c.post(url+'/translate-notes', data=body).status_code==403


@pytest.mark.parametrize('invalid', [None, 'missing', 'extra', 'refusal', 'incomplete'])
def test_provider_keeps_numeric_codes_and_rejects_changed_measurements(monkeypatch, invalid):
    source='Verificare P5 a 13.50 m, 50-100 mm.\nAttendere conferma.'
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            payload=kwargs['json']; assert payload['store'] is False and 'tools' not in payload
            assert 'P5' not in payload['input'] and '13.50' not in payload['input']
            translated=payload['input'].replace('Verificare','Vérifier').replace('Attendere conferma.','Attendre la confirmation.')
            if invalid=='missing': translated=translated.replace('__REF_0__','')
            if invalid=='extra': translated+=' 45 m'
            result={'status':'incomplete' if invalid=='incomplete' else 'completed',
                    'output':[{'type':'message','content':[{'type':'refusal' if invalid=='refusal' else 'output_text',
                         'text':json.dumps({'text':translated})}]}]}
            return type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:result})()
    monkeypatch.setattr(svc.httpx,'Client',Client)
    if invalid:
        with pytest.raises(HTTPException) as error: svc.generate(source,'fr','not-real')
        assert error.value.status_code==503
    else:
        value=svc.generate(source,'fr','not-real')
        assert 'P5 a 13.50 m, 50-100 mm.' in value and '\n' in value
