from datetime import date
import pytest
from sqlalchemy import select
from test_operations import operations
from models import (Supplier, SupplierContact, SupplierArticle, MagazzinoItem, MagazzinoCategoria,
                    PurchaseOrder, PurchaseOrderLine, PurchaseDelivery, MagazzinoMovimento)


def setup(o):
    o['actor'][0] = o['manager']
    db = o['db']
    supplier = Supplier(name='Mario', email='ordini@example.com', is_active=True)
    category = MagazzinoCategoria(nome='Bulloneria',slug='bulloneria',attiva=True)
    item = MagazzinoItem(nome='Bullone M12', quantita_disponibile=0, attivo=True, categoria=category)
    db.add_all([supplier,item]); db.commit()
    return db, o['client'], supplier, item, category


def order(o, supplier, item, category, **extras):
    return o['client'].post('/manager/ordini/nuovo',data={
        'supplier_id':supplier.id,'order_date':'2026-09-16','requester_user_id':o['manager'].id,
        'order_kind':'warehouse','category_mode':'existing','warehouse_category_id':category.id,
        'codice':['678'],'description':['Bullone M12'],'qty_ordered':['10'],
        'magazzino_item_id':[str(item.id)], **extras},follow_redirects=False)


def receive(c, po, number, qty, **extras):
    return c.post(f'/manager/ordini/{po.id}/bolle/nuova',data={
        'delivery_number':number,'delivery_date':'2026-09-16','order_line_id':[po.lines[0].id],
        'qty_delivered':[str(qty)],'confirm_now':'true',**extras},follow_redirects=False)


def test_one_stock_item_multiple_supplier_codes_and_contacts(operations):
    db,c,s,item,cat=setup(operations)
    other=Supplier(name='Gianluigi',is_active=True);db.add(other);db.commit()
    for supplier,code in [(s,'678'),(other,'967')]:
        assert c.post(f'/manager/magazzino/items/{item.id}/fornitori',data={'supplier_id':supplier.id,'code':code},follow_redirects=False).status_code==303
    for name in ['Acquisti','Consegne']:
        assert c.post(f'/manager/fornitori/{s.id}/referenti',data={'name':name,'email':'contatto@example.com','active':'true'},follow_redirects=False).status_code==303
    assert db.query(SupplierArticle).count()==2 and db.query(MagazzinoItem).count()==1
    assert db.query(SupplierContact).count()==2
    assert len(item.codice)==6 and item.codice.isdigit()
    assert c.get(f'/manager/fornitori/{s.id}').status_code==200
    card=c.get(f'/manager/magazzino/items/{item.id}/scheda');assert card.status_code==200,card.text
    assert '678' in card.text and '967' in card.text
    contact=db.query(SupplierContact).first()
    assert c.post(f'/manager/fornitori/{other.id}/referenti',data={'contact_id':contact.id,'name':'Hijack'}).status_code==404
    db.rollback()
    item2=MagazzinoItem(nome='Different',attivo=True);db.add(item2);db.commit()
    assert c.post(f'/manager/magazzino/items/{item2.id}/fornitori',data={'supplier_id':s.id,'code':'678'}).status_code==409
    db.rollback()
    operations['actor'][0]=operations['capo']
    assert c.post(f'/manager/magazzino/items/{item.id}/fornitori',data={'supplier_id':s.id,'code':'999'}).status_code==403


