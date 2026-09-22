import copy
import json
from datetime import date
import pytest
from models import SitePlan, SitePour, Fiche, SiteCoupe, SiteCoupeAssignment
from services.plan_corners import suggest_corners, overlap_area, validate_corners
from test_operations import operations
from test_site_plans import vector_pdf
from test_site_pours import fiche


def layout():
    # Two net 2.50 m arms in an L; shared boundary, no overlap.
    panels = [
        {'key':'a','label':'P3a','points':[[100,150],[200,150],[200,170],[100,170]],'width_m':2.5},
        {'key':'b','label':'P3b','points':[[100,50],[100,150],[80,150],[80,50]],'width_m':2.5},
    ]
    # Horizontal arm touches the side of the vertical arm along x=100, y=130..150.
    panels[0]['points']=[[100,130],[200,130],[200,150],[100,150]]
    for p in panels:
        p.update(element=None,reviewed=True,reference_points=copy.deepcopy(p['points']),corner_group='a',corner_net_confirmed=True)
    return {'width':300,'height':300,'scale_ppm':40,'panels':panels}


def setup(o):
    o['actor'][0]=o['manager'];db=o['db']
    data=layout()
    row=SitePlan(site_id=o['site'].id,filename='corner.pdf',pdf_data=vector_pdf(),preview_data=b'test',draft=json.dumps(data))
    db.add(row);db.commit()
    url=f'/manager/cantieri/{o["site"].id}/pianta'
    body={'revision':1,'panels':copy.deepcopy(data['panels']),'scale_ppm':40,'confirm':True}
    return url,row,body


def test_unique_adjacent_ab_only_and_no_guessed_net_confirmation():
    data=layout();panels=data['panels']
    for p in panels:p.pop('corner_group');p.pop('corner_net_confirmed')
    suggest_corners(panels)
    assert panels[0]['corner_group']==panels[1]['corner_group']
    assert not panels[0]['corner_net_confirmed']
    repeated=copy.deepcopy(panels)+[copy.deepcopy(panels[0])]
    for p in repeated:p.pop('corner_group',None)
    suggest_corners(repeated)
    assert not any(p.get('corner_group') for p in repeated)
    far=copy.deepcopy(panels)
    for p in far:p.pop('corner_group',None)
    far[1]['points']=[[x+200,y] for x,y in far[1]['points']]
    suggest_corners(far)
    assert not any(p.get('corner_group') for p in far)


@pytest.mark.parametrize('problem',['gap','overlap','net','wrong_label'])
def test_invalid_corner_rejects_approval_but_preserves_draft(operations,problem):
    o=operations;url,row,body=setup(o)
    a,b=body['panels']
    if problem=='gap':a['points']=[[x+2,y] for x,y in a['points']]
    if problem=='overlap':a['points']=[[x-2,y] for x,y in a['points']]
    if problem=='net':a['corner_net_confirmed']=False
    if problem=='wrong_label':a['label']='P4a'
    for p in body['panels']:p['extent_confirmed']=True
    response=o['client'].put(url+f'/{row.id}/convalida',json=body)
    assert response.status_code==400,response.text
    o['db'].expire_all();assert row.approved is None and row.revision==1
    assert o['db'].query(SitePour).count()==0


