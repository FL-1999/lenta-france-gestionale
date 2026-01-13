from __future__ import annotations

from datetime import date, timedelta

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


def copy_week_attendance_from_monday(
    session: Session,
    personale_id: int,
    week_start: date,
    overwrite: bool = False,
) -> tuple[int, int, bool]:
    week_end = week_start + timedelta(days=6)
    presenze = session.exec(
        select(PersonalePresenza).where(
            PersonalePresenza.personale_id == personale_id,
            PersonalePresenza.attendance_date >= week_start,
            PersonalePresenza.attendance_date <= week_end,
        )
    ).all()
    presenze_by_day = {presenza.attendance_date: presenza for presenza in presenze}
    monday = presenze_by_day.get(week_start)
    if not monday or not monday.status:
        return 0, 0, False

    created = 0
    updated = 0
    for offset in range(1, 7):
        day = week_start + timedelta(days=offset)
        existing = presenze_by_day.get(day)
        if existing:
            if overwrite:
                existing.status = monday.status
                existing.site_id = monday.site_id
                existing.hours = monday.hours
                existing.note = monday.note
                session.add(existing)
                updated += 1
            continue
        record = PersonalePresenza(
            personale_id=personale_id,
            attendance_date=day,
            status=monday.status,
            site_id=monday.site_id,
            hours=monday.hours,
            note=monday.note,
        )
        session.add(record)
        created += 1

    return created, updated, True
