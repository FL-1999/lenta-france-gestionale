from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import inspect
from sqlmodel import SQLModel
from database import ensure_model_columns
from models import (Base, Fiche, Supplier, SitePour, CostDelivery, CostInvoice, CostContract,
                    CostDeliveryLine, CostSharedExpense, SiteEconomicEntry, SiteEconomicAutoParams,
                    MagazzinoItem, MagazzinoMovimento, MagazzinoMovimentoTipoEnum,
                    PurchaseOrder, PurchaseOrderLine, PurchaseDelivery, PurchaseDeliveryLine)
from routes.site_costs import token
from services.site_costs import split_loads
from routes.economics import _compute_auto_material_costs
from test_operations import operations


def setup(o, qty=26):
    o['actor'][0]=o['manager']; db=o['db']
    s=Supplier(name='Centrale béton');db.add(s)
    f=Fiche(fiche_type='produzione',description='Test',created_by_id=o['manager'].id,site_id=o['site'].id,date=date(2026,9,20),data_getto=date(2026,9,24),
        numero_pannello=1,panel_name='P1',tipologia_scavo='paratia',metri_cubi_gettati=qty,
        larghezza_pannello=5,profondita_totale=10,altezza_pannello=.5)
    db.add(f);db.commit()
    return s,f,f'/manager/cantieri/{o["site"].id}/costi'


def post(o,base,action,body):
    return o['client'].post(base+'/'+action,json=body,headers={'x-csrf-token':token(o['manager'])})


def delivery_body(o,base,supplier,quantity=26,choice=None,reason=''):
    live=o['client'].get(base+'/data').json()['sources'][0]
    return dict(key=live['key'],fingerprint=live['fingerprint'],revision=0,supplier_id=supplier.id,
        lines=[dict(ticket='BL-001',quantity=quantity,unit_price=100,extra=25)],fiche_choice=choice,reason=reason)


def test_proposals_do_not_write_and_split_exactly(operations):
    o=operations;s,f,base=setup(o)
    first=o['client'].get(base+'/data');assert first.status_code==200,first.text
    assert first.json()['sources'][0]['date']=='2026-09-24'
    assert split_loads(26,7.5)==[7.5,7.5,7.5,3.5]
    assert split_loads(.3,.1)==[.1,.1,.1]
    assert o['db'].query(CostDelivery).count()==0
    ensure_model_columns(o['db'].get_bind(),(Base.metadata,SQLModel.metadata))
    assert o['client'].get(base).status_code==200


def test_difference_requires_choice_preserves_fiche_or_updates_it_and_blocks_stale(operations):
    o=operations;s,f,base=setup(o);body=delivery_body(o,base,s,25)
    assert post(o,base,'delivery',body).status_code==400
    assert o['db'].query(CostDelivery).count()==0 and f.metri_cubi_gettati==26
    body['fiche_choice']='keep';assert post(o,base,'delivery',body).status_code==400
    body['reason']='Volume fiche conservé pour contrôle interne'
    r=post(o,base,'delivery',body);assert r.status_code==200,r.text
    assert f.metri_cubi_gettati==26
    assert post(o,base,'delivery',body).status_code==409
    body.update(revision=1,fiche_choice='update')
    r=post(o,base,'delivery',body);assert r.status_code==200,r.text
    o['db'].expire_all();assert f.metri_cubi_gettati==25
    assert o['db'].query(CostDelivery).one().economic_entry.amount==2525
    assert o['client'].get(base+'/data').json()['deliveries'][0]['drift'] is False


def test_source_edit_and_active_curve_require_review(operations):
    o=operations;s,f,base=setup(o);body=delivery_body(o,base,s,25,'update')
    f.metri_cubi_gettati=27;o['db'].commit()
    assert post(o,base,'delivery',body).status_code==409
    body=delivery_body(o,base,s,25,'update');f.courbe_beton_active=True;o['db'].commit()
    body=delivery_body(o,base,s,25,'update')
    assert post(o,base,'delivery',body).status_code==400
    assert o['db'].query(CostDelivery).count()==0 and f.metri_cubi_gettati==27


@pytest.mark.parametrize('kind',['angle','joint'])
def test_group_one_register_and_atomic_fiche_updates(operations,kind):
    from test_site_pours import setup as setup_plan,fiche
    o=operations;site_base=setup_plan(o,('P7A','P7B') if kind=='angle' else ('P1','P2'))
    group=o['client'].post(site_base+'/getti',json={'numbers':[1,2],'kind':kind,'confirm_net':True}).json()
    assert fiche(o,1,40 if kind=='angle' else 8).status_code==303
    if kind=='joint':
        assert fiche(o,2,9).status_code==303
        group=o['client'].get(site_base+'/getti').json()[0]
        assert o['client'].put(site_base+f'/getti/{group["id"]}',json={'revision':group['revision'],'total_m3':40,'cast_date':'2026-09-24','confirm':True}).status_code==200
    supplier=Supplier(name='Centrale');o['db'].add(supplier);o['db'].commit();base=site_base+'/costi'
    sources=o['client'].get(base+'/data').json()['sources'];assert len(sources)==1
    body=delivery_body(o,base,supplier,32,'update')
    r=post(o,base,'delivery',body);assert r.status_code==200,r.text
    o['db'].expire_all();group=o['db'].query(SitePour).one();assert group.total_m3==32
    assert sum(f.metri_cubi_gettati for f in o['db'].query(Fiche))==32
    if kind=='joint':assert [f.metri_cubi_gettati for f in o['db'].query(Fiche).order_by(Fiche.numero_pannello)]==[20,12]


