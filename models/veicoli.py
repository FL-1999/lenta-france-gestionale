from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Float
from sqlmodel import SQLModel, Field


class Veicolo(SQLModel, table=True):
    __tablename__ = "veicoli"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Dati principali
    marca: str = Field(max_length=120)
    modello: str = Field(max_length=120)
    targa: str = Field(max_length=50, index=True)

    anno: Optional[int] = None
    km: Optional[int] = None

    # Nuovi campi
    carburante: Optional[str] = Field(default=None, max_length=50)
    assicurazione_scadenza: Optional[date] = None
    revisione_scadenza: Optional[date] = None

    # Solo FK verso personale.id (nessuna relationship Python per ora)
    assegnato_a_id: Optional[int] = Field(
        default=None,
        foreign_key="personale.id",
    )

    note: Optional[str] = None
    visibile_trasporti: bool = Field(default=False)

    # Classificazione e integrazione GPS camion
    categoria: str = Field(default="altro", max_length=50)
    gps_device_id: Optional[str] = Field(default=None, max_length=100, index=True)
    provider_vehicle_id: Optional[str] = Field(default=None, max_length=100, index=True)

    gps_last_latitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    gps_last_longitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    gps_last_timestamp: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    gps_last_speed_kmh: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    gps_last_status: Optional[str] = Field(default=None, max_length=100)

    @property
    def is_camion(self) -> bool:
        return (self.categoria or "").strip().lower() == "camion"

    def __repr__(self) -> str:
        return f"<Veicolo id={self.id} targa={self.targa}>"
