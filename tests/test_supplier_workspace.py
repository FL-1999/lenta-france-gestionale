from datetime import date
from test_operations import operations
from models import Supplier, SupplierContact, PurchaseOrder


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
