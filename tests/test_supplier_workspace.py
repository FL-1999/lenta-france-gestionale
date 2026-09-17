from datetime import date
from test_operations import operations
from models import Supplier, SupplierContact, PurchaseOrder


def test_supplier_code_correction_updates_search_and_future_orders_only(operations):
    from test_purchasing_workflows import setup, order
    from models import SupplierArticle, PurchaseOrderLine, MagazzinoItem, AuditLog
    db,c,s,item,cat=setup(operations)
    assert order(operations,s,item,cat).status_code==303
    article=db.query(SupplierArticle).one();line=db.query(PurchaseOrderLine).one()
    url=f'/manager/fornitori/{s.id}/articoli/{article.id}/codice'
    assert c.get(url).status_code==200
    item_code=item.codice
    r=c.post(url,data={'code':'  CORRETTO-13  ','expected_code':'678'},follow_redirects=False)
    assert r.status_code==303,r.text
    db.refresh(article);db.refresh(line);db.refresh(item)
    assert article.codice=='CORRETTO-13' and line.codice=='678'
    assert article.magazzino_item_id==line.magazzino_item_id==item.id
    assert item.codice==item_code and item.quantita_disponibile==0
    assert 'Bullone M12' in c.get('/manager/magazzino?q=CORRETTO-13').text
    new=c.get(f'/manager/ordini/nuovo?supplier_id={s.id}&item_id={item.id}&supplier_article_id={article.id}')
    assert new.status_code==200 and 'CORRETTO-13' in new.text
    page=c.get(r.headers['location'])
    assert page.status_code==200 and 'Codice fornitore aggiornato' in page.text
    assert page.context['purchased_materials'][0]['codes']==['678']
    assert db.query(AuditLog).filter_by(action='SUPPLIER_ARTICLE_CODE_CHANGED').count()==1
    assert order(operations,s,item,cat,codice=['CORRETTO-13'],magazzino_item_id=['']).status_code==303
    latest=db.query(PurchaseOrderLine).order_by(PurchaseOrderLine.id.desc()).first()
    assert latest.codice=='CORRETTO-13' and latest.magazzino_item_id==item.id
    assert db.query(SupplierArticle).count()==1


def test_supplier_code_validation_duplicates_stale_and_permissions(operations):
    from test_purchasing_workflows import setup
    from models import SupplierArticle
    db,c,s,item,cat=setup(operations)
    other=Supplier(name='Altro',is_active=True);db.add(other);db.flush()
    a=SupplierArticle(supplier_id=s.id,codice='AAA',magazzino_item_id=item.id)
    db.add_all([a,SupplierArticle(supplier_id=s.id,codice='BBB'),SupplierArticle(supplier_id=other.id,codice='CCC')]);db.commit()
    url=f'/manager/fornitori/{s.id}/articoli/{a.id}/codice'
    for code,status in [('',400),('x'*101,400),('bbb',409)]:
        r=c.post(url,data={'code':code,'expected_code':'AAA'})
        assert r.status_code==status;db.refresh(a);assert a.codice=='AAA'
    assert c.post(url,data={'code':'NEW','expected_code':'STALE'}).status_code==409
    assert c.post(f'/manager/fornitori/{other.id}/articoli/{a.id}/codice',data={'code':'NEW','expected_code':'AAA'}).status_code==404
    assert c.post(url,data={'code':'CCC','expected_code':'AAA'},follow_redirects=False).status_code==303
    operations['actor'][0]=operations['capo']
    assert c.get(url).status_code==403
    assert c.post(url,data={'code':'BAD','expected_code':'CCC'}).status_code==403


