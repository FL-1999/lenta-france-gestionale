from uuid import uuid4
import pytest
from models import (Attrezzatura, AttrezzaturaStatoEnum, Depot, User, RoleEnum, FleetJourney,
                    FleetLoad, FleetOperation, Machine, MovimentoAttrezzatura, FleetPosition, TrasportoViaggio)
from models.veicoli import Veicolo
from database import ensure_model_columns
from models import Base
from sqlmodel import SQLModel
from test_operations import operations


def setup(o):
    db=o['db'];o['actor'][0]=o['manager']
    ensure_model_columns(db.get_bind(),(Base.metadata,SQLModel.metadata))
    depot=Depot(name='Deposito',is_active=True)
    driver=User(email='fleet-driver@example.com',full_name='Autista',role=RoleEnum.driver,hashed_password='x',is_active=True)
    vehicle=Veicolo(marca='Test',modello='Camion',targa='FLEET01',categoria='camion',visibile_trasporti=True)
    pump=Attrezzatura(codice='POM-01',qr_code='OLD-QR-01',nome='Pompa',tipo='Pompe',stato=AttrezzaturaStatoEnum.disponibile,posizione_attuale='Deposito')
    gen=Attrezzatura(codice='GEN-01',qr_code='GEN-01',nome='Gruppo',tipo='Generatori',stato=AttrezzaturaStatoEnum.manutenzione,posizione_attuale=o['site'].name)
    bucket=Machine(name='Benna da scavo',site_id=o['site'].id,status='attivo',is_active=True)
    db.add_all([depot,driver,vehicle,pump,gen,bucket]);db.commit()
    D=f'depot:{depot.id}';A=f'site:{o["site"].id}';B=f'site:{o["other"].id}'
    payload=dict(token=uuid4().hex,day='2026-10-06',hour='07:00',driver_id=driver.id,vehicle_id=vehicle.id,start=D,return_to_start=True,
        moves=[dict(key=f'equipment:{pump.id}',origin=D,destination=B),
               dict(key=f'equipment:{gen.id}',origin=A,destination=D,reason='Guasto / riparazione'),
               dict(key=f'machine:{bucket.id}',origin=A,destination=B)])
    return payload,driver,pump,gen,bucket


def create(o,payload):
    r=o['client'].post('/api/parco/viaggi',json=payload);assert r.status_code==200,r.text
    trip_id=int(r.json()['url'].rsplit('/',1)[1])
    return trip_id


def test_fleet_creation_inventory_qr_and_permissions(operations):
    o=operations;payload,driver,pump,gen,bucket=setup(o);c=o['client'];db=o['db']
    assert c.get('/manager/parco').status_code==200
    from services.fleet import inventory
    row=next(a for a in inventory(db) if a['key']==f'machine:{bucket.id}')
    assert row['family']=='Attrezzature' and row['category']=='Benne'
    assert c.get(f'/manager/parco/qr/equipment/{pump.id}').headers['content-type'].startswith('image/svg+xml')
    trip_id=create(o,payload)
    assert create(o,payload)==trip_id
    assert db.query(TrasportoViaggio).count()==1
    assert pump.posizione_attuale=='Deposito' and gen.stato==AttrezzaturaStatoEnum.manutenzione
    assert db.query(FleetLoad).count()==3
    assert c.get(f'/logistica/viaggi/{trip_id}').status_code==200
    assert c.get(f'/manager/trasporti/viaggi/{trip_id}',follow_redirects=False).status_code==303
    assert c.post(f'/driver/trasporti/viaggi/{trip_id}/stato',data={'nuovo_stato':'completato'}).status_code==409
    o['actor'][0]=o['outsider']
    assert c.get('/manager/parco').status_code==403
    assert c.get(f'/api/parco/viaggi/{trip_id}').status_code==404
    o['actor'][0]=driver
    assert c.get(f'/logistica/viaggi/{trip_id}').status_code==200
    assert c.post('/api/parco/viaggi',json=payload).status_code==403


def test_edit_before_departure_reuses_trip_and_releases_removed_assets(operations):
    from sqlalchemy import text
    o=operations;payload,*_=setup(o);c=o['client']
    if o['db'].get_bind().dialect.name=='sqlite':
        o['db'].commit()
        o['db'].execute(text('PRAGMA foreign_keys=ON'))
        assert o['db'].execute(text('PRAGMA foreign_keys')).scalar()==1
    trip_id=create(o,payload)
    assert c.get(f'/manager/trasporti/organizza?edit_id={trip_id}').status_code==200
    assert c.post('/api/parco/anteprima',json={**payload,'edit_id':trip_id}).status_code==200
    changed={**payload,'revision':0,'hour':'10:00','moves':payload['moves'][:1]}
    r=c.post(f'/api/parco/viaggi/{trip_id}/modifica',json=changed);assert r.status_code==200,r.text
    assert o['db'].query(TrasportoViaggio).count()==1
    assert o['db'].query(FleetLoad).count()==1
    j=c.get(f'/api/parco/viaggi/{trip_id}').json()
    assert j['editable'] and j['hour']=='10:00'
    assert c.post(f'/api/parco/viaggi/{trip_id}/modifica',json=changed).status_code==409
    op=j['operations'][0]
    assert c.post(f'/api/parco/viaggi/{trip_id}/esito',json=dict(revision=j['revision'],action='done',operation_id=op['id'])).status_code==200
    assert c.post(f'/api/parco/viaggi/{trip_id}/modifica',json={**changed,'revision':2}).status_code==409


