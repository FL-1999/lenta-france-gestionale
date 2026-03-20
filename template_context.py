from __future__ import annotations

import time
import os
from pathlib import Path
from threading import Lock

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal
from models import (
    MagazzinoItem,
    MagazzinoRichiesta,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    SiteStatusEnum,
    User,
)
from notifications import get_warehouse_notification_counts
from permissions import get_active_role, get_user_roles, has_perm, user_has_role
from utils.places import format_place_label


def _can_view_manager_badges(user: User | None) -> bool:
    if not user:
        return False
    return bool(
        has_perm(user, "manager.access")
        or has_perm(user, "inventory.read")
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
_CACHE_KEY_WAREHOUSE_NOTIFICATIONS = "warehouse_unread_notifications"

_CACHE_TTL_SHORT = 30
_CACHE_TTL_MEDIUM = 120
_CACHE_TTL_LONG = 600


def get_numero_richieste_nuove(db) -> int:
    try:
        richieste_nuove = (
            db.query(func.count(MagazzinoRichiesta.id))
            .filter(MagazzinoRichiesta.stato == MagazzinoRichiestaStatusEnum.in_attesa)
            .scalar()
        )
    except SQLAlchemyError:
        return 0
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


def get_cached_warehouse_notifications_count(
    request: Request, user: User | None, db=None
) -> dict[str, int | bool]:
    if not user:
        return {
            "total": 0,
            "low_stock": 0,
            "requests": 0,
            "has_any": False,
            "has_low_stock": False,
            "has_requests": False,
        }
    user_id = getattr(user, "id", None)
    role = getattr(user, "role", None)
    role_value = role.value if hasattr(role, "value") else role
    if user_id is None or role_value is None:
        return {
            "total": 0,
            "low_stock": 0,
            "requests": 0,
            "has_any": False,
            "has_low_stock": False,
            "has_requests": False,
        }
    cached = getattr(request.state, "warehouse_unread_notifications_count", None)
    if isinstance(cached, dict):
        return cached

    cache_key = f"{_CACHE_KEY_WAREHOUSE_NOTIFICATIONS}:{user_id}:{role_value}"
    cached_global = _CACHE.get(cache_key)
    if isinstance(cached_global, dict):
        request.state.warehouse_unread_notifications_count = cached_global
        return cached_global

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        counts = get_warehouse_notification_counts(db, user)
        request.state.warehouse_unread_notifications_count = counts
        _CACHE.set(cache_key, counts, _CACHE_TTL_SHORT)
        return counts
    finally:
        if close_db:
            db.close()


def get_warehouse_notifications_context(
    request: Request,
    user: User | None,
    db=None,
) -> dict[str, object]:
    counts = get_cached_warehouse_notifications_count(request, user, db)
    return {
        "unread_warehouse_notifications_count": counts["total"],
        "has_unread_warehouse_notifications": counts["has_any"],
        "unread_warehouse_low_stock_notifications_count": counts["low_stock"],
        "unread_warehouse_request_notifications_count": counts["requests"],
        "has_unread_warehouse_low_stock_notifications": counts["has_low_stock"],
        "has_unread_warehouse_request_notifications": counts["has_requests"],
    }


def build_manager_context(
    request: Request,
    user: User | None,
    **context: object,
) -> dict:
    return build_template_context(request, user, **context)


def render_template(
    templates,
    request: Request,
    template_name: str,
    context: dict | None,
    db=None,
    user: User | None = None,
    **response_kwargs,
):
    created_here = False
    if db is None:
        db = getattr(getattr(request, "state", None), "db", None)
    if db is None:
        db = SessionLocal()
        created_here = True

    try:
        template_context = build_manager_context(request, user, **(context or {}))
        template_context["nuove_richieste_count"] = get_cached_nuove_richieste_count(
            request, db
        )

        return templates.TemplateResponse(
            template_name, template_context, **response_kwargs
        )
    finally:
        if created_here and db is not None:
            db.close()


def get_lang_from_request(request: Request) -> str:
    lang = request.cookies.get("lang")
    if lang in ("it", "fr"):
        return lang
    return "it"


def build_template_context(
    request: Request,
    user: User | None,
    **context: object,
) -> dict:
    template_context = dict(context or {})
    template_context.setdefault("request", request)
    template_context.setdefault("user", user)
    template_context.setdefault("has_perm", has_perm)
    template_context.setdefault("lang", get_lang_from_request(request))
    template_context.setdefault("format_place_label", format_place_label)
    template_context.setdefault("google_maps_api_key", os.getenv("GOOGLE_MAPS_API_KEY"))

    active_role = get_active_role(user)
    available_roles = list(get_user_roles(user)) if user else []
    is_manager = bool(user and has_perm(user, "manager.access"))
    is_capo = bool(active_role == RoleEnum.caposquadra)
    template_context.setdefault("active_role", active_role)
    template_context.setdefault("available_roles", available_roles)
    template_context.setdefault("available_role_values", [role.value for role in available_roles])
    template_context.setdefault(
        "show_role_switcher",
        bool(
            user
            and getattr(user, "can_switch_roles", False)
            and len(available_roles) > 1
        ),
    )
    template_context.setdefault("is_manager", is_manager)
    template_context.setdefault("is_capo", is_capo)
    warehouse_notifications_context = get_warehouse_notifications_context(request, user)
    for key, value in warehouse_notifications_context.items():
        template_context.setdefault(key, value)
    template_context.setdefault(
        "warehouse_requests_count",
        template_context.get("unread_warehouse_request_notifications_count", 0),
    )
    template_context.setdefault(
        "has_warehouse_requests",
        template_context.get("has_unread_warehouse_request_notifications", False),
    )
    template_context.setdefault(
        "warehouse_low_stock_count",
        template_context.get("unread_warehouse_low_stock_notifications_count", 0),
    )
    template_context.setdefault(
        "has_warehouse_low_stock",
        template_context.get("has_unread_warehouse_low_stock_notifications", False),
    )
    template_context.setdefault(
        "warehouse_notifications_total",
        template_context.get("unread_warehouse_notifications_count", 0),
    )
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
        try:
            low_stock = (
                db.query(func.count(MagazzinoItem.id))
                .filter(
                    MagazzinoItem.attivo.is_(True),
                    MagazzinoItem.soglia_minima.isnot(None),
                    MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
                )
                .scalar()
            )
        except SQLAlchemyError:
            low_stock = 0
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
    templates.env.globals.setdefault("ASSET_VERSION", os.getenv("ASSET_VERSION", "1"))
