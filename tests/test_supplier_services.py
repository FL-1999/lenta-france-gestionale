from datetime import date, timedelta
import uuid
import pytest
from sqlmodel import SQLModel
from database import ensure_model_columns
from models import Base, Supplier, SupplierService, ServiceRecord, Veicolo, SiteEconomicEntry, RoleEnum
from routes.site_costs import token
from services.supplier_services import history
from test_operations import operations


def setup(o):
    o['actor'][0] = o['manager']
    db = o['db']; ensure_model_columns(db.get_bind(), (Base.metadata, SQLModel.metadata))
    supplier = Supplier(name='Laboratoire et atelier'); db.add(supplier)
    vehicle = Veicolo(marca='Peugeot', modello='Expert', targa='TEST-001', km=10000,
                       revisione_scadenza=date(2030, 1, 1), visibile_trasporti=True)
    db.add(vehicle); db.commit()
    body = dict(request_key=str(uuid.uuid4()), supplier_id=supplier.id, title='Essai béton', kind='service',
                category='Laboratoire', unit='essai', price='35', quantity='6', date=str(date.today()),
                status='planned', site_id=o['site'].id)
    return supplier, vehicle, body


def save(o, body, action='record'):
    return o['client'].post('/manager/servizi/'+action, json=body, headers={'x-csrf-token': token(o['manager'])})


def test_service_costs_corrections_cancellation_no_duplicates(operations):
    o=operations;s,v,b=setup(o);db=o['db']
    r=save(o,b);assert r.status_code==200,r.text
    assert db.query(SiteEconomicEntry).count()==0
    assert save(o,b).status_code==409
    b.update(r.json(),status='executed');r=save(o,b);assert r.status_code==200,r.text
    entry=db.query(SiteEconomicEntry).one();assert entry.amount==210
    b.update(r.json(),quantity='7');r=save(o,b);assert r.status_code==200,r.text
    assert db.query(SiteEconomicEntry).count()==1 and entry.amount==245
    assert save(o,b).status_code==409
    b.update(r.json(),status='cancelled');assert save(o,b).status_code==400
    b['reason']='Erreur de saisie';r=save(o,b);assert r.status_code==200,r.text
    assert db.query(SiteEconomicEntry).count()==0 and db.query(ServiceRecord).one().status=='cancelled'


def test_maintenance_links_both_fleets_without_overwriting_inspection(operations):
    o=operations;s,v,b=setup(o);db=o['db']
    b.update(vehicle_id=v.id,maintenance=True,meter=10500,next_meter=20500,next_date='2031-01-01')
    r=save(o,b);assert r.status_code==200,r.text
    assert not history(db,vehicle_id=v.id)
    b.update(r.json(),status='executed');r=save(o,b);assert r.status_code==200,r.text
    assert len(history(db,vehicle_id=v.id))==1
    db.refresh(v);assert v.revisione_scadenza==date(2030,1,1) and v.km==10000
    for path in ['/manager/veicoli',f'/manager/veicoli/{v.id}',f'/manager/fornitori/{s.id}','/manager/servizi']:
        response=o['client'].get(path);assert response.status_code==200,response.text
    b.update(r.json(),vehicle_id=None,machine_id=o['machine'].id)
    r=save(o,b);assert r.status_code==200,r.text
    assert not history(db,vehicle_id=v.id) and len(history(db,machine_id=o['machine'].id))==1
    response=o['client'].get(f'/manager/macchinari/{o["machine"].id}');assert response.status_code==200,response.text
    assert 'Essai béton' in response.text


def test_catalogue_shared_supplier_and_history_protect_delete(operations):
    o=operations;s,v,b=setup(o)
    r=save(o,b,'catalogue');assert r.status_code==200,r.text
    b['catalogue_id']=r.json()['id'];assert save(o,b).status_code==200
    assert o['db'].query(Supplier).count()==1 and o['db'].query(SupplierService).count()==1
    r=o['client'].post(f'/manager/fornitori/{s.id}/elimina',data={'force':'1'},follow_redirects=False)
    assert r.status_code==303 and 'err=' in r.headers['location']
    assert o['db'].get(Supplier,s.id)


@pytest.mark.parametrize('change',[
    {'kind':'rental','start':'2026-10-01','end':'2026-09-01'},
    {'price':'NaN'}, {'quantity':0}, {'price':-1}, {'title':'  '},
    {'maintenance':True}, {'vehicle_id':999999},
    {'status':'executed','date':str(date.today()+timedelta(days=1))},
])
def test_invalid_service_does_not_write(operations,change):
    o=operations;s,v,b=setup(o);b.update(change)
    r=save(o,b);assert r.status_code==400,r.text
    assert o['db'].query(ServiceRecord).count()==o['db'].query(SiteEconomicEntry).count()==0


def test_role_csrf_transport_prefill_and_site_delete(operations):
    o=operations;s,v,b=setup(o);c=o['client'];db=o['db']
    assert c.post('/manager/servizi/record',json=b).status_code==403
    o['actor'][0]=o['capo'];assert c.get('/manager/servizi/data').status_code==403
    assert save(o,b).status_code==403
    o['actor'][0]=o['manager']
    r=c.get(f'/manager/trasporti/viaggi/nuovo?mezzo_id={v.id}');assert r.status_code==200,r.text
    b.update(status='executed');assert save(o,b).status_code==200
    from services.site_deletion import delete_site_records
    delete_site_records(db,o['site']);db.commit();db.expire_all()
    record=db.query(ServiceRecord).one();assert record.site_id is None
    assert record.payload['site_name']=='Cantiere assegnato'
    assert db.query(SiteEconomicEntry).count()==0


def test_unit_and_service_navigation(operations):
    from utils.warehouse_packaging import ARTICLE_UNITS, convert_quantity
    o=operations;setup(o)
    assert 'unita' in ARTICLE_UNITS
    assert convert_quantity(4, 'unita', 'unita', None, None, None, None)==4
    response=o['client'].get('/manager/magazzino/nuovo')
    assert response.status_code==200 and 'value="unita"' in response.text
    response=o['client'].get('/manager/servizi')
    assert response.context['purchase_nav']['section']=='services'


def test_manual_oblique_corner_preserves_shape_requires_net_confirmation(operations):
    from test_plan_corners import setup as corner_setup
    o=operations;url,row,b=corner_setup(o)
    a,c=b['panels'];c['points']=[[45,140],[95,145],[93,165],[43,160]]
    for p in b['panels']:p.update(corner_manual=True,extent_confirmed=True)
    c['width_m']=((50**2+5**2)**.5)/40
    c['corner_net_confirmed']=False
    assert o['client'].put(url+f'/{row.id}/convalida',json=b).status_code==400
    c['corner_net_confirmed']=True
    r=o['client'].put(url+f'/{row.id}/convalida',json=b);assert r.status_code==200,r.text
    saved=o['client'].get(url+'/data').json()['plan']['layout']['panels']
    assert saved[1]['points']==c['points'] and all(p['corner_manual'] for p in saved)
