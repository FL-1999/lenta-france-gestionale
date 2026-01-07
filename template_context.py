from __future__ import annotations

import time
from pathlib import Path
from threading import Lock

from fastapi import Request
from sqlalchemy import func

from database import SessionLocal
from models import (
    MagazzinoItem,
    MagazzinoRichiesta,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    SiteStatusEnum,
    User,
)
from permissions import has_perm


def _can_view_manager_badges(user: User | None) -> bool:
    if not user:
        return False
    return bool(
        has_perm(user, "manager.access")
        or has_perm(user, "inventory.read")
        or getattr(user, "is_magazzino_manager", False)
    )


class _SimpleTTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[object, float]] = {}
        self._lock = Lock()

    def get(self, key: str) -> object | None:
        now = time.monotonic()
        with self._lock:
            value = self._data.get(key)
            if not value:
                return None
            cached_value, expires_at = value
            if expires_at < now:
                self._data.pop(key, None)
                return None
            return cached_value

    def set(self, key: str, value: object, ttl_seconds: int) -> None:
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            self._data[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


_CACHE = _SimpleTTLCache()

_CACHE_KEY_NUOVE_RICHIESTE = "nuove_richieste_count"
_CACHE_KEY_MANAGER_BADGES = "manager_badge_counts"
_CACHE_KEY_SITE_STATUSES = "site_status_values"
_CACHE_KEY_ROLE_CHOICES = "role_choices"

_CACHE_TTL_SHORT = 30
_CACHE_TTL_MEDIUM = 120
_CACHE_TTL_LONG = 600


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

    cached_global = _CACHE.get(_CACHE_KEY_NUOVE_RICHIESTE)
    if isinstance(cached_global, int):
        request.state.nuove_richieste_count = cached_global
        return cached_global

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        count = int(get_numero_richieste_nuove(db) or 0)
        request.state.nuove_richieste_count = count
        _CACHE.set(_CACHE_KEY_NUOVE_RICHIESTE, count, _CACHE_TTL_SHORT)
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
    template_context = build_template_context(request, user, **(context or {}))
    template_context["nuove_richieste_count"] = get_cached_nuove_richieste_count(
        request, db
    )

    return templates.TemplateResponse(template_name, template_context, **response_kwargs)


def build_template_context(
    request: Request,
    user: User | None,
    **context: object,
) -> dict:
    template_context = dict(context or {})
    template_context.setdefault("request", request)
    template_context.setdefault("user", user)
    template_context.setdefault("has_perm", has_perm)

    is_manager = bool(user and has_perm(user, "manager.access"))
    is_capo = bool(user and user.role == RoleEnum.caposquadra)
    template_context.setdefault("is_manager", is_manager)
    template_context.setdefault("is_capo", is_capo)
    return template_context


def manager_badge_counts(request: Request, user: User | None = None) -> dict[str, int]:
    cached = getattr(request.state, "manager_badge_counts", None)
    if isinstance(cached, dict):
        return cached

    counts = {"pending_requests": 0, "low_stock": 0, "nuove_richieste_count": 0}
    if not _can_view_manager_badges(user):
        request.state.manager_badge_counts = counts
        return counts

    cached_global = _CACHE.get(_CACHE_KEY_MANAGER_BADGES)
    if isinstance(cached_global, dict):
        request.state.manager_badge_counts = cached_global
        return cached_global

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
    _CACHE.set(_CACHE_KEY_MANAGER_BADGES, counts, _CACHE_TTL_MEDIUM)
    return counts


def get_cached_site_status_values() -> list[str]:
    cached = _CACHE.get(_CACHE_KEY_SITE_STATUSES)
    if isinstance(cached, list):
        return cached
    values = [status.name for status in SiteStatusEnum]
    _CACHE.set(_CACHE_KEY_SITE_STATUSES, values, _CACHE_TTL_LONG)
    return values


def get_cached_role_choices() -> list[RoleEnum]:
    cached = _CACHE.get(_CACHE_KEY_ROLE_CHOICES)
    if isinstance(cached, list):
        return cached
    values = list(RoleEnum)
    _CACHE.set(_CACHE_KEY_ROLE_CHOICES, values, _CACHE_TTL_LONG)
    return values


def invalidate_manager_badges_cache() -> None:
    _CACHE.invalidate(_CACHE_KEY_NUOVE_RICHIESTE)
    _CACHE.invalidate(_CACHE_KEY_MANAGER_BADGES)


def register_manager_badges(templates) -> None:
    templates.env.globals.setdefault("manager_badge_counts", manager_badge_counts)


def register_permission_helpers(templates) -> None:
    templates.env.globals.setdefault("has_perm", has_perm)


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
