"""Explicit, bounded integration input contracts, independent of browser forms."""
from datetime import date, time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class SiteProgressChanges(StrictInput):
    cordoli_done_m: float | None = Field(default=None, ge=0, le=1000000, description='Metri eseguiti complessivi, non incremento.')
    cordoli_increment_m: float | None = Field(default=None, gt=0, le=1000000, description='Metri aggiuntivi; alternativo al totale eseguito.')
    cordoli_total_m: float | None = Field(default=None, gt=0, le=1000000, description='Totale previsto; null ripristina il totale automatico dalla pianta.')
    installazione_cantiere_pct: int | None = Field(default=None, ge=0, le=100)
    pozzi_pompaggio_pct: int | None = Field(default=None, ge=0, le=100)
    rabotage_pct: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode='after')
    def valid_patch(self):
        changes = self.model_dump(exclude_unset=True)
        if not changes or any(v is None and k != 'cordoli_total_m' for k, v in changes.items()):
            raise ValueError('Indicare almeno un valore; solo il totale previsto può essere null.')
        if 'cordoli_done_m' in changes and 'cordoli_increment_m' in changes:
            raise ValueError('Scegliere metri complessivi oppure metri aggiuntivi, non entrambi.')
        return self


class SiteDetailsChanges(StrictInput):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    start_date: date | None = None
    end_date: date | None = None
    caposquadra_id: int | None = Field(default=None, gt=0)
    projet_client: str | None = Field(default=None, max_length=255)
    projet_maitre_oeuvre: str | None = Field(default=None, max_length=255)
    projet_entreprise: str | None = Field(default=None, max_length=255)
    projet_affaire: str | None = Field(default=None, max_length=100)
    projet_indice: str | None = Field(default=None, max_length=50)
    projet_mission: str | None = Field(default=None, max_length=255)
    projet_redaction: str | None = Field(default=None, max_length=50)
    projet_controle: str | None = Field(default=None, max_length=50)

    @model_validator(mode='after')
    def valid_patch(self):
        if not self.model_fields_set:
            raise ValueError('Indicare almeno un dato da aggiornare.')
        if any(k in self.model_fields_set and getattr(self, k) is None for k in ('name', 'code')):
            raise ValueError('Nome e codice non possono essere cancellati.')
        if ('lat' in self.model_fields_set) != ('lng' in self.model_fields_set) or ((self.lat is None) != (self.lng is None)):
            raise ValueError('Latitudine e longitudine devono essere fornite insieme.')
        return self


class SiteProgressInput(StrictInput):
    site_id: int = Field(gt=0)
    changes: SiteProgressChanges


class SiteDetailsInput(StrictInput):
    site_id: int = Field(gt=0)
    changes: SiteDetailsChanges
    confirm_unverified_address: bool = Field(default=False, description='Solo su richiesta esplicita di salvare un nuovo indirizzo senza coordinate verificate.')


class ProposalInput(StrictInput):
    request_id: str = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$', description='Identificativo univoco del tentativo; riutilizzare lo stesso valore solo per ritentare la medesima proposta.')
    kind: Literal['fiche.create', 'report.create', 'trip.create', 'site.progress.update', 'site.details.update']
    payload: dict


INPUTS = {'fiche.create': FicheInput, 'report.create': ReportInput, 'trip.create': TripInput,
          'site.progress.update': SiteProgressInput, 'site.details.update': SiteDetailsInput}
