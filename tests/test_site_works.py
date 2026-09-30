import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from models import SitePlan, SiteWorksMap, SiteStrutDrawing, Fiche
from services.site_works import validate_works, empty_works, counts
from services.strut_drawing import read_pdf
from test_operations import operations
from test_site_plans import vector_pdf


def layout():
    return dict(width=210,height=210,scale_ppm=10,panels=[
        dict(key='left',label='P1',points=[[10,20],[20,20],[20,180],[10,180]],element=1,width_m=16),
        dict(key='right',label='P2',points=[[180,20],[190,20],[190,180],[180,180]],element=2,width_m=16)])


def strut():
    return dict(id='strut1',label='B1-A',panel_a='left',panel_b='right',a=[15,70],b=[185,70],
        length_m=16,diameter_mm=610,thickness_mm=10,status='installed',installed_on='2026-09-20',notes='Posa verificata')


def works():
    return dict(levels=[dict(id='level1',name='Livello -1',axis_ngf=6,struts=[strut()])],
        wells=[dict(id='well1',label='Pozzo 1',point=[80,120],status='pumping')],rabotage=[1])


def setup(o):
    o['actor'][0]=o['manager'];o['site'].numero_totale_paratie=2
    p=SitePlan(site_id=o['site'].id,filename='pianta.pdf',pdf_data=vector_pdf(),preview_data=b'png',
        draft=json.dumps(layout()),approved=json.dumps(layout()),revision=1,approved_revision=1,approved_at=datetime.utcnow())
    o['db'].add(p);o['db'].commit()
    url=f'/manager/cantieri/{o["site"].id}/avanzamento'
    return o['client'],url,dict(revision=0,plan_id=p.id,plan_revision=1,works=works())


def test_save_snap_reload_stale_and_independent_wall_state(operations):
    o=operations;c,url,body=setup(o)
    assert c.get(url).status_code==200
    response=c.put(url+'/data',json=body);assert response.status_code==200,response.text
    value=response.json()['works'];s=value['levels'][0]['struts'][0]
    assert s['a']==[20,70] and s['b']==[180,70]
    assert c.get(url+'/data').json()['works']==value
    assert c.put(url+'/data',json=body).status_code==409
    assert o['db'].query(Fiche).count()==0
    assert json.loads(o['db'].get(SitePlan,body['plan_id']).approved)==layout()
    summary=c.get(url+'/data').json()['summary'];assert summary['rabotage']['percent']==50
    assert summary['puntoni']['done']==1


def test_removal_requires_explicit_identity_and_cancel_preserves_all(operations):
    o=operations;c,url,body=setup(o);saved=c.put(url+'/data',json=body).json()
    body.update(revision=1,works=saved['works']);body['works']['wells']=[]
    assert c.put(url+'/data',json=body).status_code==400
    assert len(c.get(url+'/data').json()['works']['wells'])==1
    assert c.put(url+'/data',json={**body,'confirm_remove':['well1']}).status_code==200
    body['revision']=2;body['works']['levels']=[]
    assert c.put(url+'/data',json={**body,'confirm_remove':['level1']}).status_code==400
    assert c.put(url+'/data',json={**body,'confirm_remove':['level1','strut1']}).status_code==200


def test_site_permissions_origin_and_source_scope(operations):
    o=operations;c,url,body=setup(o)
    r=c.post(url+'/leggi-pdf',files={'file':('butons.pdf',vector_pdf())});assert r.status_code==200,r.text
    sid=r.json()['id']
    assert c.put(url+'/data',json=body,headers={'Origin':'https://evil.example'}).status_code==403
    o['actor'][0]=o['capo']
    assert c.get(url+'/data').status_code==200
    assert c.put(url+'/data',json=body).status_code==403
    assert c.post(url+'/leggi-pdf',files={'file':('x.pdf',vector_pdf())}).status_code==403
    o['actor'][0]=o['outsider']
    assert c.get(url+'/data').status_code==403
    assert c.get(url+f'/pdf/{sid}/originale').status_code==403
    o['actor'][0]=o['manager']
    assert c.get(f'/manager/cantieri/{o["other"].id}/avanzamento/pdf/{sid}/originale').status_code==404


def test_pdf_revision_keeps_progress_dates_notes_ids_and_omitted_elements(operations):
    o=operations;c,url,body=setup(o);saved=c.put(url+'/data',json=body).json()
    sid=c.post(url+'/leggi-pdf',files={'file':('butons.pdf',vector_pdf())}).json()['id']
    changed={**strut(),'id':'new-scan-id','length_m':17,'status':'planned','notes':'overwrite','installed_on':None}
    incoming={**body,'revision':1,'level_id':'level1','source_id':sid,'reviewed':True,'struts':[changed]}
    r=c.post(url+'/conferma-lettura',json={**incoming,'reviewed':False});assert r.status_code==400
    r=c.post(url+'/conferma-lettura',json=incoming);assert r.status_code==200,r.text
    s=r.json()['works']['levels'][0]['struts'][0]
    assert s['length_m']==17 and s['status']=='installed' and s['installed_on']=='2026-09-20'
    assert s['id']=='strut1' and s['notes']=='Posa verificata'
    incoming['revision']=2;incoming['struts']=[{**changed,'label':'B2-A','a':[15,140],'b':[185,140],'status':'installed'}]
    r=c.post(url+'/conferma-lettura',json=incoming);assert r.status_code==200,r.text
    assert len(r.json()['works']['levels'][0]['struts'])==2
    assert r.json()['works']['levels'][0]['struts'][1]['status']=='planned'
    assert r.json()['works']['wells']==saved['works']['wells']


