from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import Notification, RoleEnum, Report, Site, User, MagazzinoRichiesta


def create_notification(
    db: Session,
    notification_type: str,
    message: str,
    *,
    recipient_user_id: int | None = None,
    recipient_role: RoleEnum | None = None,
    target_url: str | None = None,
) -> Notification:
    notification = Notification(
        notification_type=notification_type,
        message=message,
        recipient_user_id=recipient_user_id,
        recipient_role=recipient_role,
        target_url=target_url,
        created_at=datetime.utcnow(),
        is_read=False,
    )
    db.add(notification)
    return notification


def create_notifications_for_users(
    db: Session,
    users: Iterable[User],
    notification_type: str,
    message: str,
    *,
    target_url: str | None = None,
    exclude_user_id: int | None = None,
) -> list[Notification]:
    notifications: list[Notification] = []
    for user in users:
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue
        notifications.append(
            create_notification(
                db,
                notification_type,
                message,
                recipient_user_id=user.id,
                target_url=target_url,
            )
        )
    return notifications


def _get_manager_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.role.in_([RoleEnum.manager, RoleEnum.admin]))
        .all()
    )


def _get_magazzino_manager_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.role.in_([RoleEnum.manager, RoleEnum.admin]),
            User.is_magazzino_manager.is_(True),
        )
        .all()
    )


def _find_site_for_report(db: Session, report: Report) -> Site | None:
    if not report.site_name_or_code:
        return None
    value = report.site_name_or_code.strip()
    if not value:
        return None
    return (
        db.query(Site)
        .filter(
            or_(
                Site.code == value,
                func.lower(Site.name) == value.lower(),
            )
        )
        .first()
    )


def notify_new_report(db: Session, report: Report, author: User) -> None:
    author_name = author.full_name or author.email
    message = (
        f"Nuovo rapportino da {author_name} per {report.site_name_or_code}."
    )
    create_notifications_for_users(
        db,
        _get_manager_users(db),
        "report_created",
        message,
        target_url="/manager/rapportini",
        exclude_user_id=author.id,
    )
    site = _find_site_for_report(db, report)
    if site and site.caposquadra_id and site.caposquadra_id != author.id:
        capo_message = (
            f"Nuovo rapportino per il cantiere {site.name}."
        )
        create_notification(
            db,
            "report_created",
            capo_message,
            recipient_user_id=site.caposquadra_id,
            target_url="/capo/rapportini",
        )


def notify_site_status_change(
    db: Session,
    site: Site,
    old_status: str | None,
    new_status: str | None,
    actor: User,
) -> None:
    old_label = old_status or "—"
    new_label = new_status or "—"
    manager_message = (
        f"Stato cantiere {site.name} aggiornato: {old_label} → {new_label}."
    )
    create_notifications_for_users(
        db,
        _get_manager_users(db),
        "site_status_changed",
        manager_message,
        target_url=f"/manager/sites/{site.id}",
        exclude_user_id=actor.id,
    )
    if site.caposquadra_id:
        capo_message = (
            f"Lo stato del tuo cantiere {site.name} è cambiato: {old_label} → {new_label}."
        )
        create_notification(
            db,
            "site_status_changed",
            capo_message,
            recipient_user_id=site.caposquadra_id,
            target_url=f"/capo/cantieri/{site.id}",
        )


def notify_magazzino_richiesta(
    db: Session,
    richiesta: MagazzinoRichiesta,
    requester: User,
) -> None:
    requester_name = requester.full_name or requester.email
    message = f"Nuova richiesta magazzino #{richiesta.id} da {requester_name}."
    create_notifications_for_users(
        db,
        _get_magazzino_manager_users(db),
        "magazzino_richiesta",
        message,
        target_url=f"/manager/magazzino/richieste/{richiesta.id}",
        exclude_user_id=requester.id,
    )
