from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

EDITABLE_TRIP_STATUSES = {
    "programmato",
    "assegnato",
    "da confermare",
    "da_confermare",
    "non iniziato",
    "non_iniziato",
    "in_carico",
}

NON_EDITABLE_TRIP_STATUSES = {
    "in corso",
    "in_corso",
    "in viaggio",
    "in_viaggio",
    "arrivato",
    "completato",
    "annullato chiuso",
    "annullato_chiuso",
    "già eseguito",
    "gia eseguito",
    "gia_eseguito",
}


def trip_status_value(viaggio: Any) -> str:
    stato = getattr(viaggio, "stato", None)
    value = getattr(stato, "value", stato)
    return str(value or "").strip().lower()


def can_edit_trip(viaggio: Any) -> bool:
    stato = trip_status_value(viaggio)
    if not stato:
        return False
    if stato in NON_EDITABLE_TRIP_STATUSES:
        return False
    return stato in EDITABLE_TRIP_STATUSES


def combine_trip_departure(viaggio: Any) -> datetime | None:
    trip_date: date | None = getattr(viaggio, "data_partenza", None)
    trip_time: time | None = getattr(viaggio, "orario_partenza", None)
    if not trip_date or not trip_time:
        return None
    return datetime.combine(trip_date, trip_time)


def compute_arrival_time(viaggio: Any, *, duration_minutes: int | None = None) -> time | None:
    departure = combine_trip_departure(viaggio)
    minutes = duration_minutes if duration_minutes is not None else getattr(viaggio, "durata_stimata_minuti", None)
    if departure is None or minutes is None:
        return None
    return (departure + timedelta(minutes=int(minutes))).time().replace(second=0, microsecond=0)


def format_trip_time(value: time | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%H:%M")


def format_trip_datetime_parts(trip_date: date | None, trip_time: time | None) -> str:
    if trip_date and trip_time:
        return f"{trip_date.isoformat()} · {format_trip_time(trip_time)}"
    if trip_date:
        return trip_date.isoformat()
    if trip_time:
        return format_trip_time(trip_time)
    return "—"
