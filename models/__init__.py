from enum import Enum as PyEnum
from typing import Optional
from datetime import datetime, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Float,
    Text,
    Boolean,
    ForeignKey,
    Enum,
    DateTime,
)
from sqlalchemy.orm import relationship
from sqlmodel import SQLModel, Field

from database import Base


# ============================================================
# ENUM
# ============================================================

class RoleEnum(PyEnum):
    admin = "admin"
    manager = "manager"
    caposquadra = "caposquadra"


# Questi tre servono perché vengono importati in schemas.py

class SiteStatusEnum(PyEnum):
    # Stati in ITALIANO, compatibili con schemas.py (che usa .aperto)
    aperto = "aperto"
    chiuso = "chiuso"
    pianificato = "pianificato"


class MachineTypeEnum(PyEnum):
    escavatore = "escavatore"
    autocarro = "autocarro"
    furgone = "furgone"
    altro = "altro"


class FicheTypeEnum(PyEnum):
    produzione = "produzione"
    fermo_macchina = "fermo_macchina"
    controllo = "controllo"
    altro = "altro"


class MagazzinoRichiestaStatusEnum(PyEnum):
    in_attesa = "IN_ATTESA"
    approvata = "APPROVATA"
    rifiutata = "RIFIUTATA"
    evasa = "EVASA"


# ============================================================
# MIXIN PER TIMESTAMP
# ============================================================

class TimestampMixin:
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


# ============================================================
# MODELLO UTENTE
# ============================================================

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)

    hashed_password = Column(String(255), nullable=False)

    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.caposquadra)
    language = Column(String(10), nullable=True, default="it")

    is_active = Column(Boolean, default=True, nullable=False)
    is_magazzino_manager = Column(Boolean, default=False, nullable=False)

    # Relazioni
    reports = relationship("Report", back_populates="created_by", cascade="all, delete-orphan")
    fiches = relationship("Fiche", back_populates="created_by", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"


# ============================================================
# MODELLO CANTIERE (SITE)
# ============================================================

class Site(Base, TimestampMixin):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, index=True, nullable=True)

    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True, default="France")

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    status = Column(Enum(SiteStatusEnum), nullable=False, default=SiteStatusEnum.aperto)

    is_active = Column(Boolean, default=True, nullable=False)

    # Relazioni
    reports = relationship("Report", back_populates="site", cascade="all, delete-orphan")
    fiches = relationship("Fiche", back_populates="site", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="site", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Site id={self.id} code={self.code} name={self.name}>"


# ============================================================
# MODELLO MACCHINARIO
# ============================================================

class Machine(Base, TimestampMixin):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, index=True, nullable=True)

    brand = Column(String(255), nullable=True)
    model_name = Column(String(255), nullable=True)

    machine_type = Column(Enum(MachineTypeEnum), nullable=True)
    plate = Column(String(50), nullable=True)  # targa / matricola, se presente

    status = Column(String(50), nullable=False, default="attivo")
    notes = Column(Text, nullable=True)

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site = relationship("Site", back_populates="machines")

    fiches = relationship("Fiche", back_populates="machine")

    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Machine id={self.id} code={self.code} name={self.name}>"


# ============================================================
# MODELLO REPORT (RAPPORTINO GIORNALIERO)
# ============================================================

class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)

    # Data del rapportino
    date = Column(Date, nullable=False)

    # Cantiere: opzionale FK al Site + nome/codice libero
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site = relationship("Site", back_populates="reports")

    site_name_or_code = Column(String(255), nullable=False)

    # Dati lavorativi
    total_hours = Column(Float, nullable=False, default=0.0)
    workers_count = Column(Integer, nullable=False, default=0)

    machines_used = Column(Text, nullable=True)
    activities = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Chi ha creato il rapportino
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", back_populates="reports")

    def __repr__(self) -> str:
        return f"<Report id={self.id} date={self.date} site={self.site_name_or_code}>"


# ============================================================
# MODELLO FICHE DI CANTIERE
# ============================================================

