from datetime import date, time
from types import SimpleNamespace

from utils.trips import can_edit_trip, compute_arrival_time, format_trip_datetime_parts


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