def test_new_wall_revision_does_not_move_installed_struts(operations):
    o=operations;c,url,body=setup(o);assert c.put(url+'/data',json=body).status_code==200
    p=o['db'].get(SitePlan,body['plan_id']);new=layout();new['panels'][1]['points']=[[x+5,y] for x,y in new['panels'][1]['points']]
    p.approved=json.dumps(new);p.approved_revision=2;o['db'].commit()
    r=c.get(url+'/data').json();assert r['reference_changed']
    assert r['reference']['layout']==layout()
    assert r['works']['levels'][0]['struts'][0]['b']==[180,70]


@pytest.mark.parametrize('kind',['panel','duplicate','outside','same','thickness','date','crossing'])
def test_invalid_geometry_or_values_rejected(kind):
    v=works();p=layout();s=v['levels'][0]['struts'][0]
    if kind=='panel':s['panel_a']='other-site-panel'
    if kind=='duplicate':v['wells'][0]['id']='strut1'
    if kind=='outside':v['wells'][0]['point']=[999,1]
    if kind=='same':s['panel_b']='left'
    if kind=='thickness':s['thickness_mm']=400
    if kind=='date':s['removed_on']='2025-01-01'
    if kind=='crossing':p['panels'].append(dict(key='third',label='P3',points=[[90,20],[100,20],[100,180],[90,180]],element=3))
    with pytest.raises(ValueError):validate_works(v,p)


def test_pdf_page_crop_and_real_extraction():
    # Same byte length keeps this small synthetic vector PDF's xref valid.
    pdf=vector_pdf().replace(b'(P7a)',b'(B12)')
    result,preview=read_pdf(pdf)
    assert [s['label'] for s in result['struts']]==['B12']
    assert preview.startswith(b'\x89PNG')
    assert read_pdf(pdf,1,[0,0,.1,.1])[0]['struts']==[]
    for crop in ([0,0,0,0],[0,0,float('nan'),1],[-1,0,1,1]):
        with pytest.raises(ValueError):read_pdf(pdf,1,crop)
    with pytest.raises(ValueError):read_pdf(pdf,2)
    with pytest.raises(ValueError):read_pdf(b'not PDF')


def test_second_level_independent_and_deleted_site_cascades(operations):
    o=operations;c,url,body=setup(o)
    body['works']['levels'].append(dict(id='level2',name='Livello -2',axis_ngf=3,struts=[{**strut(),'id':'s2','status':'planned'}]))
    r=c.put(url+'/data',json=body);assert r.status_code==200,r.text
    assert r.json()['works']['levels'][1]['struts'][0]['status']=='planned'
    from services.site_deletion import delete_site_records
    c.post(url+'/leggi-pdf',files={'file':('b.pdf',vector_pdf())})
    delete_site_records(o['db'],o['site']);o['db'].commit()
    assert o['db'].query(SiteWorksMap).count()==o['db'].query(SiteStrutDrawing).count()==0


def test_coupe_axes_only_prefill_unambiguous_levels_without_progress():
    a=SimpleNamespace(drawing_info={'reviewed':True,'struts':[3,6]})
    site=SimpleNamespace(coupes=[a,a],strut_levels=[])
    value=empty_works(site)
    assert [l['axis_ngf'] for l in value['levels']]==[6,3]
    assert all(l['struts']==[] for l in value['levels'])
    site.coupes.append(SimpleNamespace(drawing_info={'reviewed':True,'struts':[5]}))
    assert empty_works(site)['levels']==[]


def test_removed_strut_keeps_completed_placement_but_is_not_in_operation():
    value=validate_works(works(),layout())
    value['levels'][0]['struts'][0]['status']='removed'
    totals=counts(value)
    assert totals['placed']==1 and totals['installed']==0 and totals['removed']==1


def test_dense_cad_axis_work_is_bounded_and_pdf_still_allows_crop(monkeypatch):
    import services.strut_drawing as reader
    class Segments(list):
        visits=0
        def __iter__(self):
            for item in super().__iter__():
                self.visits+=1
                yield item
    segments=Segments([((0,y/100),(200,y/100)) for y in range(4000)])
    budget=[20000]
    with pytest.raises(reader.AxisWorkLimit):
        reader.axis_proposal(dict(x=100,y=10,angle=0,size=10),segments,budget)
    assert segments.visits<=20000
    monkeypatch.setattr(reader,'MAX_AXIS_WORK',0)
    pdf=vector_pdf().replace(b'(P7a)',b'(B12)')
    result,preview=reader.read_pdf(pdf)
    assert result['struts'][0]['label']=='B12'
    assert result['struts'][0]['a'] is None
    assert 'Disegno molto denso' in result['notice']
    assert preview.startswith(b'\x89PNG')
    assert reader.read_pdf(pdf,1,[0,0,.1,.1])[0]['struts']==[]


def test_pdf_upload_extraction_runs_outside_event_loop(operations,monkeypatch):
    import asyncio
    import routes.site_works as routes
    original=routes.read_pdf
    def checked(*args):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return original(*args)
    monkeypatch.setattr(routes,'read_pdf',checked)
    c,url,_=setup(operations)
    assert c.post(url+'/leggi-pdf',files={'file':('b.pdf',vector_pdf())}).status_code==200