def test_driver_done_failed_pickup_corrections_and_recovery(operations):
    o=operations;payload,driver,pump,gen,bucket=setup(o);c=o['client'];db=o['db'];trip_id=create(o,payload)
    o['actor'][0]=driver
    base=f'/api/parco/viaggi/{trip_id}'
    def state():return c.get(base).json()
    def action(act,key=None,kind=None,reason='',destination=None):
        j=state();op=next((op for op in j['operations'] if op['stop']==j['stop'] and op['kind']==kind and next(l for l in j['loads'] if l['id']==op['load_id'])['asset']['key']==key and (op['result']=='pending' if act!='correct' else op['result']=='yes')),None)
        r=c.post(base+'/esito',json=dict(revision=j['revision'],action=act,operation_id=op['id'] if op else None,reason=reason,destination=destination));assert r.status_code==200,r.text;return r.json()
    # Depot pickup, then B (direct delivery), A pickup, B and depot return.
    action('done',f'equipment:{pump.id}','load')
    action('correct',f'equipment:{pump.id}','load')
    assert db.get(Attrezzatura,pump.id).posizione_attuale=='Deposito'
    action('done',f'equipment:{pump.id}','load');action('next')
    j=state();op=next(op for op in j['operations'] if op['stop']==j['stop'])
    assert c.post(base+'/esito',json=dict(revision=j['revision'],action='not_done',operation_id=op['id'],reason=' ')).status_code==400
    action('not_done',f'equipment:{pump.id}','unload','Accesso bloccato');action('next')
    action('not_done',f'equipment:{gen.id}','load','Non pronto')
    action('done',f'machine:{bucket.id}','load');action('next')
    action('done',f'machine:{bucket.id}','unload');action('next')
    assert db.get(Machine,bucket.id).site_id==o['other'].id
    assert c.post(base+'/esito',json=dict(revision=state()['revision'],action='next')).status_code==409
    action('recover',destination=payload['start'])
    action('done',f'equipment:{pump.id}','unload');action('next')
    assert state()['finished']
    assert gen.posizione_attuale==o['site'].name and gen.stato==AttrezzaturaStatoEnum.manutenzione
    assert pump.posizione_attuale=='Deposito'
    assert db.query(MovimentoAttrezzatura).count()==1
    assert any(op['result']=='skip' for op in state()['operations'])
    assert c.post(base+'/esito',json=dict(revision=0,action='next')).status_code==409


def test_plan_rejects_duplicate_wrong_origin_reservations_and_stale_writes(operations):
    o=operations;payload,driver,pump,gen,bucket=setup(o);c=o['client']
    assert c.post('/api/parco/anteprima',json={**payload,'moves':[payload['moves'][0]]*2}).status_code==400
    assert c.post('/api/parco/anteprima',json={**payload,'moves':[{**payload['moves'][0],'origin':payload['moves'][1]['origin']}]}).status_code==409
    trip_id=create(o,payload)
    assert c.post('/api/parco/viaggi',json={**payload,'token':uuid4().hex,'hour':'08:00'}).status_code==409
    j=c.get(f'/api/parco/viaggi/{trip_id}').json();op=next(op for op in j['operations'] if op['stop']==0)
    args=dict(revision=0,action='done',operation_id=op['id'])
    assert c.post(f'/api/parco/viaggi/{trip_id}/esito',json=args).status_code==200
    assert c.post(f'/api/parco/viaggi/{trip_id}/esito',json=args).status_code==409


def test_postgres_competing_fleet_reservations(operations):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from routes.fleet import create as create_api, CreateInput
    o=operations;payload,*_=setup(o);engine=o['db'].get_bind()
    if engine.dialect.name!='postgresql':
        pytest.skip('Concurrent row locks are verified on PostgreSQL in CI')
    barrier=Barrier(2);manager_id=o['manager'].id
    def reserve(hour):
        with Session(engine) as db:
            user=db.get(User,manager_id)
            barrier.wait(timeout=10)
            try:
                create_api(CreateInput(**{**payload,'token':uuid4().hex,'hour':hour}),db,user)
                return 200
            except HTTPException as exc:
                db.rollback();return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(reserve,h) for h in ['08:00','09:00']]
        assert sorted(f.result(timeout=25) for f in futures)==[200,409]
    assert o['db'].query(FleetLoad).count()==3


def test_maintenance_survives_transport_and_recovery_has_one_current_attempt(operations):
    o=operations;payload,driver,pump,gen,bucket=setup(o);c=o['client'];db=o['db']
    payload['moves']=[payload['moves'][1]]
    trip_id=create(o,payload);base=f'/api/parco/viaggi/{trip_id}'
    def send(action,operation_id=None,**kw):
        j=c.get(base).json()
        return c.post(base+'/esito',json=dict(action=action,revision=j['revision'],operation_id=operation_id,**kw))
    assert send('next').status_code==200
    j=c.get(base).json();load=next(o for o in j['operations'] if o['kind']=='load')
    assert send('done',load['id']).status_code==200
    assert db.get(Attrezzatura,gen.id).stato==AttrezzaturaStatoEnum.manutenzione
    assert send('next').status_code==200
    j=c.get(base).json();unload=next(o for o in j['operations'] if o['kind']=='unload')
    assert send('not_done',unload['id'],reason='Area non libera').status_code==200
    assert send('recover',destination=payload['start']).status_code==200
    assert send('correct',unload['id']).status_code==409
    j=c.get(base).json();retry=next(o for o in j['operations'] if o['result']=='pending')
    assert send('done',retry['id']).status_code==200
    assert db.get(Attrezzatura,gen.id).stato==AttrezzaturaStatoEnum.manutenzione
    assert send('next').status_code==200