def test_invoice_two_sites_replaces_provisional_locks_tickets_and_can_be_corrected(operations):
    o=operations;s,f,base=setup(o);db=o['db']
    assert post(o,base,'delivery',delivery_body(o,base,s)).status_code==200
    other=Fiche(fiche_type='produzione',description='Test',created_by_id=o['manager'].id,site_id=o['other'].id,date=date(2026,9,24),data_getto=date(2026,9,24),numero_pannello=1,tipologia_scavo='paratia',metri_cubi_gettati=10)
    db.add(other);db.commit();base2=f'/manager/cantieri/{o["other"].id}/costi'
    assert post(o,base2,'delivery',delivery_body(o,base2,s,10)).status_code==200
    eligible=o['client'].get(base+'/data').json()['eligible'];assert len(eligible)==2
    data={'supplier_id':s.id,'number':'FACT-9','date':'2026-09-30','total':3650,
        'lines':[dict(id=l['id'],revision=l['revision'],quantity=l['quantity'],unit_price=100,extra=25) for l in eligible]}
    data['total']=1;assert post(o,base,'invoice',data).status_code==400
    assert db.query(CostInvoice).count()==0
    data['total']=4010
    for l in data['lines']:l['unit_price']=110
    r=post(o,base,'invoice',data);assert r.status_code==200,r.text
    db.expire_all();assert sum(e.amount for e in db.query(SiteEconomicEntry))==4010
    assert post(o,base,'invoice',data).status_code==409
    assert o['client'].get(base+'/data').json()['eligible']==[]
    body=delivery_body(o,base,s);body['revision']=2
    assert post(o,base,'delivery',body).status_code==409
    invoice=db.query(CostInvoice).one()
    assert post(o,base,'cancel-invoice',{'id':invoice.id,'revision':1,'reason':'Correction prix'}).status_code==200
    db.expire_all();assert sum(e.amount for e in db.query(SiteEconomicEntry))==3650
    data['lines']=[dict(id=l['id'],revision=l['revision'],quantity=l['quantity'],unit_price=110,extra=25) for l in o['client'].get(base+'/data').json()['eligible']]
    assert post(o,base,'invoice',data).status_code==200
    assert db.query(CostInvoice).count()==1


def test_invoice_quantity_mismatch_needs_reason_does_not_change_fiche(operations):
    o=operations;s,f,base=setup(o);assert post(o,base,'delivery',delivery_body(o,base,s)).status_code==200
    line=o['client'].get(base+'/data').json()['eligible'][0]
    data=dict(supplier_id=s.id,number='F1',date='2026-09-30',total=2700,
        lines=[dict(id=line['id'],revision=line['revision'],quantity=27,unit_price=100,extra=0)])
    assert post(o,base,'invoice',data).status_code==400
    data['lines'][0]['reason']='Frais exprimés en volume facturé';assert post(o,base,'invoice',data).status_code==200
    assert f.metri_cubi_gettati==26


def test_no_double_auto_cost_no_edit_from_legacy_and_unverify(operations):
    o=operations;s,f,base=setup(o);db=o['db']
    f2=Fiche(fiche_type='produzione',description='Test',created_by_id=o['manager'].id,site_id=o['site'].id,date=f.date,data_getto=f.data_getto,numero_pannello=2,tipologia_scavo='paratia',metri_cubi_gettati=10)
    db.add(f2);db.commit()
    assert post(o,base,'delivery',delivery_body(o,base,s)).status_code==200
    db.expire_all();entry=db.query(SiteEconomicEntry).one();site=o['site']
    params=SiteEconomicAutoParams(costo_cemento_mc=100,manual_material_entries_override_auto=True)
    rows,daily,total=_compute_auto_material_costs(site,params,date(2026,9,1),date(2026,9,30),[entry])
    assert total==1000 and [r['fiche_id'] for r in rows]==[f2.id]
    assert o['client'].delete(f'/manager/cantieri/{site.id}/economics/entries/{entry.id}').status_code==409
    d=db.query(CostDelivery).one()
    assert post(o,base,'unverify-delivery',dict(id=d.id,revision=d.revision,reason='Erreur de saisie')).status_code==200
    assert db.query(CostDelivery).count()==db.query(SiteEconomicEntry).count()==0
    assert f.metri_cubi_gettati==26


