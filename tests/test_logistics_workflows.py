"""Real HTTP workflow regressions. Also executed against PostgreSQL in CI."""
from datetime import date

import pytest
from sqlmodel import SQLModel

from database import ensure_model_columns
from models import (Base, Attrezzatura, AttrezzaturaStatoEnum, Depot, MagazzinoItem,
                    MagazzinoMovimento, MagazzinoRichiesta, MagazzinoRichiestaStatusEnum,
                    MovimentoAttrezzatura, RoleEnum, TrasportoViaggio, User)
from models.veicoli import Veicolo
from test_operations import operations


def trip_setup(o, monkeypatch):
    db=o['db']; o['actor'][0]=o['manager']
    ensure_model_columns(db.get_bind(), (Base.metadata, SQLModel.metadata))
    driver=User(email='logistics-driver@example.com', role=RoleEnum.driver, hashed_password='x', is_active=True)
    depot=Depot(name='Deposito Collaudo', is_active=True)
    pump=Attrezzatura(codice='POMPA-01', qr_code='ATT-P01', tipo='pompa', nome='Pompa prova', stato=AttrezzaturaStatoEnum.disponibile)
    tool=Attrezzatura(codice='TOOL-02', qr_code='ATT-T02', tipo='utensile', nome='Utensile prova', stato=AttrezzaturaStatoEnum.disponibile)
    db.add_all([driver,depot,pump,tool]);db.commit()
    monkeypatch.setattr('routes.trasporti._sync_trip_eta', lambda trip: 'ETA non configurata nel collaudo')
    payload={'codice_viaggio':'TEST-A-B','data_partenza':'2026-09-16','autista_id':driver.id,
             'origine_place':f'depot:{depot.id}','destinazione_place':f'site:{o["other"].id}',
             'tappa_destinazione':[f'site:{o["site"].id}', f'site:{o["other"].id}'],
             'tipo_attrezzatura':['pompa','utensile'], 'quantita':['1','1'],
             'richiesta_tappa_idx':['1','2'],'richiesta_origine_idx':['0','1']}
    r=o['client'].post('/manager/trasporti/viaggi/nuovo',data=payload,follow_redirects=False)
    assert r.status_code==303,r.text
    trip=db.query(TrasportoViaggio).filter_by(codice_viaggio='TEST-A-B').one()
    return trip,driver,pump,tool,payload


def test_multistop_planning_scans_and_history(operations, monkeypatch):
    o=operations;db=o['db'];c=o['client']
    trip,driver,pump,tool,payload=trip_setup(o,monkeypatch)
    a,b=trip.tappe;trip_id=trip.id
    assert c.get('/manager/trasporti/planner?week_start=2026-09-14').status_code==200
    assert [(r.origine_tappa_ordine,r.tappa.ordine) for r in trip.richieste_attrezzature]==[(0,1),(1,2)]
    o['actor'][0]=driver
    path=f'/driver/trasporti/viaggi/{trip_id}'
    assert c.get(path).status_code==200
    def scan(code, action='carico', stop=None, pickup=0):
        return c.post(path+'/scan',params={'action':action,'origine_tappa_ordine':pickup,**({'tappa_id':stop} if stop else {})},data={'qr_code':code})
    assert scan(pump.qr_code).status_code==400  # Never silently use stop A.
    assert scan(pump.qr_code,stop=999999).status_code==400
    assert scan(pump.qr_code,stop=a.id).json()['action']=='caricato'
    assert scan(pump.qr_code,stop=a.id).json()['action']=='caricato'
    assert scan(pump.qr_code,'scarico',b.id).json()['reason']=='tappa_errata'
    # Once physically loaded, editing cannot erase its assignment or recreate stops.
    o['actor'][0]=o['manager']
    c.post(f'/manager/trasporti/viaggi/{trip_id}/modifica',data=payload,follow_redirects=False)
    assert [t.id for t in db.get(TrasportoViaggio,trip_id).tappe]==[a.id,b.id]
    o['actor'][0]=driver
    for _ in range(2): assert scan(pump.qr_code,'scarico',a.id).json()['action']=='scaricato'
    assert db.query(MovimentoAttrezzatura).filter_by(viaggio_id=trip_id).count()==1
    assert scan(tool.codice,stop=b.id).json()['reason']=='fuori_lista'  # Pick up at A, not depot.
    assert scan(tool.codice,stop=b.id,pickup=1).json()['action']=='caricato'
    assert c.post(path+'/stato',data={'nuovo_stato':'completato'},follow_redirects=False).status_code==409
    db.rollback()  # Test fixture shares a session; real requests close/rollback it.
    for _ in range(2): assert scan(tool.qr_code,'scarico',b.id).json()['action']=='scaricato'
    movements=db.query(MovimentoAttrezzatura).filter_by(viaggio_id=trip_id).order_by(MovimentoAttrezzatura.id).all()
    assert len(movements)==2
    assert movements[0].destinazione_site_id==o['site'].id
    assert (movements[1].origine_site_id,movements[1].destinazione_site_id)==(o['site'].id,o['other'].id)
    assert db.get(Attrezzatura,tool.id).posizione_attuale==o['other'].name
    for _ in range(2): assert c.post(path+'/stato',data={'nuovo_stato':'completato'},follow_redirects=False).status_code==303
    assert db.query(MovimentoAttrezzatura).filter_by(viaggio_id=trip_id).count()==2
    outsider=User(email='other-driver@example.com',role=RoleEnum.driver,hashed_password='x',is_active=True)
    db.add(outsider);db.commit();o['actor'][0]=outsider
    assert scan(pump.qr_code,'scarico',a.id).status_code==404