def test_corner_plan_then_coupe_then_single_fiche_and_safe_split(operations):
    o=operations;db=o['db'];c=o['client'];url,row,body=setup(o)
    response=c.put(url+f'/{row.id}/convalida',json=body)
    assert response.status_code==200,response.text
    data=c.get(url+'/data').json()['plan']
    panels=data['layout']['panels'];numbers=[p['element'] for p in panels]
    assert len(set(numbers))==2 and db.query(Fiche).count()==0 and db.query(SitePour).count()==0
    # Not allowed to create an individual fiche for a pending corner.
    assert fiche(o,numbers[0]).status_code==400
    config={'coupe_nome':'Coupe angle','coupe_quota_tn':'10','coupe_profondita_teorica':'10',
            'coupe_spessore':'0.5','coupe_paratie':','.join(map(str,numbers))}
    response=c.post(f'/manager/cantieri/{o["site"].id}/configurazione-progetto',data=config,follow_redirects=False)
    assert response.status_code==303,response.text
    db.expire_all();group=db.query(SitePour).one()
    assert group.label=='P3 A/B'
    assert fiche(o,numbers[0],25).status_code==303
    db.expire_all();f=db.query(Fiche).one()
    assert f.panel_name=='P3 A/B' and f.larghezza_pannello==5
    assert {m.fiche_id for m in group.members}=={f.id}
    split={'revision':data['revision'],'panels':copy.deepcopy(panels),'scale_ppm':40,'confirm':True}
    for p in split['panels']:p['corner_group']=None
    response=c.put(url+f'/{row.id}/convalida',json=split)
    assert response.status_code==409,response.text
    db.expire_all();assert db.query(Fiche).count()==1 and row.revision==data['revision']
    assert all(p['corner_group'] for p in json.loads(row.approved)['panels'])


def test_split_without_fiche_preserves_panels_and_coupe(operations):
    o=operations;db=o['db'];c=o['client'];url,row,body=setup(o)
    assert c.put(url+f'/{row.id}/convalida',json=body).status_code==200
    data=c.get(url+'/data').json()['plan'];panels=data['layout']['panels'];ids=[p['element'] for p in panels]
    cup=SiteCoupe(site_id=o['site'].id,nome='Coupe',profondita_teorica=10,spessore=.5);db.add(cup);db.flush()
    for n in ids:db.add(SiteCoupeAssignment(site_id=o['site'].id,coupe_id=cup.id,tipologia_scavo='paratia',numero_elemento=n))
    db.flush()
    from services.plan_corners import reconcile_groups
    reconcile_groups(db,o['site'],data['layout']);db.commit()
    assert db.query(SitePour).count()==1
    for p in panels:p['corner_group']=None;p['corner_net_confirmed']=False
    response=c.put(url+f'/{row.id}/convalida',json={'revision':data['revision'],'panels':panels,'scale_ppm':40,'confirm':True})
    assert response.status_code==200,response.text
    assert db.query(SitePour).count()==0 and db.query(SiteCoupeAssignment).count()==2
    assert [p['element'] for p in c.get(url+'/data').json()['plan']['layout']['panels']]==ids


def test_overlap_math_accepts_shared_boundary_only():
    a,b=layout()['panels']
    assert overlap_area(a['points'],b['points'])==0
    shifted=[[x-5,y] for x,y in a['points']]
    assert overlap_area(shifted,b['points'])==pytest.approx(100)


def test_pending_corner_tracks_coupe_and_production_cannot_be_detached(operations):
    from services.plan_corners import reconcile_groups
    from fastapi import HTTPException
    o=operations;db=o['db'];c=o['client'];url,row,body=setup(o)
    assert c.put(url+f'/{row.id}/convalida',json=body).status_code==200
    data=json.loads(row.approved)
    cup=SiteCoupe(site_id=o['site'].id,nome='Coupe',profondita_teorica=10,spessore=.5)
    db.add(cup);db.flush()
    for p in data['panels']:
        db.add(SiteCoupeAssignment(site_id=o['site'].id,coupe_id=cup.id,tipologia_scavo='paratia',numero_elemento=p['element']))
    db.flush();reconcile_groups(db,o['site'],data);db.commit()
    cup.profondita_teorica=12
    db.flush();reconcile_groups(db,o['site'],data);db.commit()
    group=db.query(SitePour).one()
    assert all(json.loads(m.snapshot)['depth']==12 for m in group.members)
    assert fiche(o,data['panels'][0]['element'],25).status_code==303
    db.expire_all()
    assignment=db.query(SiteCoupeAssignment).first()
    db.delete(assignment);db.flush()
    with pytest.raises(HTTPException) as error:
        reconcile_groups(db,o['site'],data)
    assert error.value.status_code==409
    db.rollback()
    assert db.query(SiteCoupeAssignment).count()==2 and db.query(Fiche).count()==1
