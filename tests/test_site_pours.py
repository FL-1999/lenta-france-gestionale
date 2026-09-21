import json
from datetime import date
from decimal import Decimal
import pytest
from models import SitePlan, SiteCoupe, SiteCoupeAssignment, SiteProgressGridName, SitePour, SitePourPanel, Fiche, RoleEnum
from services.site_pours import allocation
from utils.production_stats import compute_site_production
from test_operations import operations


def setup(o, labels=('P7A','P7B'), widths=(5,3)):
    db=o['db'];o['actor'][0]=o['manager'];site=o['site'];site.numero_totale_paratie=2
    c=SiteCoupe(site_id=site.id,nome='CUP 1',profondita_teorica=10,spessore=.5,quota_tn=20,quota_testa=20,quota_fondo_teorica=10)
    db.add(c);db.flush()
    panels=[]
    for n,(label,width) in enumerate(zip(labels,widths),1):
        panels.append({'key':str(n),'element':n,'label':label,'width_m':width,'points':[[0,n*30],[width*10,n*30],[width*10,n*30+5],[0,n*30+5]],'reviewed':True})
        db.add(SiteCoupeAssignment(site_id=site.id,coupe_id=c.id,tipologia_scavo='paratia',numero_elemento=n))
        db.add(SiteProgressGridName(site_id=site.id,tipologia_scavo='paratia',numero_elemento=n,nome_personalizzato=label))
    layout=json.dumps({'width':100,'height':100,'panels':panels,'scale_ppm':10})
    db.add(SitePlan(site_id=site.id,filename='test.pdf',pdf_data=b'test',preview_data=b'test',draft=layout,approved=layout,approved_at=date.today()))
    db.commit()
    return f'/manager/cantieri/{site.id}'


def fiche(o, n, volume=None):
    data={'cantiere_id':o['site'].id,'numero_pannello':n,'data_scavo':'2026-09-21','operatore':'Squadra',
          'tipologia_scavo':'paratia','profondita_totale':'10','strato_da':['0'],'strato_a':['10'],'strato_materiale':['sabbia']}
    if volume is not None: data.update(metri_cubi_gettati=str(volume),data_getto='2026-09-21')
    return o['client'].post('/manager/fiches/nuova',data=data,follow_redirects=False)


def test_angle_single_fiche_two_panels_no_duplicate_volume_and_delete(operations):
    o=operations;base=setup(o);c=o['client'];db=o['db']
    created=c.post(base+'/getti',json={'numbers':[1,2],'kind':'angle','confirm_net':True})
    assert created.status_code==200,created.text
    g=created.json();assert g['label']=='P7 A/B'
    assert '8.0' in c.get(f'/manager/fiches/nuova?cantiere_id={o["site"].id}&numero_pannello=1').text
    response=fiche(o,1,42);assert response.status_code==303,response.text
    db.expire_all();f=db.query(Fiche).one();assert f.panel_name=='P7 A/B' and f.larghezza_pannello==8
    assert len(f.pour_panels)==2
    stats=compute_site_production(o['site'],[f]);assert stats['paratie']['count']==2
    assert stats['totale']['volume_cls_reale']==42 and stats['totale']['volume_cls_teorico']==40
    es=c.get(base+'/pianta/data').json()['elements'];assert es[0]['fiche_id']==es[1]['fiche_id']==f.id
    assert fiche(o,2,10).status_code==400
    assert c.get(base).status_code==200
    detail=c.get(f'/manager/fiches/{f.id}');assert detail.status_code==200,detail.text
    assert 'Fiche unica' in detail.text and 'P7 A/B' in detail.text
    g=c.get(base+'/getti').json()[0]
    assert c.delete(base+f'/getti/{g["id"]}?revision={g["revision"]}&confirm=true').status_code==409
    assert db.query(Fiche).count()==1
    assert c.delete(base+f'/getti/{g["id"]}?revision={g["revision"]}&confirm=true&delete_fiche=true').status_code==403
    o['manager'].role=RoleEnum.admin;db.commit()
    assert c.delete(base+f'/getti/{g["id"]}?revision={g["revision"]}&confirm=true&delete_fiche=true').status_code==200
    db.expire_all();assert db.query(Fiche).count()==0 and db.query(SitePourPanel).count()==0
    assert c.get(base+'/pianta/data').json()['elements'][1]['fiche_id'] is None


