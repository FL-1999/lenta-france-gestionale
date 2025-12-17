from __future__ import annotations

from datetime import date
from typing import Optional

from sqlmodel import SQLModel, Field, Relationship


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

    # FK verso personale.id (SQLModel)
    assegnato_a_id: Optional[int] = Field(
        default=None,
        foreign_key="personale.id",
    )

    # Se vuoi usare v.assegnato_a nel template:
    # (funziona anche se la relationship inversa non è definita,
    # ma è più pulito se la aggiungi in Personale)
    assegnato_a: Optional["Personale"] = Relationship()

    note: Optional[str] = None

    def __repr__(self) -> str:
        return f"<Veicolo id={self.id} targa={self.targa}>"
