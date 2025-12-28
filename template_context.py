from __future__ import annotations

from fastapi import Request
from sqlalchemy import func

from database import SessionLocal
from models import (
    MagazzinoItem,
    MagazzinoRichiesta,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    User,
)


def _can_view_manager_badges(user: User | None) -> bool:
    if not user:
        return False
    return bool(
        user.role in (RoleEnum.admin, RoleEnum.manager) or getattr(user, "is_magazzino_manager", False)
    )


def get_numero_richieste_nuove(db) -> int:
    richieste_nuove = (
        db.query(func.count(MagazzinoRichiesta.id))
        .filter(MagazzinoRichiesta.stato == MagazzinoRichiestaStatusEnum.in_attesa)
        .scalar()
    )
    return int(richieste_nuove or 0)


def manager_badge_counts(request: Request, user: User | None = None) -> dict[str, int]:
    cached = getattr(request.state, "manager_badge_counts", None)
    if isinstance(cached, dict):
        return cached

    counts = {"pending_requests": 0, "low_stock": 0, "nuove_richieste_count": 0}
    if not _can_view_manager_badges(user):
        request.state.manager_badge_counts = counts
        return counts

    db = SessionLocal()
    try:
        pending_requests = get_numero_richieste_nuove(db)
        low_stock = (
            db.query(func.count(MagazzinoItem.id))
            .filter(
                MagazzinoItem.attivo.is_(True),
                MagazzinoItem.soglia_minima.isnot(None),
                MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
            )
            .scalar()
        )
        counts = {
            "pending_requests": int(pending_requests or 0),
            "nuove_richieste_count": int(pending_requests or 0),
            "low_stock": int(low_stock or 0),
        }
    finally:
        db.close()

    request.state.manager_badge_counts = counts
    return counts


def register_manager_badges(templates) -> None:
    templates.env.globals.setdefault("manager_badge_counts", manager_badge_counts)
