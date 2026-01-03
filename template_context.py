from __future__ import annotations

from pathlib import Path

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


def get_cached_nuove_richieste_count(request: Request, db=None) -> int:
    cached = getattr(request.state, "nuove_richieste_count", None)
    if isinstance(cached, int):
        return cached

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        count = get_numero_richieste_nuove(db)
        count = int(count or 0)
        request.state.nuove_richieste_count = count
        return count
    finally:
        if close_db:
            db.close()


def render_template(
    templates,
    request: Request,
    template_name: str,
    context: dict | None,
    db,
    user: User | None,
    **response_kwargs,
):
    template_context = dict(context or {})
    template_context.setdefault("request", request)
    template_context.setdefault("user", user)

    template_context["nuove_richieste_count"] = get_cached_nuove_richieste_count(
        request, db
    )

    return templates.TemplateResponse(template_name, template_context, **response_kwargs)


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
        pending_requests = get_cached_nuove_richieste_count(request, db)
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


def static_url(request: Request, path: str) -> str:
    normalized_path = path.lstrip("/")
    static_path = Path("static") / normalized_path
    version = None
    try:
        version = int(static_path.stat().st_mtime)
    except FileNotFoundError:
        version = None

    url = request.url_for("static", path=normalized_path)
    if version is None:
        return str(url)
    return f"{url}?v={version}"


def register_static_helpers(templates) -> None:
    templates.env.globals.setdefault("static_url", static_url)
