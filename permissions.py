from __future__ import annotations

from collections.abc import Iterable
from typing import FrozenSet

from models import RoleEnum, User


MANAGER_BASE_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "manager.access",
        "trasporti.read",
        "trasporti.create",
        "trasporti.update",
        "cantieri.read",
        "sites.create",
        "sites.update",
        "depositi.read",
        "depositi.create",
        "depositi.update",
        "assegnazioni.read",
        "assegnazioni.manage",
        "economics.read",
        "economics.manage",
        "gabbie.read",
        "gabbie.manage",
    }
)

FERRAIOLO_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "gabbie.read",
        "gabbie.manage",
    }
)

MAGAZZINO_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "inventory.read",
        "inventory.manage",
        "inventory.movements.read",
        "warehouse.requests.read",
        "warehouse.requests.manage",
        "warehouse.loads.prepare",
        "equipment.read",
        "trasporti.read",
        "trasporti.loads.manage",
        "trasporti.movements.read",
        "depositi.read",
        "logistics.places.read",
    }
)


WAREHOUSE_PERMISSION_MATRIX: dict[str, tuple[str, ...]] = {
    "inventario_materiali": ("inventory.read", "inventory.manage"),
    "attrezzature": ("equipment.read", "trasporti.read", "trasporti.loads.manage"),
    "richieste_viaggio": ("warehouse.requests.read", "warehouse.requests.manage", "trasporti.read"),
    "preparazione_carichi": ("warehouse.loads.prepare", "trasporti.loads.manage"),
    "depositi_luoghi_logistici": ("depositi.read", "logistics.places.read"),
    "movimenti_magazzino": ("inventory.movements.read",),
}

DRIVER_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "trasporti.assigned.read",
        "trasporti.assigned.update",
    }
)

ADMIN_EXTRA_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "admin.access",
        "sites.delete",
        "users.read",
        "users.manage",
        "users.create",
        "users.update",
        "users.update_role",
        "users.delete",
        "users.switch_role",
        "users.*",
        "settings.manage",
        "records.delete",
    }
)

ROLE_PERMISSIONS: dict[RoleEnum, FrozenSet[str]] = {
    RoleEnum.caposquadra: frozenset(),
    RoleEnum.manager: MANAGER_BASE_PERMISSIONS,
    RoleEnum.admin: MANAGER_BASE_PERMISSIONS | ADMIN_EXTRA_PERMISSIONS,
    RoleEnum.magazzino: MAGAZZINO_PERMISSIONS,
    RoleEnum.driver: DRIVER_PERMISSIONS,
    RoleEnum.ferraiolo: FERRAIOLO_PERMISSIONS,
}


def _normalize_role(role: RoleEnum | str | None) -> RoleEnum | None:
    if role is None:
        return None
    if isinstance(role, RoleEnum):
        return role
    try:
        return RoleEnum(role)
    except Exception:
        try:
            cleaned_role = str(role).split(".")[-1]
            return RoleEnum[cleaned_role]
        except Exception:
            return None


def get_active_role(user: User | None) -> RoleEnum | None:
    if not user:
        return None
    return _normalize_role(getattr(user, "role", None))


def get_user_roles(user: User | None) -> tuple[RoleEnum, ...]:
    if not user:
        return tuple()

    collected: list[RoleEnum] = []
    seen: set[RoleEnum] = set()

    for user_role in getattr(user, "user_roles", []) or []:
        role_obj = getattr(user_role, "role", None)
        role_name = getattr(role_obj, "name", None)
        normalized = _normalize_role(role_name)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        collected.append(normalized)

    active_role = get_active_role(user)
    if active_role is not None and active_role not in seen:
        collected.append(active_role)

    return tuple(collected)


def user_has_role(user: User | None, role: RoleEnum | str | None) -> bool:
    normalized = _normalize_role(role)
    if normalized is None:
        return False
    return normalized in get_user_roles(user)


def _perm_matches(perm: str, granted: Iterable[str]) -> bool:
    if perm in granted:
        return True
    for granted_perm in granted:
        if granted_perm.endswith(".*") and perm.startswith(granted_perm[:-1]):
            return True
    if perm.endswith(".*"):
        prefix = perm[:-1]
        return any(p.startswith(prefix) for p in granted)
    return False


def has_perm(user: User | None, perm: str) -> bool:
    if not user:
        return False
    role = get_active_role(user)
    if role is None:
        return False
    permissions = ROLE_PERMISSIONS.get(role, frozenset())
    return _perm_matches(perm, permissions)



def has_any_perm(user: User | None, *perms: str) -> bool:
    return any(has_perm(user, perm) for perm in perms)


def can_access_manager_area(user: User | None) -> bool:
    return has_perm(user, "manager.access")


def can_access_warehouse_area(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "inventory.read", "inventory.manage")


def can_manage_warehouse_requests(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "warehouse.requests.manage", "warehouse.loads.prepare")


def can_access_depots(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "depositi.read")


def can_manage_depots(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "depositi.create", "depositi.update")


def can_access_logistics_area(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "trasporti.read", "trasporti.loads.manage")


def can_view_site_margin(user: User | None) -> bool:
    return user_has_role(user, RoleEnum.admin) or has_perm(user, "admin.access")


def can_manage_trip_loads(user: User | None) -> bool:
    return has_any_perm(user, "manager.access", "trasporti.loads.manage", "warehouse.loads.prepare")