def test_partial_delivery_draft_edit_close_and_replay(operations):
    db,c,s,item,cat=setup(operations)
    contact=SupplierContact(supplier_id=s.id,name='Maria',email='maria@example.com',is_active=True);db.add(contact)
    db.add(SupplierArticle(supplier_id=s.id,codice='678',magazzino_item_id=item.id));db.commit()
    result=order(operations,s,item,cat,magazzino_item_id=[''],supplier_contact_id=contact.id)
    assert result.status_code==303,result.text
    po=db.query(PurchaseOrder).one(); assert po.lines[0].magazzino_item_id==item.id
    assert po.contact_email_override=='maria@example.com'
    assert c.get(result.headers['location']).status_code==200
    assert receive(c,po,'BL-1',4,confirm_now='false').status_code==303
    db.refresh(item);assert item.quantita_disponibile==0
    delivery=db.query(PurchaseDelivery).one()
    assert c.get(f'/manager/ordini/bolle/{delivery.id}/modifica').status_code==200
    assert receive(c,po,'BL-1',3,delivery_id=delivery.id,confirm_now='false').status_code==303
    db.refresh(delivery);assert delivery.lines[0].qty_delivered==3
    confirm=f'/manager/ordini/bolle/{delivery.id}/conferma'
    assert c.post(confirm,follow_redirects=False).status_code==303
    assert c.post(confirm,follow_redirects=False).status_code==303
    db.refresh(item);db.refresh(po);assert item.quantita_disponibile==3 and po.status=='PARZIALE'
    assert receive(c,po,'BL-2',7).status_code==303
    assert receive(c,po,'BL-2',7).status_code==303
    db.refresh(item);db.refresh(po);assert item.quantita_disponibile==10 and po.status=='CHIUSO'
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).count()==2
    page=c.get(f'/manager/ordini/{po.id}');assert page.status_code==200 and 'BL-2' in page.text
    assert c.get(f'/manager/ordini/bolle/{delivery.id}/modifica').status_code==409
    for path in ['/manager/ordini?status=tutti','/manager/ordini?status=chiuso']:
        response=c.get(path);assert response.status_code==200 and f'href="http://testserver/manager/ordini/{po.id}"' in response.text


@pytest.mark.parametrize('qty',['11','-1','nan','inf','0'])
def test_invalid_receipts_never_change_stock(operations,qty):
    db,c,s,item,cat=setup(operations)
    assert order(operations,s,item,cat).status_code==303
    po=db.query(PurchaseOrder).one()
    result=receive(c,po,'INVALID',qty)
    assert result.status_code==200,result.text
    assert db.query(PurchaseDelivery).count()==0
    db.refresh(item);assert item.quantita_disponibile==0


def test_two_drafts_cannot_overreceive_at_confirmation(operations):
    db,c,s,item,cat=setup(operations);assert order(operations,s,item,cat).status_code==303
    po=db.query(PurchaseOrder).one()
    for n in ['A','B']: assert receive(c,po,n,8,confirm_now='false').status_code==303
    deliveries=db.query(PurchaseDelivery).order_by(PurchaseDelivery.id).all()
    for d in deliveries: c.post(f'/manager/ordini/bolle/{d.id}/conferma',follow_redirects=False)
    db.refresh(item);assert item.quantita_disponibile==8
    db.refresh(deliveries[1]);assert not deliveries[1].confirmed


def test_automatic_codes_preserve_legacy_and_new_item_from_order(operations):
    db,c,s,item,cat=setup(operations)
    legacy=MagazzinoItem(nome='Vecchio',codice='000002',attivo=True);db.add(legacy);db.commit()
    new=MagazzinoItem(nome='Nuovo',attivo=True);db.add(new);db.commit()
    assert new.codice=='000003' and legacy.codice=='000002'
    assert order(operations,s,item,cat,magazzino_item_id=['__new__'],codice=['NEW']).status_code==303
    po=db.query(PurchaseOrder).one();assert po.lines[0].magazzino_item_id!=item.id
    created=db.get(MagazzinoItem,po.lines[0].magazzino_item_id)
    assert created.codice=='000004' and created.quantita_disponibile==0
    assert c.get('/manager/magazzino/nuovo').status_code==200
    response=c.post('/manager/magazzino/nuovo',data={'nome':'Creato da scheda','attivo':'true'},follow_redirects=False)
    assert response.status_code==303,response.text
    assert c.get(response.headers['location']).status_code==200