def test_joint_exact_allocation_revision_manual_and_restore(operations):
    o=operations;base=setup(o,('P1','P2'));c=o['client'];db=o['db']
    g=c.post(base+'/getti',json={'numbers':[1,2],'kind':'joint'}).json()
    data={'revision':g['revision'],'total_m3':40,'cast_date':'2026-09-21','confirm':True}
    assert c.put(base+f'/getti/{g["id"]}',json=data).status_code==400
    assert fiche(o,1,8).status_code==303
    assert fiche(o,2,9).status_code==303
    db.expire_all();g=c.get(base+'/getti').json()[0];data['revision']=g['revision']
    r=c.put(base+f'/getti/{g["id"]}',json=data);assert r.status_code==200,r.text
    assert [m['allocated_m3'] for m in r.json()['members']]==[25,15]
    assert c.put(base+f'/getti/{g["id"]}',json=data).status_code==409
    data['revision']=r.json()['revision'];data['manual']=[30,12]
    assert c.put(base+f'/getti/{g["id"]}',json=data).status_code==400
    db.expire_all();assert sum(f.metri_cubi_gettati for f in db.query(Fiche))==40
    data['manual']=[24,16];r=c.put(base+f'/getti/{g["id"]}',json=data);assert r.status_code==200
    db.expire_all();assert [f.metri_cubi_gettati for f in db.query(Fiche).order_by(Fiche.numero_pannello)]==[24,16]
    g=r.json();assert c.delete(base+f'/getti/{g["id"]}?revision={g["revision"]}&confirm=true').status_code==200
    db.expire_all();assert [f.metri_cubi_gettati for f in db.query(Fiche).order_by(Fiche.numero_pannello)]==[8,9]


def test_status_permissions_and_preserved_records(operations):
    o=operations;base=setup(o);c=o['client'];db=o['db']
    assert c.post(base+'/stato',data={'stato':'chiuso'}).status_code==400
    assert c.post(base+'/stato',data={'stato':'chiuso','conferma':'true'},follow_redirects=False).status_code==303
    db.expire_all();assert o['site'].status.value=='chiuso' and db.query(SitePlan).count()==1
    assert o['site'].name not in c.get('/manager/cantieri').text
    assert o['site'].name in c.get('/manager/cantieri?stato=terminati').text
    assert c.post(base+'/stato',data={'stato':'aperto','conferma':'true'},follow_redirects=False).status_code==303
    o['actor'][0]=o['capo']
    assert c.post(base+'/getti',json={'numbers':[1,2],'kind':'angle','confirm_net':True}).status_code==403
    assert c.post(base+'/stato',data={'stato':'chiuso','conferma':'true'}).status_code==403
    o['actor'][0]=o['outsider'];assert c.get(base+'/getti').status_code in (403,404)


def test_group_validation_is_atomic(operations):
    o=operations;base=setup(o);c=o['client'];db=o['db']
    for body in [{'numbers':[1,1],'kind':'joint'}, {'numbers':[1,999],'kind':'joint'}, {'numbers':[1,2],'kind':'angle'}]:
        assert c.post(base+'/getti',json=body).status_code==400
        assert db.query(SitePour).count()==0
    assert c.post(base+'/getti',json={'numbers':[1,2],'kind':'angle','confirm_net':True}).status_code==200
    assert c.post(base+'/getti',json={'numbers':[1,2],'kind':'joint'}).status_code==409


@pytest.mark.parametrize('total,weights,expected',[(40,[5,3],[25,15]),(20,[5,5],[10,10]),(1,[1,1,1],[.334,.333,.333]),(40,[5*10*.5,3*20*.5],[18.182,21.818])])
def test_allocations(total,weights,expected):
    parts=allocation(total,weights);assert parts==expected
    assert sum(Decimal(str(p)) for p in parts)==Decimal(str(total))
