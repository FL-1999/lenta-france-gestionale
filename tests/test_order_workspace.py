from datetime import date
from test_operations import operations
from models import Supplier, PurchaseOrder, PurchaseOrderLine, PurchaseDelivery, PurchaseDeliveryLine


def seed_orders(db, manager_id, site_id):
    supplier = Supplier(name='Riviera Fournitures', email='achats@example.com', is_active=True)
    other = Supplier(name='Secondo fornitore', is_active=False)
    db.add_all([supplier, other]); db.flush()
    rows = []
    for number, state, sid, kind, description in [
        ('2026-101', 'aperto', supplier.id, 'warehouse', 'Ganci e accessori'),
        ('2026-102', 'parziale', supplier.id, 'closed', 'Materiale per cantiere'),
        ('2026-103', 'CHIUSO', supplier.id, 'warehouse', 'Rifornimento completato'),
        ('2026-104', 'completato', other.id, 'warehouse', 'Storico 100%')]:
        order = PurchaseOrder(order_number=number, status=state, supplier_id=sid,
            requester_user_id=manager_id, order_date=date(2026,9,17), order_kind=kind,
            description=description, site_id=site_id if kind == 'closed' else None, delivery_type='PICKUP')
        db.add(order); db.flush()
        line = PurchaseOrderLine(order_id=order.id, qty_ordered=10, description='Articolo di prova')
        db.add(line); db.flush()
        if state in ['parziale', 'CHIUSO', 'completato']:
            delivery = PurchaseDelivery(order_id=order.id, delivery_number='BL-'+number, confirmed=True, delivery_type='PICKUP')
            db.add(delivery); db.flush()
            db.add(PurchaseDeliveryLine(delivery_id=delivery.id, order_line_id=line.id, qty_delivered=4 if state == 'parziale' else 10))
        if state == 'parziale':
            draft = PurchaseDelivery(order_id=order.id, delivery_number='DRAFT', confirmed=False, delivery_type='PICKUP')
            db.add(draft); db.flush()
            db.add(PurchaseDeliveryLine(delivery_id=draft.id, order_line_id=line.id, qty_delivered=6))
        rows.append(order)
    db.commit()
    return supplier, other, rows


def test_order_directory_states_filters_and_confirmed_progress(operations):
    o=operations; o['actor'][0]=o['manager']; c=o['client']; db=o['db']
    supplier, other, rows=seed_orders(db,o['manager'].id,o['site'].id)
    r=c.get('/manager/ordini'); assert r.status_code==200
    assert r.context['counts']=={'tutti':4,'in_corso':2,'parziale':1,'chiuso':2}
    assert {x.id for x in r.context['orders']}=={rows[0].id,rows[1].id}
    assert r.context['completion_map'][rows[1].id]==40
    assert r.context['receipt_map'][rows[1].id]==1
    closed=c.get('/manager/ordini/chiusi')
    assert {x.id for x in closed.context['orders']}=={rows[2].id,rows[3].id}
    filtered=c.get('/manager/ordini',params={'status':'tutti','supplier_id':supplier.id,'kind':'closed','date_from':'2026-09-17','q':'Materiale'})
    assert [x.id for x in filtered.context['orders']]==[rows[1].id]
    assert filtered.context['counts']['tutti']==1
    link=str(filtered.context['status_links']['chiuso'])
    assert f'supplier_id={supplier.id}' in link and 'q=Materiale' in link and 'kind=closed' in link
    assert c.get('/manager/ordini?status=tutti&supplier_id=0&q=%25').context['result_count']==1
    assert c.get('/manager/ordini?status=tutti&date_to=2026-09-16').context['result_count']==0
    profile=c.get(f'/manager/fornitori/{supplier.id}')
    assert profile.context['completion_map'][rows[1].id]==40
    assert 'Filtra gli ordini' in profile.text and 'order-row' in profile.text
    o['actor'][0]=o['outsider']
    assert c.get('/manager/ordini').status_code==403
    assert c.get('/manager/ordini/chiusi').status_code==403


def test_order_pagination_retains_filters_and_stable_order(operations):
    o=operations; o['actor'][0]=o['manager']; c=o['client']; db=o['db']
    supplier, other, rows=seed_orders(db,o['manager'].id,o['site'].id)
    for i in range(25):
        db.add(PurchaseOrder(order_number=f'EXTRA-{i:02}', supplier_id=supplier.id,
            requester_user_id=o['manager'].id, order_date=date(2026,9,17), status='aperto', delivery_type='PICKUP'))
    db.commit()
    params={'status':'tutti','supplier_id':supplier.id,'q':'EXTRA','date_from':'2026-09-17'}
    first=c.get('/manager/ordini',params=params); second=c.get('/manager/ordini',params={**params,'page':2})
    assert len(first.context['orders'])==20 and len(second.context['orders'])==5
    assert first.context['orders'][0].order_number=='EXTRA-24'
    assert not {x.id for x in first.context['orders']} & {x.id for x in second.context['orders']}
    assert f'supplier_id={supplier.id}' in str(first.context['page_url'])
    assert c.get('/manager/ordini',params={**params,'page':999}).context['page']==2