def test_direct_and_warehouse_sources_no_double_movement_and_prices_optional(operations):
    o=operations;s,f,base=setup(o);db=o['db'];db.delete(f)
    item=MagazzinoItem(nome='Sacs',unita_misura='pz',quantita_disponibile=100,costo_unitario=None);db.add(item);db.flush()
    order=PurchaseOrder(order_number='COST-1',supplier_id=s.id,delivery_type='SITE',delivery_site_id=o['site'].id)
    order.lines=[PurchaseOrderLine(description='Sacs',magazzino_item_id=item.id,qty_ordered=100)]
    db.add(order);db.flush()
    d=PurchaseDelivery(order_id=order.id,delivery_number='BL-1',confirmed=True,delivery_type='SITE',delivery_site_id=o['site'].id,delivery_date=date(2026,9,24))
    d.lines=[PurchaseDeliveryLine(order_line_id=order.lines[0].id,qty_delivered=100)];db.add(d);db.flush()
    db.add_all([MagazzinoMovimento(item_id=item.id,tipo=MagazzinoMovimentoTipoEnum.scarico,quantita=100,cantiere_id=o['site'].id,purchase_delivery_id=d.id),MagazzinoMovimento(item_id=item.id,tipo=MagazzinoMovimentoTipoEnum.scarico,quantita=20,cantiere_id=o['site'].id)])
    db.commit();sources=o['client'].get(base+'/data').json()['sources'];assert len(sources)==2
    for source in sources:
        body=dict(key=source['key'],fingerprint=source['fingerprint'],revision=0,supplier_id=s.id if source['kind']=='direct' else None,lines=[dict(ticket=source['ticket'],quantity=source['quantity'],unit_price=None,extra=0)])
        assert post(o,base,'delivery',body).status_code==200
    assert item.quantita_disponibile==100 and db.query(MagazzinoMovimento).count()==2
    assert len(o['client'].get(base+'/data').json()['eligible'])==1
    assert all(l.unit_price is None for l in db.query(CostDeliveryLine))


def test_contract_version_snapshot_and_shared_reallocation(operations):
    o=operations;s,f,base=setup(o);db=o['db']
    contract=dict(supplier_id=s.id,name='C30',price=100,capacity=7.5,surcharge='fixed',rate=25,planned=1000)
    assert post(o,base,'contract',contract).status_code==200
    c=db.query(CostContract).one();body=delivery_body(o,base,s);body.update(contract_id=c.id,contract_revision=1)
    assert post(o,base,'delivery',body).status_code==200
    contract.update(id=c.id,revision=1,price=120);assert post(o,base,'contract',contract).status_code==200
    db.expire_all();assert db.query(CostDelivery).one().contract['price']==100
    data=dict(request_key='cost-test-shared',description='Transport commun',date='2026-09-24',total=900,allocations=[dict(site_id=o['site'].id,amount=600),dict(site_id=o['other'].id,amount=300)])
    assert post(o,base,'shared',data).status_code==200
    assert post(o,base,'shared',data).status_code==409
    e=db.query(CostSharedExpense).one();data.update(id=e.id,revision=1)
    data['allocations'][0]['amount']=1000;assert post(o,base,'shared',data).status_code==400
    data['allocations'][0]['amount']=500;assert post(o,base,'shared',data).status_code==200
    db.expire_all();assert sum(a.amount for a in e.allocations)==800
    assert db.query(SiteEconomicEntry).count()==3
    assert post(o,base,'shared',data).status_code==409


@pytest.mark.parametrize('value',['NaN','Infinity','-1','0','100000000000'])
def test_invalid_quantity_rejected_atomically(operations,value):
    o=operations;s,f,base=setup(o);body=delivery_body(o,base,s,value,'update')
    assert post(o,base,'delivery',body).status_code==400
    assert o['db'].query(CostDelivery).count()==0 and f.metri_cubi_gettati==26


def test_permissions_and_csrf(operations):
    o=operations;s,f,base=setup(o);body=delivery_body(o,base,s)
    assert o['client'].post(base+'/delivery',json=body).status_code==403
    assert o['client'].post(base+'/delivery',json=body,headers={'x-csrf-token':token(o['manager']),'origin':'https://evil.invalid'}).status_code==403
    o['actor'][0]=o['capo']
    assert o['client'].get(base+'/data').status_code==403
    assert post(o,base,'delivery',body).status_code==403


def test_site_deletion_preserves_company_invoice_without_fk_failure(operations):
    from services.site_deletion import delete_site_records
    o=operations;s,f,base=setup(o);db=o['db']
    assert post(o,base,'delivery',delivery_body(o,base,s)).status_code==200
    l=o['client'].get(base+'/data').json()['eligible'][0]
    assert post(o,base,'invoice',dict(supplier_id=s.id,number='INV1',date='2026-09-24',total=2625,lines=[dict(id=l['id'],revision=1,quantity=26,unit_price=100,extra=25)])).status_code==200
    delete_site_records(db,o['site']);db.commit();db.expire_all()
    assert db.query(CostInvoice).count()==1
    d=db.query(CostDelivery).one();assert d.site_id is None and d.site_name=='Cantiere assegnato'

