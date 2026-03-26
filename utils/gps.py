from __future__ import annotations

from models.entities import TrasportoViaggio


def trip_gps_marker_context(trip: TrasportoViaggio) -> dict[str, object]:
    mezzo = trip.mezzo
    if not mezzo:
        return {"source": "stimata", "gps_available": False, "gps_status_label": "Mezzo non associato"}

    if (mezzo.categoria or "").strip().lower() != "camion":
        return {"source": "stimata", "gps_available": False, "gps_status_label": "Mezzo non camion"}

    if mezzo.gps_last_latitude is not None and mezzo.gps_last_longitude is not None:
        return {
            "source": "gps_reale",
            "gps_available": True,
            "lat": float(mezzo.gps_last_latitude),
            "lng": float(mezzo.gps_last_longitude),
            "timestamp": mezzo.gps_last_timestamp.isoformat() if mezzo.gps_last_timestamp else None,
            "speed_kmh": float(mezzo.gps_last_speed_kmh) if mezzo.gps_last_speed_kmh is not None else None,
            "status": mezzo.gps_last_status,
            "gps_status_label": "GPS reale disponibile",
        }

    return {
        "source": "gps_non_disponibile",
        "gps_available": False,
        "timestamp": mezzo.gps_last_timestamp.isoformat() if mezzo.gps_last_timestamp else None,
        "speed_kmh": float(mezzo.gps_last_speed_kmh) if mezzo.gps_last_speed_kmh is not None else None,
        "status": mezzo.gps_last_status,
        "gps_status_label": "GPS non disponibile",
    }
