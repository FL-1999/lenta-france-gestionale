from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from models import PersonalePresenza


def get_week_attendance(
    session: Session,
    week_start: date,
    week_end: date,
    personale_id: int | None = None,
) -> list[PersonalePresenza]:
    query = select(PersonalePresenza).where(
        PersonalePresenza.attendance_date >= week_start,
        PersonalePresenza.attendance_date <= week_end,
    )
    if personale_id is not None:
        query = query.where(PersonalePresenza.personale_id == personale_id)
    return session.exec(query).all()


def upsert_personale_presenza(
    session: Session,
    personale_id: int,
    attendance_date: date,
    status: str,
    site_id: int | None = None,
    hours: float | None = None,
    note: str | None = None,
) -> PersonalePresenza:
    existing = session.exec(
        select(PersonalePresenza).where(
            PersonalePresenza.personale_id == personale_id,
            PersonalePresenza.attendance_date == attendance_date,
        )
    ).first()
    if existing:
        existing.status = status
        existing.site_id = site_id
        existing.hours = hours
        existing.note = note
        session.add(existing)
        return existing

    record = PersonalePresenza(
        personale_id=personale_id,
        attendance_date=attendance_date,
        status=status,
        site_id=site_id,
        hours=hours,
        note=note,
    )
    session.add(record)
    return record
