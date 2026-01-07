from __future__ import annotations

from collections.abc import Iterable
from typing import FrozenSet

from models import RoleEnum, User


MANAGER_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "manager.access",
        "sites.create",
        "sites.update",
        "users.read",
    }
)

MAGAZZINO_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "inventory.read",
        "inventory.manage",
    }
)

CONTABILITA_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "reports.read_all",
    }
)

HR_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "users.read",
    }
)

ADMIN_EXTRA_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        "sites.delete",
        "users.manage",
        "users.create",
        "users.update",
        "users.update_role",
        "users.delete",
        "users.*",
        "settings.manage",
        "records.delete",
    }
)

ROLE_PERMISSIONS: dict[RoleEnum, FrozenSet[str]] = {
    RoleEnum.caposquadra: frozenset(),
    RoleEnum.manager: MANAGER_PERMISSIONS,
    RoleEnum.admin: MANAGER_PERMISSIONS | ADMIN_EXTRA_PERMISSIONS,
    RoleEnum.magazzino: MAGAZZINO_PERMISSIONS,
    RoleEnum.contabilita: CONTABILITA_PERMISSIONS,
    RoleEnum.hr: HR_PERMISSIONS,
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
    role = _normalize_role(getattr(user, "role", None))
    if role is None:
        return False
    permissions = ROLE_PERMISSIONS.get(role, frozenset())
    return _perm_matches(perm, permissions)