def test_manifest_rejects_bad_quantity_and_pickup_without_creating_trip(operations,monkeypatch):
    o=operations;trip,driver,pump,tool,payload=trip_setup(o,monkeypatch)
    for changes in ({'quantita':['oops','1']},{'richiesta_origine_idx':['1','2']},
                    {'tappa_destinazione':['',f'site:{o["other"].id}']}):
        response=o['client'].post('/manager/trasporti/viaggi/nuovo',data={**payload,'codice_viaggio':'INVALID',**changes})
        assert response.status_code==400
        o['db'].rollback()
        assert o['db'].query(TrasportoViaggio).count()==1


def test_request_stock_only_changes_on_confirmed_delivery(operations):
    o=operations;db=o['db'];c=o['client']
    item=MagazzinoItem(codice='CONSUMABILE-01',nome='Articolo prova',quantita_disponibile=10,attivo=True)
    db.add(item);db.commit();item_id=item.id
    r=c.post('/capo/magazzino/richieste/nuova',data={'item_id':[item_id],'quantita':['4']},follow_redirects=False)
    assert r.status_code==303
    request=db.query(MagazzinoRichiesta).one();request_id=request.id;row_id=request.righe[0].id
    base=f'/manager/magazzino/richieste/{request_id}'
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==10
    assert c.post(base+'/evadi').status_code==403
    o['actor'][0]=o['manager']
    assert c.post(base+'/evadi',follow_redirects=False).status_code==303
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==10
    assert c.post(base+'/approva',follow_redirects=False).status_code==303
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==10
    assert c.post(base+'/evadi',data={f'quantita_da_evadere_{row_id}':'2'},follow_redirects=False).status_code==303
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==8
    assert db.get(MagazzinoRichiesta,request_id).stato==MagazzinoRichiestaStatusEnum.parziale
    c.post(base+'/approva',follow_redirects=False)
    assert db.get(MagazzinoRichiesta,request_id).stato==MagazzinoRichiestaStatusEnum.parziale
    for _ in range(2): assert c.post(base+'/evadi',follow_redirects=False).status_code==303
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==6
    assert db.query(MagazzinoMovimento).filter_by(item_id=item_id).count()==2


@pytest.mark.parametrize('quantity',['nan','inf','-3','1000'])
def test_invalid_stock_withdrawal_never_changes_balance(operations,quantity):
    o=operations;o['actor'][0]=o['manager'];db=o['db']
    item=MagazzinoItem(codice='STOCK-01',nome='Articolo prova',quantita_disponibile=10,attivo=True)
    db.add(item);db.commit();item_id=item.id
    o['client'].post(f'/manager/magazzino/items/{item_id}/scarico-rapido',data={'quantita':quantity,'location_id':f'site:{o["site"].id}'})
    db.expire_all()
    assert db.get(MagazzinoItem,item_id).quantita_disponibile==10
    assert db.query(MagazzinoMovimento).filter_by(item_id=item_id).count()==0


