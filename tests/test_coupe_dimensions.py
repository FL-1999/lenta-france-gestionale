import json
import pytest
from models import Fiche, SiteCoupe, SiteCoupeAssignment
from main import _calculate_fiche_volume_teorico
from test_operations import operations
from test_site_pours import setup, fiche


def test_different_panel_widths_share_coupe_thickness_and_volume(operations):
    o=operations;setup(o,('P1','P2'),(6.4,3.5));db=o['db']
    coupe=db.query(SiteCoupe).one();coupe.larghezza=99;db.commit()
    response=fiche(o,1,32)
    import re
    assert response.status_code==303, re.findall(r'<div[^>]*role="alert"[^>]*>(.*?)</div>',response.text,re.S)
    assert fiche(o,2,17.5).status_code==303
    db.expire_all();items=db.query(Fiche).order_by(Fiche.numero_pannello).all()
    assert [f.larghezza_pannello for f in items]==[6.4,3.5]
    assert {f.coupe_id for f in items}=={coupe.id}
    assert [f.altezza_pannello for f in items]==[.5,.5]
    assert [_calculate_fiche_volume_teorico(f) for f in items]==pytest.approx([32,17.5])


@pytest.mark.parametrize('field,value',[('larghezza_pannello','5'),('altezza_pannello','0.8')])
def test_new_fiche_cannot_override_plan_width_or_coupe_thickness(operations,field,value):
    o=operations;setup(o,('P1','P2'),(6.4,3.5))
    response=o['client'].post('/manager/fiches/nuova',data={
        'cantiere_id':o['site'].id,'numero_pannello':1,'data_scavo':'2026-09-21',
        'data_getto':'2026-09-21','metri_cubi_gettati':'32','operatore':'Squadra','tipologia_scavo':'paratia','profondita_totale':'10',
        'strato_da':['0'],'strato_a':['10'],'strato_materiale':['sabbia'],field:value},follow_redirects=False)
    assert response.status_code==400 and o['db'].query(Fiche).count()==0


def test_distinct_coupe_types_persist_and_mixed_submission_rolls_back(operations):
    o=operations;o['actor'][0]=o['manager'];c=o['client'];db=o['db']
    url=f'/manager/cantieri/{o["site"].id}/configurazione-progetto'
    data={'coupe_nome':['Paroi A','Pieux A'],'coupe_tipologia_scavo':['paratia','palo'],
          'coupe_paratie':['1,2',''],'coupe_pali':['','1,2'],'coupe_spessore':['.5',''],
          'coupe_diametro':['','.8'],'coupe_profondita_teorica':['10','15']}
    response=c.post(url,data=data,follow_redirects=False)
    assert response.status_code==303,response.text
    db.expire_all();coups=db.query(SiteCoupe).order_by(SiteCoupe.id).all()
    assert [v.work_kind for v in coups]==['paratia','palo']
    assert coups[0].diametro is None and coups[0].larghezza is None
    assert coups[1].spessore is None and coups[1].diametro==.8
    data['coupe_id']=[str(v.id) for v in coups];data['coupe_pali'][0]='3'
    response=c.post(url,data=data)
    assert response.status_code==400 and 'Separa paratie e pali' in response.text
    db.expire_all();assert db.query(SiteCoupeAssignment).count()==4
    assert db.query(SiteCoupe).count()==2


def test_legacy_mixed_coupe_stays_visible_without_rewriting_fiches(operations):
    o=operations;base=setup(o,('P1','P2'),(6.4,3.5));db=o['db'];cup=db.query(SiteCoupe).one()
    db.add(SiteCoupeAssignment(site_id=o['site'].id,coupe_id=cup.id,tipologia_scavo='palo',numero_elemento=1));db.commit();db.expire_all()
    assert cup.work_kind=='mixed'
    assert o['client'].get(base+'/configurazione-progetto').status_code==200
