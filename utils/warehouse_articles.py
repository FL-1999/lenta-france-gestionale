"""Rules shared by article deletion confirmation and its POST endpoint."""
from models import MagazzinoMovimento, MagazzinoRichiestaRiga, PurchaseOrderLine


def article_deletion_block(db, item):
    if (item.quantita_disponibile or 0) != 0:
        return 'stock'
    for model, field in [(MagazzinoMovimento, MagazzinoMovimento.item_id),
                         (MagazzinoRichiestaRiga, MagazzinoRichiestaRiga.item_id),
                         (PurchaseOrderLine, PurchaseOrderLine.magazzino_item_id)]:
        if db.query(model.id).filter(field == item.id).first():
            return 'history'
    return None
