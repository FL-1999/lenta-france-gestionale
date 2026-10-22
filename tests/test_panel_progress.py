import json
from types import SimpleNamespace

import pytest
from models import Fiche, RoleEnum, SitePlan
from services.panel_progress import count_panels, panel_progress
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
    assert stats['totale']['volume_cls_reale']==(42 if kind=='angle' else 60)
    assert o['site'].numero_totale_paratie==2 and len(json.loads(db.query(SitePlan).one().approved)['panels'])==2
    page=c.get(base); assert page.status_code==200
    assert f'{target} / {target}' in page.text and 'Superficie paratia eseguita' in page.text
    from main import _build_site_progress
    assert _build_site_progress(o['site'],'it')[0]['paratie']['total']==target
    fiches[0].notes='Ricontrollare'; db.commit()
    assert panel_progress(o['site'],fiches)['pending']==1
    assert panel_progress(o['site'],fiches)['done']==target-1