def test_supplier_materials_separate_vendor_orders_confirmed_receipts_and_catalog(operations):
    from models import (MagazzinoItem,SupplierArticle,PurchaseOrderLine,PurchaseDelivery,PurchaseDeliveryLine)
    db=operations['db'];c=operations['client'];operations['actor'][0]=operations['manager']
    s=Supplier(name='Fornitore A');other=Supplier(name='Fornitore B')
    item=MagazzinoItem(nome='Gancio',unita_misura='pz',quantita_disponibile=999,attivo=True)
    catalog=MagazzinoItem(nome='Mai acquistato',attivo=True)
    db.add_all([s,other,item,catalog]);db.flush()
    db.add(SupplierArticle(supplier_id=s.id,codice='CATALOG',magazzino_item_id=catalog.id))
    for n,vendor in enumerate([s,s,other]):
        po=PurchaseOrder(supplier_id=vendor.id,order_number=f'MATERIAL-{n}');db.add(po);db.flush()
        quantities=[10,4] if n==0 else [6] if n==1 else [100]
        for j,qty in enumerate(quantities):
            line=PurchaseOrderLine(order_id=po.id,magazzino_item_id=item.id,codice=f'CODE-{n}',qty_ordered=qty)
            db.add(line);db.flush()
            receipts=[4,2] if n==0 and j==0 else [1] if n==0 else [qty]
            for k,received in enumerate(receipts):
                delivery=PurchaseDelivery(order_id=po.id,delivery_number=f'BL-{n}-{j}-{k}',confirmed=True,delivery_type='PICKUP')
                db.add(delivery);db.flush();db.add(PurchaseDeliveryLine(delivery_id=delivery.id,order_line_id=line.id,qty_delivered=received))
            draft=PurchaseDelivery(order_id=po.id,delivery_number=f'DRAFT-{j}',confirmed=False,delivery_type='PICKUP')
            db.add(draft);db.flush();db.add(PurchaseDeliveryLine(delivery_id=draft.id,order_line_id=line.id,qty_delivered=500))
    unlinked_order=PurchaseOrder(supplier_id=s.id,order_number='OLD-UNLINKED');db.add(unlinked_order);db.flush()
    db.add(PurchaseOrderLine(order_id=unlinked_order.id,codice='OLD',description='Storico libero',qty_ordered=3));db.commit()
    page=c.get(f'/manager/fornitori/{s.id}');assert page.status_code==200
    materials=page.context['purchased_materials'];assert len(materials)==2
    data=next(m for m in materials if m['item'])
    assert (data['ordered'],data['received'],data['remaining'],data['order_count'])==(20,13,7,2)
    assert data['unit']=='pz' and data['codes']==['CODE-0','CODE-1']
    unlinked=next(m for m in materials if not m['item'])
    assert unlinked['ordered']==3 and unlinked['unit'] is None
    assert 'MATERIAL-2' not in page.text
    db.refresh(item);assert item.quantita_disponibile==999


def test_supplier_search_status_and_literal_search(operations):
    o=operations; db=o['db']; c=o['client']; o['actor'][0]=o['manager']
    active=Supplier(name='Acme',city='Nice',is_active=True)
    inactive=Supplier(name='Old company',is_active=False)
    literal=Supplier(name='100% service',is_active=True)
    db.add_all([active,inactive,literal]);db.flush()
    db.add_all([SupplierContact(supplier_id=active.id,name='Lucie Martin',email='lucie@example.com'),
                SupplierContact(supplier_id=active.id,name='Lucie Second',email='second@example.com')]);db.commit()
    for q in ['Lucie','lucie@example.com','Nice']:
        r=c.get('/manager/fornitori',params={'q':q})
        assert r.status_code==200
        assert [s.id for s in r.context['suppliers']]==[active.id]
        assert r.context['counts']=={'all':1,'active':1,'inactive':0}
    r=c.get('/manager/fornitori',params={'q':'%'})
    assert [s.id for s in r.context['suppliers']]==[literal.id]
    r=c.get('/manager/fornitori?stato=inactive')
    assert [s.id for s in r.context['suppliers']]==[inactive.id]
    assert 'supplier-order-link' not in r.text
    profile=c.get(f'/manager/fornitori/{inactive.id}')
    assert f'ordini/nuovo?supplier_id={inactive.id}' not in profile.text
    assert f'fornitori/{inactive.id}/toggle' in profile.text


def test_supplier_pages_and_full_order_history(operations):
    o=operations; db=o['db'];c=o['client'];o['actor'][0]=o['manager']
    db.add_all(Supplier(name=f'Supplier {i:03}',is_active=True) for i in range(32));db.commit()
    first=c.get('/manager/fornitori?q=Supplier&stato=active')
    assert len(first.context['suppliers'])==30
    assert 'q=Supplier&amp;stato=active&amp;page=2' in first.text
    second=c.get('/manager/fornitori?q=Supplier&stato=active&page=2')
    assert len(second.context['suppliers'])==2
    supplier=db.query(Supplier).filter_by(name='Supplier 000').one()
    other=db.query(Supplier).filter_by(name='Supplier 001').one()
    for i in range(55):
        db.add(PurchaseOrder(supplier_id=supplier.id,order_number=f'HISTORY-{i:03}',order_date=date.today(),
                            requester_user_id=o['manager'].id,order_kind='warehouse',delivery_type='PICKUP'))
    db.add(PurchaseOrder(supplier_id=other.id,order_number='OTHER-SUPPLIER',order_date=date.today(),
                        requester_user_id=o['manager'].id,order_kind='warehouse',delivery_type='PICKUP'))
    db.commit()
    seen=[]
    for page in [1,2,3]:
        r=c.get(f'/manager/fornitori/{supplier.id}?order_page={page}')
        assert r.status_code==200
        seen += [x.order_number for x in r.context['supplier_orders']]
        assert 'OTHER-SUPPLIER' not in r.text
    assert len(seen)==len(set(seen))==55 and 'HISTORY-000' in seen
    assert c.get(f'/manager/fornitori/{supplier.id}?order_page=-5').status_code==200
    o['actor'][0]=o['outsider']
    assert c.get('/manager/fornitori').status_code==403
    assert c.get(f'/manager/fornitori/{supplier.id}').status_code==403