def test_legacy_unlinked_order_can_be_repaired_before_receipt(operations):
    db,c,s,item,cat=setup(operations)
    po=PurchaseOrder(order_number='LEGACY',supplier_id=s.id,order_date=date.today(),requester_user_id=operations['manager'].id,order_kind='warehouse',delivery_type='PICKUP')
    po.lines=[PurchaseOrderLine(description='Bullone storico',codice='OLD',qty_ordered=5)]
    db.add(po);db.commit()
    assert c.get(f'/manager/ordini/{po.id}').status_code==200
    response=c.post(f'/manager/ordini/{po.id}/righe/{po.lines[0].id}/articolo',data={'item_id':item.id},follow_redirects=False)
    assert response.status_code==303
    assert receive(c,po,'OLD-BL',5).status_code==303
    assert c.post(f'/manager/ordini/{po.id}/elimina',follow_redirects=False).status_code==303
    assert db.get(PurchaseOrder,po.id) is not None
    assert c.post(f'/manager/fornitori/{s.id}/elimina',data={'force':'1'},follow_redirects=False).status_code==303
    assert db.get(Supplier,s.id) is not None
    db.refresh(item);assert item.quantita_disponibile==5


def test_supplier_catalog_column_upgrade_preserves_historical_rows(operations):
    from sqlalchemy import inspect, text
    from database import ensure_model_columns
    from models import Base
    db,c,s,item,cat=setup(operations)
    db.add(SupplierArticle(supplier_id=s.id,codice='HIST',descrizione='Da conservare'));db.commit()
    engine=db.get_bind()
    # Simulate the exact pre-release table without the new nullable link.
    with engine.begin() as conn:
        conn.execute(text('DROP INDEX IF EXISTS ix_supplier_articles_magazzino_item_id'))
        if engine.dialect.name == 'sqlite':
            conn.execute(text('ALTER TABLE supplier_articles RENAME TO old_supplier_articles'))
            conn.execute(text('CREATE TABLE supplier_articles AS SELECT id,supplier_id,codice,descrizione,unita,ultimo_prezzo,last_used_at,usi,created_at,updated_at FROM old_supplier_articles'))
            conn.execute(text('DROP TABLE old_supplier_articles'))
        else:
            conn.execute(text('ALTER TABLE supplier_articles DROP COLUMN magazzino_item_id'))
    for _ in range(2): ensure_model_columns(engine,(Base.metadata,))
    db.expire_all()
    article=db.query(SupplierArticle).filter_by(codice='HIST').one()
    assert article.descrizione=='Da conservare' and article.magazzino_item_id is None


def test_parallel_postgres_confirmations_do_not_double_stock(operations):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from routes.ordini import _confirm_purchase_delivery
    from models import User
    db,c,s,item,cat=setup(operations)
    engine=db.get_bind()
    if engine.dialect.name!='postgresql': pytest.skip('Real row locks require PostgreSQL')
    assert order(operations,s,item,cat).status_code==303
    po=db.query(PurchaseOrder).one();assert receive(c,po,'CONCURRENT',10,confirm_now='false').status_code==303
    delivery_id=db.query(PurchaseDelivery).one().id
    order_id,manager_id,item_id=po.id,operations['manager'].id,item.id
    db.commit();barrier=Barrier(2)
    def confirm():
        with Session(engine) as worker:
            user=worker.get(User,manager_id);barrier.wait(timeout=10)
            locked=worker.query(PurchaseOrder).filter_by(id=order_id).with_for_update().one()
            _confirm_purchase_delivery(worker,locked,worker.get(PurchaseDelivery,delivery_id),user)
            worker.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(confirm) for _ in range(2)]
        for job in jobs: job.result(timeout=20)
    db.expire_all();assert db.get(MagazzinoItem,item_id).quantita_disponibile==10
    assert db.query(MagazzinoMovimento).filter_by(purchase_delivery_id=delivery_id).count()==1
