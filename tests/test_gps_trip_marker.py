from datetime import datetime
from types import SimpleNamespace

from utils.gps import trip_gps_marker_context


def test_trip_gps_marker_context_uses_real_gps_for_camion() -> None:
    mezzo = SimpleNamespace(
        categoria="camion",
        gps_last_latitude=45.01,
        gps_last_longitude=7.61,
        gps_last_timestamp=datetime(2026, 3, 26, 8, 30),
        gps_last_speed_kmh=72.5,
        gps_last_status="in_movimento",
    )
    trip = SimpleNamespace(mezzo=mezzo)

    result = trip_gps_marker_context(trip)

    assert result["source"] == "gps_reale"
    assert result["gps_available"] is True
    assert result["lat"] == 45.01
    assert result["speed_kmh"] == 72.5


def test_trip_gps_marker_context_fallback_for_camion_without_fix() -> None:
    mezzo = SimpleNamespace(
        categoria="camion",
        gps_last_latitude=None,
        gps_last_longitude=None,
        gps_last_timestamp=None,
        gps_last_speed_kmh=None,
        gps_last_status=None,
    )
    trip = SimpleNamespace(mezzo=mezzo)

    result = trip_gps_marker_context(trip)

    assert result["source"] == "gps_non_disponibile"
    assert result["gps_available"] is False


def test_trip_gps_marker_context_estimated_for_non_truck() -> None:
    mezzo = SimpleNamespace(categoria="furgone")
    trip = SimpleNamespace(mezzo=mezzo)

    result = trip_gps_marker_context(trip)

    assert result["source"] == "stimata"
    assert result["gps_available"] is False
