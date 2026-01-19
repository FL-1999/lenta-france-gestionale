from __future__ import annotations

from sqlalchemy.orm import Session

from models import MagazzinoRichiesta, MagazzinoRichiestaStatusEnum


def count_pending_for_user(db: Session, user_id: int | None = None) -> int:
    query = db.query(MagazzinoRichiesta).filter(
        MagazzinoRichiesta.stato == MagazzinoRichiestaStatusEnum.in_attesa
    )
    return int(query.count() or 0)
