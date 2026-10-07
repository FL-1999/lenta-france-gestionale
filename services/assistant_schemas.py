"""Explicit, bounded integration input contracts, independent of browser forms."""
from datetime import date, time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_max_length=10000)


class WorkerInput(StrictInput):
    personale_id: int = Field(gt=0)
    hours_worked: float = Field(ge=0, le=24)
    role_label: str | None = Field(default=None, max_length=120)
    note: str | None = None


class ReportInput(StrictInput):
    site_id: int = Field(gt=0)
    date: date
    total_hours: float = Field(ge=0, le=100000, description='Ore del rapportino secondo la convenzione del gestionale; le ore per persona sono esplicite in workers.')
    workers: list[WorkerInput] = Field(min_length=1, max_length=200)
    machines_used: str | None = None
    activities: str | None = None
    notes: str | None = None


class FicheInput(StrictInput):
    cantiere_id: int = Field(gt=0)
    numero_pannello: int = Field(gt=0)
    data_scavo: date
    operatore: str = Field(min_length=1, max_length=255)
    tipologia_scavo: Literal['paratia', 'palo']
    macchinario_id: int | None = Field(default=None, gt=0)
    capocantiere_id: int | None = Field(default=None, gt=0)
    coupe_id: int | None = Field(default=None, gt=0)
    data_getto: date | None = None
    metri_cubi_gettati: float | None = Field(default=None, ge=0)
    descrizione: str | None = None
    ore_lavorate: float | None = Field(default=None, ge=0)
    note: str | None = None
    materiale: str | None = None
    profondita_totale: float | None = Field(default=None, gt=0)
    diametro_palo_cm: float | None = Field(default=None, gt=0, description='Centimetri, non metri')
    larghezza_pannello: float | None = Field(default=None, gt=0, description='Metri')
    altezza_pannello: float | None = Field(default=None, gt=0, description='Spessore in metri')
    quota_ngf_testa: float | None = None
    quota_ngf_fondo: float | None = None
    quota_ngf_note: str | None = None
    scavo_da_tn: bool | None = None
    quota_partenza: float | None = None
    quota_testa_getto: float | None = None
    sonic_realizzato: bool | None = None
    inclinometre_realizzato: bool | None = None
    strato_da: list[float] = Field(default_factory=list, max_length=100)
    strato_a: list[float] = Field(default_factory=list, max_length=100)
    strato_materiale: list[str] = Field(default_factory=list, max_length=100)
    strato_materiale_altro: list[str] = Field(default_factory=list, max_length=100)
    courbe_beton_active: bool = False
    courbe_realisee_volume: list[float] = Field(default_factory=list, max_length=200)
    courbe_realisee_hauteur: list[float] = Field(default_factory=list, max_length=200)
    courbe_tube_volume: list[float] = Field(default_factory=list, max_length=200)
    courbe_tube_hauteur: list[float] = Field(default_factory=list, max_length=200)
    courbe_beton_volume_total: float | None = Field(default=None, ge=0)
    courbe_beton_hauteur_initiale: float | None = None
    courbe_beton_hauteur_finale: float | None = None


class MoveInput(StrictInput):
    key: str = Field(min_length=1, max_length=80)
    origin: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=100)


class TripInput(StrictInput):
    day: date
    hour: time
    driver_id: int = Field(gt=0)
    vehicle_id: int = Field(gt=0)
    start: str = Field(min_length=1, max_length=80)
    return_to_start: bool
    moves: list[MoveInput] = Field(min_length=1, max_length=150)


class ProposalInput(StrictInput):
    request_id: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$', description='Identificativo univoco del tentativo; riutilizzare lo stesso valore solo per ritentare la medesima proposta.')
    kind: Literal['fiche.create', 'report.create', 'trip.create']
    payload: dict


INPUTS = {'fiche.create': FicheInput, 'report.create': ReportInput, 'trip.create': TripInput}
