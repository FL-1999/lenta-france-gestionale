from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Personale, RoleEnum, User


AUTO_PERSONALE_NOTE = "Creato automaticamente dal profilo utente/caposquadra."


def split_user_full_name(user: User) -> tuple[str, str]:
    display_name = (user.full_name or user.email.split("@", 1)[0]).strip()
    parts = display_name.split()
    if not parts:
        return "Caposquadra", user.email
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def should_create_personale_for_user(
    user: User,
    roles: list[RoleEnum] | tuple[RoleEnum, ...] | set[RoleEnum],
    create_personale_profile: bool | None = None,
) -> bool:
    """Decide whether a login user must also have a linked personnel profile.

    Automatic creation is intentionally narrow: only single-role caposquadra users
    without active role switching are synchronized. Explicit opt-in from the user
    form/API can force creation/association for exceptional multi-profile or generic
    users.
    """
    if create_personale_profile is not None:
        return bool(create_personale_profile)

    normalized_roles = set(roles)
    return (
        normalized_roles == {RoleEnum.caposquadra}
        and user.role == RoleEnum.caposquadra
        and not bool(getattr(user, "can_switch_roles", False))
    )


def ensure_user_personale_profile(
    db: Session,
    user: User,
    roles: list[RoleEnum] | tuple[RoleEnum, ...] | set[RoleEnum] | None = None,
    create_personale_profile: bool | None = None,
) -> Personale | None:
    """Create or associate the Personale row linked to a login user.

    Deduplication order:
    1. an existing personnel row with the same user_id;
    2. an existing personnel row with the same email (case-insensitive);
    3. otherwise a new active personnel row is created.
    """
    normalized_roles = list(roles or [user.role])
    if not should_create_personale_for_user(user, normalized_roles, create_personale_profile):
        return None

    email = (user.email or "").strip()
    personale = None

    if user.id is not None:
        personale = db.query(Personale).filter(Personale.user_id == user.id).first()

    if personale is None and email:
        personale = (
            db.query(Personale)
            .filter(func.lower(Personale.email) == email.lower())
            .first()
        )

    if personale:
        personale.user_id = user.id
        if email and not personale.email:
            personale.email = email
        if not personale.ruolo:
            personale.ruolo = _role_label(user.role)
        if not personale.attivo:
            personale.attivo = True
        db.add(personale)
        db.flush()
        return personale

    nome, cognome = split_user_full_name(user)
    personale = Personale(
        user_id=user.id,
        nome=nome,
        cognome=cognome,
        ruolo=_role_label(user.role),
        email=email or None,
        attivo=True,
        note=AUTO_PERSONALE_NOTE,
    )
    db.add(personale)
    db.flush()
    return personale


def _role_label(role: RoleEnum | None) -> str:
    if role == RoleEnum.caposquadra:
        return "Caposquadra"
    if role is None:
        return "Personale"
    return role.value.capitalize()
