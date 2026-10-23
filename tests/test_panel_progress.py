import json
from types import SimpleNamespace

import pytest
from models import Fiche, RoleEnum, SitePlan, SiteCoupe, SiteCoupeAssignment
from services.panel_progress import count_panels, panel_progress, planned_surface
from services.fiche_review import review_token
from utils.production_stats import compute_site_production
from test_operations import operations
from test_site_pours import setup, fiche


def row(number, status='confirmed', kind='paratia'):
    return SimpleNamespace(numero_pannello=number, review_status=status,
                           tipologia_scavo=kind, pour_panels=[])


def test_physical_panel_counts_partial_corners_and_unrelated_elements():
    corners=[(1,2),(1,2),(3,4),(3,99)]
    result=count_panels(6,[row(1),row(2),row(3),row(4,'pending'),row(5),row(6,kind='palo')],corners)
    assert result==dict(done=2,total=4,percent=50,pending=1,remaining=2,angles=2)
    assert count_panels(6,[row(1)],corners)['done']==0
    assert count_panels(6,[row(1),row(1)],())['done']==1
    assert count_panels(0,[row(1)],())['percent']==0


def test_approved_corners_reduce_target_before_coupe_or_fiche(operations):
    o=operations; setup(o); db=o['db']; plan=db.query(SitePlan).one()
    data=json.loads(plan.approved)
    for panel in data['panels']: panel['corner_group']='corner-7'
    plan.approved=json.dumps(data); db.commit()
    o['site'].numero_totale_paratie=5; db.commit()  # Other configured panels survive a partial plan.
    assert panel_progress(o['site'])==dict(done=0,total=4,percent=0,pending=0,remaining=4,angles=1)
    assert o['site'].numero_totale_paratie==5


@pytest.mark.parametrize('kind,labels,target', [('angle',('P7A','P7B'),1),('joint',('P1','P2'),2)])
def test_confirmed_corner_or_joint_progress_and_quantities(operations,kind,labels,target):
    o=operations; base=setup(o,labels); db=o['db']; c=o['client']
    response=c.post(base+'/getti',json={'numbers':[1,2],'kind':kind,'confirm_net':True})
    assert response.status_code==200, response.text
    assert panel_progress(o['site'])['total']==target
    assert fiche(o,1,42).status_code==303
    if kind=='joint': assert fiche(o,2,18).status_code==303
    db.expire_all(); fiches=db.query(Fiche).all()
    assert panel_progress(o['site'],fiches)['done']==0
    assert panel_progress(o['site'],fiches)['pending']==target
    o['manager'].role=RoleEnum.admin; db.commit()
    for f in fiches:
        assert c.post(f'/manager/fiches/{f.id}/conferma',data={'csrf':review_token(f,o['manager'])},follow_redirects=False).status_code==303
    db.expire_all()
    result=panel_progress(o['site'],fiches)
    assert result['done']==result['total']==target and result['percent']==100
    stats=compute_site_production(o['site'],fiches)
    assert stats['paratie']['count']==stats['paratie']['target']==target
    assert stats['paratie']['superficie']==80
    assert stats['paratie']['surface_progress']==dict(total=80,missing=0,elements=2,
                                                    executed=80,executed_missing=0,percent=100)
    assert stats['totale']['volume_cls_reale']==(42 if kind=='angle' else 60)
    assert o['site'].numero_totale_paratie==2 and len(json.loads(db.query(SitePlan).one().approved)['panels'])==2
    page=c.get(base); assert page.status_code==200
    assert f'{target} / {target}' in page.text and 'Superficie paratia eseguita' in page.text
    from main import _build_site_progress
    assert _build_site_progress(o['site'],'it')[0]['paratie']['total']==target
    fiches[0].notes='Ricontrollare'; db.commit()
    assert panel_progress(o['site'],fiches)['pending']==1
    assert panel_progress(o['site'],fiches)['done']==target-1


def test_project_surface_uses_each_arm_width_and_its_assigned_depth(operations):
    o=operations; setup(o); db=o['db']; plan=db.query(SitePlan).one()
    layout=json.loads(plan.approved)
    for p in layout['panels']: p['corner_group']='corner-7'
    plan.approved=json.dumps(layout)
    c=SiteCoupe(site_id=o['site'].id,nome='Coupe 2',profondita_teorica=12,larghezza=99)
    db.add(c);db.flush()
    db.query(SiteCoupeAssignment).filter_by(numero_elemento=2).one().coupe=c
    db.commit()
    assert panel_progress(o['site'])['total']==1
    assert planned_surface(o['site'])==dict(total=86,missing=0,elements=2)  # 5*10 + 3*12
    # Other sites and unapproved drafts cannot affect this project's total.
    plan.draft=json.dumps({'panels':[dict(element=1,width_m=500)]})
    db.add(SiteCoupeAssignment(site_id=o['other'].id,coupe_id=c.id,tipologia_scavo='paratia',numero_elemento=1))
    db.commit()
    assert planned_surface(o['site'])['total']==86


def test_surface_comparison_keeps_project_target_separate_from_actual_fiche(operations):
    o=operations; setup(o,('P1','P2')); db=o['db']
    assert fiche(o,1,30).status_code==303
    f=db.query(Fiche).one();f.profondita_totale=12;db.commit()
    f.review_status='confirmed';db.commit()
    s=compute_site_production(o['site'],[f])['paratie']['surface_progress']
    assert s['total']==80 and s['executed']==60 and s['percent']==75
    f.profondita_totale=20;db.commit()
    f.review_status='confirmed';db.commit()
    s=compute_site_production(o['site'],[f])['paratie']['surface_progress']
    assert s['total']==80 and s['executed']==100 and s['percent']==125
    f.review_status='pending';db.commit()
    s=compute_site_production(o['site'],[f])['paratie']['surface_progress']
    assert s['executed']==0 and s['percent']==0
    f.larghezza_pannello=None;db.commit()
    f.review_status='confirmed';db.commit()
    s=compute_site_production(o['site'],[f])['paratie']['surface_progress']
    assert s['executed'] is None and s['executed_missing']==1 and s['percent'] is None


def test_project_surface_does_not_publish_partial_total(operations):
    o=operations; setup(o); db=o['db']
    o['site'].numero_totale_paratie=3;db.commit()
    s=compute_site_production(o['site'],[])['paratie']['surface_progress']
    assert s['total'] is None and s['missing']==1 and s['percent'] is None
    assert 'Totale superficie da completare' in o['client'].get(f'/manager/cantieri/{o["site"].id}').text
    assert planned_surface(o['other'])==dict(total=None,missing=0,elements=0)


@pytest.mark.parametrize('width', [4,0,-2,float('inf')])
def test_project_surface_without_plan_uses_only_valid_assigned_coupe_width(operations,width):
    o=operations;setup(o);db=o['db']
    db.query(SitePlan).delete()
    c=db.query(SiteCoupe).one();c.larghezza=width;db.commit()
    result=planned_surface(o['site'])
    assert result['total']==(80 if width==4 else None)
    assert result['missing']==(0 if width==4 else 2)
