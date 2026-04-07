from datetime import date, datetime, time
from types import SimpleNamespace

from utils.trips import can_edit_trip, compute_arrival_time, compute_trip_progress, format_trip_datetime_parts


def test_can_edit_trip_allows_only_pre_departure_states() -> None:
    assert can_edit_trip(SimpleNamespace(stato=SimpleNamespace(value="programmato"))) is True
    assert can_edit_trip(SimpleNamespace(stato=SimpleNamespace(value="in_carico"))) is False
    assert can_edit_trip(SimpleNamespace(stato=SimpleNamespace(value="in_viaggio"))) is False
    assert can_edit_trip(SimpleNamespace(stato=SimpleNamespace(value="completato"))) is False


def test_compute_arrival_time_uses_departure_and_duration() -> None:
    viaggio = SimpleNamespace(
        data_partenza=date(2026, 3, 20),
        orario_partenza=time(6, 30),
        durata_stimata_minuti=80,
    )

    assert compute_arrival_time(viaggio) == time(7, 50)
    assert format_trip_datetime_parts(viaggio.data_partenza, viaggio.orario_partenza) == "2026-03-20 · 06:30"


def test_compute_trip_progress_returns_not_started_before_departure() -> None:
    viaggio = SimpleNamespace(
        data_partenza=date(2026, 3, 20),
        orario_partenza=time(8, 0),
        arrivo_stimato=time(10, 0),
        data_arrivo_prevista=None,
        durata_stimata_minuti=None,
    )

    result = compute_trip_progress(viaggio, now=datetime(2026, 3, 20, 7, 30))

    assert result["status"] == "non_partito"
    assert result["progress_percent"] == 0
    assert result["is_available"] is True


def test_compute_trip_progress_returns_in_progress_between_departure_and_eta() -> None:
    viaggio = SimpleNamespace(
        data_partenza=date(2026, 3, 20),
        orario_partenza=time(8, 0),
        arrivo_stimato=time(10, 0),
        data_arrivo_prevista=None,
        durata_stimata_minuti=None,
    )

    result = compute_trip_progress(viaggio, now=datetime(2026, 3, 20, 9, 0))

    assert result["status"] == "in_corso"
    assert result["progress_percent"] == 50
    assert result["is_available"] is True


def test_compute_trip_progress_returns_delay_after_eta() -> None:
    viaggio = SimpleNamespace(
        data_partenza=date(2026, 3, 20),
        orario_partenza=time(8, 0),
        arrivo_stimato=time(10, 0),
        data_arrivo_prevista=None,
        durata_stimata_minuti=None,
    )

    result = compute_trip_progress(viaggio, now=datetime(2026, 3, 20, 11, 0))

    assert result["status"] == "in_ritardo"
    assert result["progress_percent"] == 100
    assert result["is_available"] is True


def test_compute_trip_progress_returns_fallback_when_estimate_missing() -> None:
    viaggio = SimpleNamespace(
        data_partenza=date(2026, 3, 20),
        orario_partenza=None,
        arrivo_stimato=None,
        data_arrivo_prevista=None,
        durata_stimata_minuti=None,
    )

    result = compute_trip_progress(viaggio)

    assert result["status"] == "non_disponibile"
    assert result["progress_percent"] is None
    assert result["is_available"] is False
