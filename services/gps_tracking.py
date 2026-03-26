from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from models.entities import VehicleGpsTrackPoint
from models.veicoli import Veicolo


@dataclass(slots=True)
class GPSPosition:
    vehicle_provider_id: str | None
    gps_device_id: str | None
    latitude: float
    longitude: float
    timestamp: datetime
    speed_kmh: float | None = None
    vehicle_status: str | None = None
    raw_payload: dict[str, Any] | None = None


class GPSProviderAdapter(ABC):
    provider_name = "unconfigured"

    @abstractmethod
    def fetch_positions(self, *, vehicles: list[Veicolo]) -> list[GPSPosition]:
        """Fetch current positions for the provided vehicles."""

    def parse_webhook_payload(self, payload: dict[str, Any]) -> list[GPSPosition]:
        """Optional webhook parser."""
        return []


class NullGPSProviderAdapter(GPSProviderAdapter):
    provider_name = "none"

    def fetch_positions(self, *, vehicles: list[Veicolo]) -> list[GPSPosition]:
        return []


class GPSIntegrationService:
    def __init__(self, provider: GPSProviderAdapter):
        self.provider = provider

    def sync_truck_positions(self, db: Session) -> dict[str, int | str]:
        trucks = (
            db.query(Veicolo)
            .filter(Veicolo.categoria == "camion")
            .filter((Veicolo.gps_device_id.isnot(None)) | (Veicolo.provider_vehicle_id.isnot(None)))
            .all()
        )
        if not trucks:
            return {"provider": self.provider.provider_name, "trucks": 0, "updated": 0, "created_track_points": 0}

        by_provider_vehicle = {
            (vehicle.provider_vehicle_id or "").strip(): vehicle
            for vehicle in trucks
            if (vehicle.provider_vehicle_id or "").strip()
        }
        by_device = {
            (vehicle.gps_device_id or "").strip(): vehicle
            for vehicle in trucks
            if (vehicle.gps_device_id or "").strip()
        }

        updated = 0
        track_points_created = 0
        positions = self.provider.fetch_positions(vehicles=trucks)
        for position in positions:
            vehicle = None
            if position.vehicle_provider_id:
                vehicle = by_provider_vehicle.get(position.vehicle_provider_id.strip())
            if not vehicle and position.gps_device_id:
                vehicle = by_device.get(position.gps_device_id.strip())
            if not vehicle:
                continue

            vehicle.gps_last_latitude = float(position.latitude)
            vehicle.gps_last_longitude = float(position.longitude)
            vehicle.gps_last_timestamp = position.timestamp
            vehicle.gps_last_speed_kmh = float(position.speed_kmh) if position.speed_kmh is not None else None
            vehicle.gps_last_status = position.vehicle_status
            db.add(vehicle)
            updated += 1

            if position.raw_payload is not None:
                db.add(
                    VehicleGpsTrackPoint(
                        vehicle_id=vehicle.id,
                        provider=self.provider.provider_name,
                        latitude=float(position.latitude),
                        longitude=float(position.longitude),
                        recorded_at=position.timestamp,
                        speed_kmh=float(position.speed_kmh) if position.speed_kmh is not None else None,
                        vehicle_status=position.vehicle_status,
                        payload=position.raw_payload,
                    )
                )
                track_points_created += 1

        db.commit()
        return {
            "provider": self.provider.provider_name,
            "trucks": len(trucks),
            "updated": updated,
            "created_track_points": track_points_created,
        }

    def ingest_webhook_positions(self, db: Session, payload: dict[str, Any]) -> dict[str, int | str]:
        trucks = db.query(Veicolo).filter(Veicolo.categoria == "camion").all()
        by_provider_vehicle = {
            (vehicle.provider_vehicle_id or "").strip(): vehicle
            for vehicle in trucks
            if (vehicle.provider_vehicle_id or "").strip()
        }
        by_device = {
            (vehicle.gps_device_id or "").strip(): vehicle
            for vehicle in trucks
            if (vehicle.gps_device_id or "").strip()
        }
        positions = self.provider.parse_webhook_payload(payload)
        updated = 0
        for position in positions:
            vehicle = None
            if position.vehicle_provider_id:
                vehicle = by_provider_vehicle.get(position.vehicle_provider_id.strip())
            if not vehicle and position.gps_device_id:
                vehicle = by_device.get(position.gps_device_id.strip())
            if not vehicle:
                continue
            vehicle.gps_last_latitude = float(position.latitude)
            vehicle.gps_last_longitude = float(position.longitude)
            vehicle.gps_last_timestamp = position.timestamp
            vehicle.gps_last_speed_kmh = float(position.speed_kmh) if position.speed_kmh is not None else None
            vehicle.gps_last_status = position.vehicle_status
            db.add(vehicle)
            updated += 1

        db.commit()
        return {"provider": self.provider.provider_name, "received": len(positions), "updated": updated}


__all__ = [
    "GPSPosition",
    "GPSProviderAdapter",
    "NullGPSProviderAdapter",
    "GPSIntegrationService",
]