def test_vehicle_create_edit_preserves_zero_and_optional_values(operations):
    o=operations;o['actor'][0]=o['manager'];db=o['db'];c=o['client']
    ensure_model_columns(db.get_bind(),(Base.metadata,SQLModel.metadata))
    assert c.get('/manager/veicoli/nuovo').status_code==200
    data={'marca':'Marca prova','modello':'Camion','targa':'test123','km':'0','categoria':'camion',
          'visibile_trasporti':'on','assegnato_a_id':o['person'].id,'revisione_scadenza':'2027-01-31'}
    assert c.post('/manager/veicoli/nuovo',data=data,follow_redirects=False).status_code==303
    vehicle=db.query(Veicolo).one()
    assert vehicle.targa=='TEST123' and vehicle.km==0 and vehicle.visibile_trasporti
    assert o['person'].nome in c.get('/manager/veicoli').text
    url=f'/manager/veicoli/{vehicle.id}/modifica'
    response=c.get(url)
    assert 'name="km" type="number" value="0"' in response.text
    assert '2027-01-31' in response.text
    assert c.post(url,data={**data,'note':'Veicolo collaudo'},follow_redirects=False).status_code==303
    db.expire_all()
    assert db.query(Veicolo).one().note=='Veicolo collaudo'


def test_postgres_competing_withdrawals_cannot_oversell(operations, monkeypatch):
    """Two independent transactions request 8 units each from a balance of 10."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from sqlalchemy.orm import Session
    from main import app
    from routes.magazzino import manager_magazzino_scarico_rapido

    o=operations;engine=o['db'].get_bind()
    if engine.dialect.name!='postgresql':
        pytest.skip('Row locking is exercised by the PostgreSQL CI job')
    item=MagazzinoItem(codice='CONCURRENT',nome='Articolo concorrente',quantita_disponibile=10,attivo=True)
    o['db'].add(item);o['db'].commit()
    item_id,manager_id,site_id=item.id,o['manager'].id,o['site'].id
    monkeypatch.setattr('routes.magazzino._render_magazzino_items_list', lambda *a,**kw:HTMLResponse('Stock insufficiente',status_code=400))
    gate=Barrier(2)
    def withdraw():
        with Session(engine) as db:
            user=db.get(User,manager_id)
            request=Request({'type':'http','method':'POST','path':'/','query_string':b'',
                'scheme':'http','server':('testserver',80),'headers':[], 'app':app,'router':app.router})
            gate.wait(timeout=10)
            return manager_magazzino_scarico_rapido(item_id,request,quantita='8',note='',
                location_id=f'site:{site_id}',caposquadra_id=None,db=db,current_user=user).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(withdraw) for _ in range(2)]
        assert sorted(j.result(timeout=30) for j in jobs)==[303,400]
    o['db'].expire_all()
    assert o['db'].get(MagazzinoItem,item_id).quantita_disponibile==2
    assert o['db'].query(MagazzinoMovimento).filter_by(item_id=item_id).count()==1


def test_existing_transport_tables_upgrade_without_erasing_requests(operations, monkeypatch):
    from sqlalchemy import text
    from models import TrasportoRichiestaAttrezzatura
    o=operations
    trip_setup(o,monkeypatch)
    db=o['db'];engine=db.get_bind()
    db.commit();db.expunge_all()
    with engine.begin() as conn:
        for table in ('trasporto_richiesta_attrezzature','trasporto_attrezzature_viaggio'):
            conn.execute(text(f'ALTER TABLE {table} DROP COLUMN origine_tappa_ordine'))
    for _ in range(2):
        ensure_model_columns(engine,(Base.metadata,SQLModel.metadata))
    saved=db.query(TrasportoRichiestaAttrezzatura).all()
    assert len(saved)==2 and all(r.origine_tappa_ordine is None for r in saved)
    assert db.query(TrasportoViaggio).one().codice_viaggio=='TEST-A-B'

