import json
from datetime import date

import pytest
from models import Fiche, SiteCoupe, SiteCoupeAssignment, SiteProgressGridName
from main import _calculate_fiche_volume_teorico
from test_operations import operations
from test_site_plans import setup, payload


def configure(o, number=1):
    return o['client'].post(f'/manager/cantieri/{o["site"].id}/configurazione-progetto', data={
        'coupe_id':['',''], 'coupe_nome':['Coupe 1',''],
        'coupe_paratie':[str(number),''], 'coupe_pali':['',''],
        'coupe_quota_reference_label':['NGM','NGF'],
        'coupe_quota_tn':['10.5',''], 'coupe_quota_testa':['10.5',''],
        'coupe_quota_fondo_teorica':['-1.5',''], 'coupe_base_paroi_mecanique':['-1.38',''],
        'coupe_scavo_da_tn':['1','1'], 'coupe_quota_testa_getto_prevista':['10.5',''],
        'coupe_spessore':['0.42',''], 'coupe_larghezza':['5.2',''],
        'coupe_type_coulage':['Gravitaire','Gravitaire'],
        'coupe_terreno_teorico':['0-12 m: Sable',''],
    }, follow_redirects=False)


def test_confirm_coupe_create_fiche_and_historical_snapshot(operations):
    o=operations;c,url,pid,plan=setup(o)
    body=payload(plan);body['panels'][0].update(element=None,width_m=5.2)
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    assert configure(o).status_code==303
    db=o['db'];db.expire_all()
    coupe=db.query(SiteCoupe).one()
    assert coupe.profondita_teorica==12 and coupe.quota_reference_label=='NGM'
    assert db.query(SiteCoupeAssignment).one().numero_elemento==1
    link=c.get(url+'/data').json()['elements'][0]['create_url']
    form=c.get(link)
    assert form.status_code==200 and 'P7a' in form.text
    assert 'value="5.2"' in form.text
    data={'cantiere_id':o['site'].id,'numero_pannello':1,'data_scavo':'2026-09-17',
          'data_getto':'2026-09-17','metri_cubi_gettati':'27.5','operatore':'Squadra prova',
          'tipologia_scavo':'paratia','profondita_totale':'12',
          'strato_da':['0'],'strato_a':['12'],'strato_materiale':['sabbia']}
    response=c.post('/manager/fiches/nuova',data=data,follow_redirects=False)
    assert response.status_code==303,response.text
    db.expire_all();fiche=db.query(Fiche).one()
    assert fiche.panel_name=='P7a' and fiche.coupe_id==coupe.id
    assert fiche.larghezza_pannello==5.2 and fiche.altezza_pannello==.42
    assert fiche.quota_ngf_fondo==-1.5 and fiche.quota_partenza==10.5
    assert _calculate_fiche_volume_teorico(fiche)==pytest.approx(26.208)
    assert fiche.report_coupe.base_paroi_mecanique==-1.38
    coupe.base_paroi_mecanique=99;coupe.quota_reference_label='CHANGED';db.commit()
    detail=c.get(f'/manager/fiches/{fiche.id}')
    assert detail.status_code==200 and 'NGM' in detail.text and '-1,38' in detail.text
    assert 'CHANGED' not in detail.text
    assert c.get(link,follow_redirects=False).status_code==303
    duplicate=c.post('/manager/fiches/nuova',data=data,follow_redirects=False)
    assert duplicate.status_code==400 and db.query(Fiche).count()==1
    live=c.get(url+'/data').json()['elements'][0]
    assert live['status']=='cast' and live['concrete_m3']==27.5 and live['create_url'] is None


def test_duplicate_names_have_distinct_ids_and_reapproval_keeps_identity(operations):
    o=operations;c,url,pid,plan=setup(o);body=payload(plan)
    panel=body['panels'][0];panel['element']=None
    body['panels'].append({**panel,'key':'second-occurrence'})
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    current=c.get(url+'/data').json()['plan']
    ids=[p['element'] for p in current['layout']['panels']]
    assert len(set(ids))==2
    body.update(revision=current['revision'],panels=current['layout']['panels'])
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    assert operations['db'].query(SiteProgressGridName).count()==2
    body['revision']+=1;body['panels'][0]['element']=None
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==400


def test_coupe_rejects_overlapping_assignments_atomically(operations):
    o=operations;c,url,pid,plan=setup(o)
    assert configure(o).status_code==303
    original=o['db'].query(SiteCoupeAssignment).one().coupe_id
    response=c.post(f'/manager/cantieri/{o["site"].id}/configurazione-progetto',data={
        'coupe_id':[str(original),''], 'coupe_nome':['Existing','Other'],
        'coupe_paratie':['1','1'], 'coupe_quota_reference_label':['NGF','NGF']})
    assert response.status_code==400
    o['db'].expire_all()
    assert o['db'].query(SiteCoupeAssignment).one().coupe_id==original