class Fiche(Base, TimestampMixin):
    __tablename__ = "fiches"

    id = Column(Integer, primary_key=True, index=True)

    date = Column(Date, nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    site = relationship("Site", back_populates="fiches")

    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    machine = relationship("Machine", back_populates="fiches")

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", back_populates="fiches")

    fiche_type = Column(Enum(FicheTypeEnum), nullable=False)
    description = Column(Text, nullable=False)
    operator = Column(String(255), nullable=True)
    hours = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    tipologia_scavo = Column(String(50), nullable=True)
    stratigrafia = Column(Text, nullable=True)
    materiale = Column(String(100), nullable=True)
    profondita_totale = Column(Float, nullable=True)
    diametro_palo = Column(Float, nullable=True)
    larghezza_pannello = Column(Float, nullable=True)
    altezza_pannello = Column(Float, nullable=True)
    data_getto = Column(Date, nullable=True)
    metri_cubi_gettati = Column(Float, nullable=True)

    layers = relationship("StratigraphyLayer", back_populates="fiche", cascade="all, delete-orphan")
    stratigrafie = relationship(
        "FicheStratigrafia",
        back_populates="fiche",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Fiche id={self.id} date={self.date} type={self.fiche_type}>"


# ============================================================
# MODELLO STRATIGRAFIA FICHE (MULTI-LAYER)
# ============================================================

class FicheStratigrafia(Base, TimestampMixin):
    __tablename__ = "fiche_stratigrafia"

    id = Column(Integer, primary_key=True, index=True)
    fiche_id = Column(Integer, ForeignKey("fiches.id"), nullable=False)
    fiche = relationship("Fiche", back_populates="stratigrafie")

    da_profondita = Column(Float, nullable=False)
    a_profondita = Column(Float, nullable=False)
    materiale = Column(String(100), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<FicheStratigrafia id={self.id} fiche_id={self.fiche_id} "
            f"da={self.da_profondita} a={self.a_profondita}>"
        )


# ============================================================
# MODELLO STRATO (STRATIGRAPHY LAYER)
# ============================================================

class StratigraphyLayer(Base):
    __tablename__ = "stratigraphy_layers"

    id = Column(Integer, primary_key=True, index=True)
    fiche_id = Column(Integer, ForeignKey("fiches.id"), nullable=False)
    fiche = relationship("Fiche", back_populates="layers")

    layer_index = Column(Integer, nullable=False)
    material = Column(String(255), nullable=False)
    thickness_m = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<StratigraphyLayer id={self.id} fiche_id={self.fiche_id} layer_index={self.layer_index}>"


class MagazzinoItem(Base, TimestampMixin):
    __tablename__ = "magazzino_items"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    descrizione = Column(Text, nullable=True)
    unita_misura = Column(String(50), nullable=False)
    quantita_disponibile = Column(Float, nullable=False, default=0.0)
    soglia_minima = Column(Float, nullable=True)
    attivo = Column(Boolean, default=True, nullable=False)

    righe_richiesta = relationship("MagazzinoRichiestaRiga", back_populates="item")

    def __repr__(self) -> str:
        return f"<MagazzinoItem id={self.id} nome={self.nome} unita={self.unita_misura}>"


class MagazzinoRichiesta(Base, TimestampMixin):
    __tablename__ = "magazzino_richieste"

    id = Column(Integer, primary_key=True, index=True)
    stato = Column(
        Enum(MagazzinoRichiestaStatusEnum),
        nullable=False,
        default=MagazzinoRichiestaStatusEnum.in_attesa,
    )

    richiesto_da_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cantiere_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    note = Column(Text, nullable=True)

    risposta_manager = Column(Text, nullable=True)
    gestito_da_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    gestito_at = Column(DateTime, nullable=True)
    letto_da_richiedente = Column(Boolean, default=False, nullable=False)

    richiesto_da = relationship("User", foreign_keys=[richiesto_da_user_id])
    gestito_da = relationship("User", foreign_keys=[gestito_da_user_id])
    cantiere = relationship("Site")

    righe = relationship(
        "MagazzinoRichiestaRiga",
        back_populates="richiesta",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<MagazzinoRichiesta id={self.id} stato={self.stato}>"


class MagazzinoRichiestaRiga(Base):
    __tablename__ = "magazzino_richieste_righe"

    id = Column(Integer, primary_key=True, index=True)
    richiesta_id = Column(Integer, ForeignKey("magazzino_richieste.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("magazzino_items.id"), nullable=False)
    quantita_richiesta = Column(Float, nullable=False)

    richiesta = relationship("MagazzinoRichiesta", back_populates="righe")
    item = relationship("MagazzinoItem", back_populates="righe_richiesta")

    def __repr__(self) -> str:
        return (
            "<MagazzinoRichiestaRiga "
            f"id={self.id} richiesta_id={self.richiesta_id} item_id={self.item_id}>"
        )


class Personale(SQLModel, table=True):
    __tablename__ = "personale"

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    cognome: str
    ruolo: Optional[str] = Field(
        default=None, description="Ruolo in azienda (operaio, caposquadra, ecc.)"
    )
    telefono: Optional[str] = None
    email: Optional[str] = None
    data_assunzione: Optional[date] = None
    attivo: bool = Field(default=True)
    note: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


# Import dei modelli specifici
from .veicoli import Veicolo
