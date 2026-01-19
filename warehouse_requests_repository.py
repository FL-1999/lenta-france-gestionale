from __future__ import annotations

from sqlalchemy.orm import Session

from models import MagazzinoRichiesta, MagazzinoRichiestaStatusEnum


PENDING_REQUEST_STATUSES = {
    MagazzinoRichiestaStatusEnum.in_attesa,
}


def count_pending_for_user(db: Session, user_id: int | None = None) -> int:
    query = db.query(MagazzinoRichiesta).filter(
        MagazzinoRichiesta.stato.in_(PENDING_REQUEST_STATUSES)
    )
    return int(query.count() or 0)


def count_pending_requests_for_user(db: Session, user_id: int | None = None) -> int:
    return count_pending_for_user(db, user_id)
