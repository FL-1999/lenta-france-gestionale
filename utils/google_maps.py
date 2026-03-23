from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from typing import Any

import httpx

from utils.trips import compute_arrival_time

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


@dataclass
class TripETAResult:
    available: bool
    duration_minutes: int | None = None
    arrival_time: time | None = None
    source: str = "unavailable"
    message: str = "Arrivo stimato non disponibile"


def _point_location(point: dict[str, Any]) -> str | None:
    lat = point.get("lat")
    lng = point.get("lng")
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    name = str(point.get("name") or "").strip()
    return name or None


def estimate_trip_eta(viaggio: Any, route_points: list[dict[str, Any]]) -> TripETAResult:
    departure_time = getattr(viaggio, "orario_partenza", None)
    if departure_time is None:
        return TripETAResult(message="Imposta un orario di partenza per calcolare l'arrivo stimato")

    if len(route_points) < 2:
        return TripETAResult(message="Servono almeno origine e destinazione per stimare l'arrivo")

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return TripETAResult(message="Google Maps non configurato")

    origin = _point_location(route_points[0])
    destination = _point_location(route_points[-1])
    if not origin or not destination:
        return TripETAResult(message="Origine o destinazione incomplete")

    waypoints = [_point_location(point) for point in route_points[1:-1]]
    params = {
        "origin": origin,
        "destination": destination,
        "mode": "driving",
        "key": api_key,
    }
    valid_waypoints = [value for value in waypoints if value]
    if valid_waypoints:
        params["waypoints"] = "|".join(valid_waypoints)

    try:
        response = httpx.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=8.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError:
        return TripETAResult(message="Google Maps non raggiungibile")
    except ValueError:
        return TripETAResult(message="Risposta Google Maps non valida")

    routes = payload.get("routes") or []
    if payload.get("status") != "OK" or not routes:
        return TripETAResult(message="Percorso non disponibile da Google Maps")

    legs = routes[0].get("legs") or []
    total_seconds = sum(int((leg.get("duration") or {}).get("value") or 0) for leg in legs)
    if total_seconds <= 0:
        return TripETAResult(message="Durata del percorso non disponibile")

    duration_minutes = max(1, round(total_seconds / 60))
    arrival_time = compute_arrival_time(viaggio, duration_minutes=duration_minutes)
    if arrival_time is None:
        return TripETAResult(
            available=True,
            duration_minutes=duration_minutes,
            source="google_maps",
            message="Durata stimata disponibile, arrivo non calcolabile",
        )

    return TripETAResult(
        available=True,
        duration_minutes=duration_minutes,
        arrival_time=arrival_time,
        source="google_maps",
        message="Arrivo stimato calcolato con Google Maps",
    )
