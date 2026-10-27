"""Catalog completeness is independent of category placement and stock."""
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import joinedload
from models import MagazzinoItem as Item, MagazzinoCategoria as Category, SupplierArticle as Article, WarehouseSupplierPending as Pending


def unresolved_pending():
    # Also handles codes added by integrations/older clients: a real linked code
    # always resolves the reminder, even if a pending row has not been removed.
    return ~select(Article.id).where(
        Article.magazzino_item_id == Pending.magazzino_item_id,
        Article.supplier_id == Pending.supplier_id,
        func.trim(Article.codice) != '',
    ).correlate(Pending).exists()


def conditions():
    classified = select(Category.id).where(Category.id == Item.categoria_id,
        Category.attiva.is_(True), Category.macro_id.isnot(None)).correlate(Item).exists()
    linked = select(Article.id).where(Article.magazzino_item_id == Item.id).correlate(Item).exists()
    pending = select(Pending.id).where(Pending.magazzino_item_id == Item.id).correlate(Item).exists()
    blank_code = select(Article.id).where(Article.magazzino_item_id == Item.id,
        func.trim(Article.codice) == '').correlate(Item).exists()
    awaiting_code = select(Pending.id).where(Pending.magazzino_item_id == Item.id,
        unresolved_pending()).correlate(Item).exists()
    flags = {'classification': ~classified, 'supplier': ~(linked | pending), 'code': blank_code | awaiting_code}
    return {'all': or_(*flags.values()), **flags}


def summary(db):
    flags = conditions()
    row = db.query(*(func.coalesce(func.sum(case((flag, 1), else_=0)), 0)
        for flag in flags.values())).filter(Item.attivo.is_(True)).one()
    return dict(zip(flags, (int(value) for value in row)))


def pending_for_item(db, item_id):
    return db.query(Pending).options(joinedload(Pending.supplier)).filter(
        Pending.magazzino_item_id == item_id, unresolved_pending()).order_by(Pending.id).all()


def remember_supplier(db, item_id, supplier_id):
    """Caller holds the supplier lock, shared with catalog/order code writes."""
    if db.query(Article.id).filter(Article.magazzino_item_id == item_id,
            Article.supplier_id == supplier_id, func.trim(Article.codice) != '').first():
        return None
    pending = db.query(Pending).filter_by(magazzino_item_id=item_id, supplier_id=supplier_id).first()
    if pending is None:
        pending = Pending(magazzino_item_id=item_id, supplier_id=supplier_id)
        db.add(pending)
        db.flush()
    return pending


def resolve_supplier(db, item_id, supplier_id):
    db.query(Pending).filter_by(magazzino_item_id=item_id, supplier_id=supplier_id).delete(synchronize_session='fetch')


def supplier_counts(db):
    links = select(Article.magazzino_item_id, Article.supplier_id).where(Article.magazzino_item_id.isnot(None)).union(
        select(Pending.magazzino_item_id, Pending.supplier_id)).subquery()
    return dict(db.query(links.c.magazzino_item_id, func.count()).group_by(links.c.magazzino_item_id).all())
