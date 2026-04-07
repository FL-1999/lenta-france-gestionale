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
}

NON_EDITABLE_TRIP_STATUSES = {
    # "in_carico" è trattato come viaggio già partito/in esecuzione.
    "in_carico",
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
    """Trip modificabile solo se non ancora partito."""
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


def combine_trip_arrival(viaggio: Any) -> datetime | None:
    trip_date: date | None = getattr(viaggio, "data_arrivo_prevista", None) or getattr(viaggio, "data_partenza", None)
    arrival_time: time | None = getattr(viaggio, "arrivo_stimato", None)
    if arrival_time is None:
        arrival_time = compute_arrival_time(viaggio)
    if not trip_date or not arrival_time:
        return None
    return datetime.combine(trip_date, arrival_time)


def compute_trip_progress(viaggio: Any, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.utcnow()
    departure_dt = combine_trip_departure(viaggio)
    arrival_dt = combine_trip_arrival(viaggio)
    fallback = {
        "progress_percent": None,
        "status": "non_disponibile",
        "status_label": "Stima non disponibile",
        "tempo_trascorso": None,
        "tempo_rimanente": None,
        "tempo_ritardo": None,
        "timing_text": "Stima non disponibile",
        "is_available": False,
    }
    if departure_dt is None or arrival_dt is None:
        return fallback
    total_seconds = int((arrival_dt - departure_dt).total_seconds())
    if total_seconds <= 0:
        return fallback

    elapsed_seconds = int((current_time - departure_dt).total_seconds())
    progress_ratio = max(0.0, min(1.0, elapsed_seconds / total_seconds))
    progress_percent = int(round(progress_ratio * 100))

    elapsed_delta = max(current_time - departure_dt, timedelta(0))
    remaining_delta = max(arrival_dt - current_time, timedelta(0))
    delay_delta = max(current_time - arrival_dt, timedelta(0))

    if current_time < departure_dt:
        status = "non_partito"
        status_label = "Non ancora partito"
        timing_text = "Non ancora partito"
    elif current_time > arrival_dt:
        status = "in_ritardo"
        status_label = "Arrivo stimato superato"
        timing_text = "In ritardo"
    elif progress_percent >= 100:
        status = "completato"
        status_label = "Arrivo stimato raggiunto"
        timing_text = "Arrivo stimato raggiunto"
    else:
        status = "in_corso"
        status_label = "In corso"
        timing_text = "Nei tempi"

    return {
        "progress_percent": progress_percent,
        "status": status,
        "status_label": status_label,
        "tempo_trascorso": elapsed_delta,
        "tempo_rimanente": remaining_delta,
        "tempo_ritardo": delay_delta,
        "timing_text": timing_text,
        "is_available": True,
    }


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
