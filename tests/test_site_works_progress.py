import json
from datetime import datetime

from models import SiteStrutLevel, SiteCoupe, SiteWorksMap
from services.site_works import counts, guide_configuration
from test_operations import operations
from test_site_works import setup, layout, strut


def test_guides_follow_approved_metres_until_manually_overridden(operations):
    o=operations;c,url,body=setup(o)
    assert c.put(url+'/data',json=body).status_code==200
    result=c.get(url+'/data').json()
    assert result['configuration']['wall_length_m']==32
    assert result['summary']['cordoli']['total']==32
    result=c.patch(url+'/progress',json={'cordoli_done_m':8}).json()
    assert result['summary']['cordoli']['percent']==25
    result=c.patch(url+'/progress',json={'installazione_cantiere_pct':30}).json()
    assert result['configuration']['guide_auto']
    assert result['summary']['cordoli']['done']==8
    assert c.patch(url+'/progress',json={'cordoli_total_m':40}).status_code==200
    plan=o['site'].plans[0];new=layout();new['panels'][0]['width_m']=20
    plan.approved=json.dumps(new);plan.approved_revision=2;o['db'].commit()
    result=c.get(url+'/data').json()
    assert result['configuration']['wall_length_m']==36
    assert result['configuration']['guide_total_m']==40
    assert not result['configuration']['guide_auto']
    assert result['reference']['layout']==layout()
    result=c.patch(url+'/progress',json={'cordoli_total_m':None}).json()
    assert result['configuration']['guide_total_m']==36
    assert result['summary']['installazione_cantiere']['done']==30
    assert result['works']['levels'][0]['struts'][0]['status']=='installed'


def test_metres_count_both_corner_arms_and_never_partial_or_removed_plan(operations):
    o=operations;c,url,_=setup(o);plan=o['site'].plans[0]
    p=layout()
    for panel in p['panels']:panel.update(corner_group='corner',element=1)
    plan.approved=json.dumps(p);o['db'].commit()
    assert guide_configuration(o['site'])['wall_length_m']==32
    p['panels'][0]['width_m']=None;plan.approved=json.dumps(p);o['db'].commit()
    assert c.get(url+'/data').json()['configuration']['wall_length_m'] is None
    plan.approved=json.dumps(layout());plan.removed_at=datetime.utcnow();o['db'].commit()
    assert c.get(url+'/data').json()['configuration']['wall_length_m'] is None


def test_configured_levels_populate_empty_map_and_mapped_counts_supersede_manual(operations):
    o=operations;c,url,body=setup(o)
    body['works']={'levels':[],'wells':[],'rabotage':[]}
    assert c.put(url+'/data',json=body).status_code==200
    o['db'].add(SiteStrutLevel(site_id=o['site'].id,level_index=1,level_quota='-3.5 m',total_struts_level=6,done_struts_level=2))
    o['db'].add(SiteCoupe(site_id=o['site'].id,nome='Coupe 1',drawing_info={'reviewed':True,'struts':[12]}))
    o['db'].commit();o['db'].expire_all()
    result=c.get(url+'/data').json();level=result['works']['levels'][0]
    assert level['axis_ngf']==12 and level['struts']==[]
    assert counts(result['works'])['struts']==6 and counts(result['works'])['placed']==2
    assert result['summary']['puntoni']['total']==6
    body.update(revision=result['revision'],works=result['works'])
    level['planned_count']=8;level['completed_count']=3
    saved=c.put(url+'/data',json=body);assert saved.status_code==200,saved.text
    result=c.get(url+'/data').json();assert len(result['works']['levels'])==1
    assert result['summary']['puntoni']['total']==8
    assert result['summary']['puntoni']['levels'][0]['total']==8
    result['works']['levels'][0]['struts']=[strut()]
    body.update(revision=result['revision'],works=result['works'])
    assert c.put(url+'/data',json=body).status_code==200
    result=c.get(url+'/data').json()
    assert result['summary']['puntoni']['total']==1 and result['summary']['puntoni']['done']==1
    assert result['summary']['puntoni']['levels'][0]['total']==1
    assert o['db'].query(SiteStrutLevel).one().total_struts_level==6


def test_progress_validation_and_permissions_preserve_automatic_sources(operations):
    o=operations;c,url,body=setup(o)
    assert c.put(url+'/data',json=body).status_code==200
    for payload in ({'installazione_cantiere_pct':101},{'cordoli_done_m':-1},{'cordoli_total_m':0},{'unknown':1}):
        assert c.patch(url+'/progress',json=payload).status_code==422
    for key in ('pozzi_pompaggio_pct','rabotage_pct'):
        assert c.patch(url+'/progress',json={key:50}).status_code==400
    assert c.patch(url+'/progress',json={'installazione_cantiere_pct':None}).status_code==400
    assert c.patch(url+'/progress',json={'installazione_cantiere_pct':50},headers={'Origin':'https://evil.example'}).status_code==403
    o['actor'][0]=o['capo']
    assert c.patch(url+'/progress',json={'cordoli_done_m':4}).status_code==403
    o['actor'][0]=o['outsider']
    assert c.patch(url+'/progress',json={'cordoli_done_m':4}).status_code==403


def test_manual_progress_works_before_plan_is_configured(operations):
    o=operations;o['actor'][0]=o['manager'];url=f'/manager/cantieri/{o["site"].id}/avanzamento'
    result=o['client'].patch(url+'/progress',json={'installazione_cantiere_pct':20,'cordoli_total_m':45,'cordoli_done_m':9,'pozzi_pompaggio_pct':10})
    assert result.status_code==200,result.text
    assert result.json()['reference'] is None
    assert result.json()['summary']['cordoli']['percent']==20
    assert o['db'].query(SiteWorksMap).count()==0


def test_levels_can_be_configured_before_plan_and_attach_without_losing_counts(operations):
    o=operations;o['actor'][0]=o['manager'];c=o['client'];url=f'/manager/cantieri/{o["site"].id}/avanzamento'
    value={'levels':[dict(id='level1',name='Livello 1',axis_ngf=12,planned_count=6,completed_count=2,struts=[])],'wells':[],'rabotage':[]}
    body=dict(revision=0,plan_id=None,plan_revision=None,works=value)
    response=c.put(url+'/data',json=body);assert response.status_code==200,response.text
    assert o['db'].get(SiteWorksMap,o['site'].id).reference=='null'
    result=c.get(url+'/data').json()
    assert result['reference'] is None and result['summary']['puntoni']['total']==6
    body.update(revision=1,works=result['works'])
    body['works']['levels'][0]['struts']=[strut()]
    assert c.put(url+'/data',json=body).status_code==400
    assert c.get(url+'/data').json()['works']['levels'][0]['struts']==[]
    _,_,plan_body=setup(o)
    result=c.get(url+'/data').json()
    assert result['reference']['plan_id']==plan_body['plan_id']
    assert result['works']['levels'][0]['planned_count']==6
    body.update(works=result['works'],plan_id=plan_body['plan_id'],plan_revision=1)
    assert c.put(url+'/data',json=body).status_code==200
    assert json.loads(o['db'].get(SiteWorksMap,o['site'].id).reference)['plan_id']==plan_body['plan_id']
