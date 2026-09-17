"""Supplier-only purchase quantities, independent of current warehouse stock."""
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from models import PurchaseOrder, PurchaseOrderLine, PurchaseDelivery, PurchaseDeliveryLine


def supplier_purchase_materials(db, supplier_id):
    received = (db.query(PurchaseDeliveryLine.order_line_id.label('line_id'),
                        PurchaseDelivery.order_id.label('order_id'),
                        func.sum(PurchaseDeliveryLine.qty_delivered).label('quantity'))
        .join(PurchaseDelivery, PurchaseDelivery.id == PurchaseDeliveryLine.delivery_id)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseDelivery.order_id)
        .filter(PurchaseDelivery.confirmed.is_(True), PurchaseOrder.supplier_id == supplier_id)
        .group_by(PurchaseDeliveryLine.order_line_id, PurchaseDelivery.order_id).subquery())
    rows = (db.query(PurchaseOrderLine, func.coalesce(received.c.quantity, 0))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
        .outerjoin(received, (received.c.line_id == PurchaseOrderLine.id) & (received.c.order_id == PurchaseOrder.id))
        .options(joinedload(PurchaseOrderLine.magazzino_item), joinedload(PurchaseOrderLine.order))
        .filter(PurchaseOrder.supplier_id == supplier_id)
        .order_by(PurchaseOrder.id.desc(), PurchaseOrderLine.id).all())
    materials = {}
    for line, quantity in rows:
        item = line.magazzino_item
        # Unlinked historical lines have no recorded unit or reliable common identity.
        key = ('item', item.id) if item else ('line', line.id)
        if key not in materials:
            materials[key] = {'item': item, 'name': item.nome if item else (line.description or line.codice or '—'),
                'unit': item.unita_misura if item else None, 'ordered': 0, 'received': 0, 'remaining': 0,
                'codes': set(), 'order_ids': set(), 'latest_order': line.order}
        material = materials[key]
        material['ordered'] += line.qty_ordered
        material['received'] += quantity
        material['remaining'] += max(0, line.qty_ordered - quantity)
        material['order_ids'].add(line.order_id)
        if line.codice: material['codes'].add(line.codice)
    for material in materials.values():
        material['codes'] = sorted(material['codes'])
        material['order_count'] = len(material.pop('order_ids'))
    return list(materials.values())
