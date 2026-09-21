from datetime import datetime
import pytest
import re
from tests.test_operations import operations
from models import Depot, Attrezzatura, MachineSiteAssignment
from utils.places import get_selectable_places, get_place_by_value


def setup(o):
    o['actor'][0] = o['manager']
    return o['client'], o['db']


def test_filters_and_real_depot_locations(operations):
    c, db = setup(operations)
    active = Depot(name='Montauroux', city='Nice', is_active=True)
    inactive = Depot(name='Riserva', city='Nice', is_active=False)
    db.add_all([active, inactive]); db.commit()
    response = c.get('/manager/depositi?q=Nice&stato=attivi&per_page=1&page=99')
    assert response.status_code == 200
    assert response.text.count('data-depot-item') == 1
    assert 'Montauroux' in response.text and 'Riserva' not in response.text
    values = {p.value for p in get_selectable_places(db)}
    assert f'depot:{active.id}' in values and f'depot:{inactive.id}' not in values
    assert get_place_by_value(db, f'depot:{active.id}', include_inactive=False)
    assert get_place_by_value(db, f'depot:{inactive.id}', include_inactive=False) is None
    assert get_place_by_value(db, f'depot:{inactive.id}', include_inactive=True)


@pytest.mark.parametrize('lat,lng', [('NaN','2'),('91','2'),('45','181'),('45','')])
def test_invalid_coordinates_preserve_depot(operations, lat, lng):
    c, db = setup(operations)
    depot = Depot(name='Originale', lat=45, lng=2)
    db.add(depot); db.commit(); depot_id=depot.id
    response = c.post(f'/manager/depositi/{depot_id}/modifica', data={'name':'Sbagliato','lat':lat,'lng':lng,'is_active':'on'})
    assert response.status_code == 400
    db.expire_all()
    assert db.get(Depot, depot_id).name == 'Originale'
    assert db.get(Depot, depot_id).lat == 45


def test_rename_preserves_current_resources_and_history(operations):
    c, db = setup(operations)
    depot = Depot(name='Prima')
    assignment = MachineSiteAssignment(machine_id=operations['machine'].id, location_label='[Deposito] Prima')
    historical = MachineSiteAssignment(machine_id=operations['machine'].id, location_label='[Deposito] Prima', unassigned_at=datetime(2026,1,1))
    equipment = Attrezzatura(codice='ATT1',qr_code='ATT1',nome='Pompa deposito',tipo='Pompa',posizione_attuale='[Deposito] Prima')
    db.add_all([depot,assignment,historical,equipment]);db.commit()
    response=c.post(f'/manager/depositi/{depot.id}/modifica',data={'name':'Dopo','is_active':'on'},follow_redirects=False)
    assert response.status_code==303
    db.expire_all()
    assert assignment.location_label=='[Deposito] Dopo'
    assert equipment.posizione_attuale=='[Deposito] Dopo'
    assert historical.location_label=='[Deposito] Prima'
    detail=c.get(f'/manager/depositi/{depot.id}')
    assert detail.status_code==200 and 'Pompa deposito' in detail.text and 'Macchina prova' in detail.text


def test_inactive_creation_and_cantiere_separation(operations):
    c,db=setup(operations)
    response=c.post('/manager/depositi/nuovo',data={'name':'Riserva','is_active':'off'},follow_redirects=False)
    assert response.status_code==303
    assert not db.query(Depot).filter_by(name='Riserva').one().is_active
    response=c.get('/manager/cantieri/nuovo')
    assert response.status_code==200
    assert len(re.findall(r'class="cantiere-step(?: is-active)?"',response.text))==3
    assert 'Depositi disponibili' not in response.text
    assert 'name="deposito_id"' not in response.text
    operations['actor'][0]=operations['capo']
    assert c.post('/manager/depositi/nuovo',data={'name':'Vietato'}).status_code==403
    assert not db.query(Depot).filter_by(name='Vietato').first()
