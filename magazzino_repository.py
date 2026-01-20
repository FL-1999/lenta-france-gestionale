from __future__ import annotations

from sqlalchemy.orm import Session

from models import MagazzinoItem


def count_under_threshold(db: Session | None) -> int:
    if db is None:
        return 0
    count = (
        db.query(MagazzinoItem)
        .filter(
            MagazzinoItem.attivo.is_(True),
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
        .count()
    )
    return int(count or 0)
