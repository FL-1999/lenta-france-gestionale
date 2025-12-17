from __future__ import annotations

from datetime import date
from typing import Optional

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

    def __repr__(self) -> str:
        return f"<Veicolo id={self.id} targa={self.targa}>"
