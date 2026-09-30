import copy
import json

from models import SitePlan, SiteProgressGridName, SitePour, CloudPlanPublication, SiteCoupe, SiteCoupeAssignment
from test_operations import operations
from test_plan_corners import layout, setup


def multiple_corners():
    data=layout();data['width']=900
    data['panels']=[]
    for number,offset,shift in ((4,0,-4),(7,300,0),(12,600,4)):
        pair=layout()['panels']
        for p in pair:
            p.update(key=f"{number}{p['key']}",label=f"P{number}{p['key']}",corner_group=f'{number}a',extent_confirmed=True)
            p['points']=[[x+offset+(shift if p['key'].endswith('a') else 0),y] for x,y in p['points']]
            p['reference_points']=copy.deepcopy(p['points'])
        data['panels'].extend(pair)
    return data


def test_preflight_collects_all_errors_matches_final_and_never_writes(operations):
    o=operations;url,row,body=setup(o);db=o['db'];data=multiple_corners()
    row.draft=json.dumps(data);db.commit()
    original=row.draft
    body['panels']=copy.deepcopy(data['panels'])
    body['panels'][2]['reviewed']=False
    body['panels'][3]['width_m']=None
    models=(SiteProgressGridName,SitePour,CloudPlanPublication)
    counts=[db.query(m).count() for m in models]
    response=o['client'].post(url+f'/{row.id}/verifica',json=body)
    assert response.status_code==200,response.text
    issues=response.json()['issues']
    assert any(i['field']=='corner' and i['keys']==['4a','4b'] and 'sovrappongono' in i['message'] for i in issues)
    assert any(i['field']=='corner' and i['keys']==['12a','12b'] for i in issues)
    assert any(i['field']=='reviewed' and i['keys']==['7a'] for i in issues)
    assert any(i['field']=='width_m' and i['keys']==['7b'] for i in issues)
    failed=o['client'].put(url+f'/{row.id}/convalida',json=body)
    assert failed.status_code==400 and failed.json()['issues']==issues
    db.expire_all()
    assert row.draft==original and row.revision==1 and row.approved is None
    assert counts==[db.query(m).count() for m in models]
    # Saving an unfinished but structurally valid draft remains possible.
    body['panels'][2]['reviewed']=True
    assert o['client'].put(url+f'/{row.id}/bozza',json=body).status_code==200
    db.expire_all();saved=json.loads(row.draft)['panels']
    assert all(p['reviewed'] for p in saved) and saved[3]['width_m'] is None
    assert row.approved is None


def test_preflight_reports_coupe_conflict_even_with_geometry_errors(operations):
    o=operations;url,row,body=setup(o);db=o['db']
    assert o['client'].put(url+f'/{row.id}/convalida',json=body).status_code==200
    db.expire_all();body['revision']=row.revision;body['panels']=json.loads(row.approved)['panels']
    for n,p in enumerate(body['panels']):
        cup=SiteCoupe(site_id=o['site'].id,nome=f'Coupe {n}',profondita_teorica=10,spessore=.5)
        db.add(cup);db.flush()
        db.add(SiteCoupeAssignment(site_id=o['site'].id,coupe_id=cup.id,tipologia_scavo='paratia',numero_elemento=p['element']))
    db.commit()
    body['panels'][0]['points']=[[x-3,y] for x,y in body['panels'][0]['points']]
    response=o['client'].post(url+f'/{row.id}/verifica',json=body)
    assert response.status_code==200,response.text
    issues=response.json()['issues']
    assert {'corner','project','extent_confirmed'} <= {i['field'] for i in issues}
    assert db.query(SitePour).count()==0


def test_preflight_permissions_revision_and_original_identity(operations):
    o=operations;url,row,body=setup(o);c=o['client'];db=o['db']
    assert c.put(url+f'/{row.id}/convalida',json=body).status_code==200
    assert c.post(url+f'/{row.id}/verifica',json=body).status_code==409
    db.expire_all();body['revision']=row.revision;body['panels']=json.loads(row.approved)['panels']
    for p in body['panels']:p['element']=None
    response=c.post(url+f'/{row.id}/verifica',json=body)
    assert len([i for i in response.json()['issues'] if i['field']=='element'])==2
    assert c.post(url+f'/{row.id}/verifica',json=body,headers={'Origin':'https://untrusted.example'}).status_code==403
    o['actor'][0]=o['capo']
    assert c.post(url+f'/{row.id}/verifica',json=body).status_code==403
