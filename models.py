from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Float,
    Text,
    Date,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from database import Base


class RoleEnum(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    caposquadra = "caposquadra"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.caposquadra)
    language = Column(String, default="it")  # "it" o "fr"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reports = relationship("DailyReport", back_populates="author")


class SiteStatusEnum(str, enum.Enum):
    aperto = "aperto"
    in_corso = "in_corso"
    chiuso = "chiuso"


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    status = Column(Enum(SiteStatusEnum), default=SiteStatusEnum.aperto)
    progress = Column(Integer, default=0)  # 0–100
    description = Column(Text, nullable=True)

    machines = relationship("Machine", back_populates="current_site")
    reports = relationship("DailyReport", back_populates="site")
    fiches = relationship("Fiche", back_populates="site")


class MachineTypeEnum(str, enum.Enum):
    escavatore = "escavatore"
    pala_gommata = "pala_gommata"
    macchina_pali = "macchina_pali"
    macchina_paratie = "macchina_paratie"
    altro = "altro"


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    model = Column(String, nullable=True)
    type = Column(Enum(MachineTypeEnum), nullable=False)
    current_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    notes = Column(Text, nullable=True)        # note generali
    issue_notes = Column(Text, nullable=True)  # problemi segnalati
    has_issue = Column(Boolean, default=False)

    current_site = relationship("Site", back_populates="machines")
    fiches = relationship("Fiche", back_populates="machine")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    date = Column(Date, default=datetime.utcnow)
    weather = Column(String, nullable=True)
    num_workers = Column(Integer, default=0)
    hours_worked = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)

    site = relationship("Site", back_populates="reports")
    author = relationship("User", back_populates="reports")


class FicheTypeEnum(str, enum.Enum):
    palo = "palo"
    paratia = "paratia"


class Fiche(Base):
    __tablename__ = "fiches"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)

    type = Column(Enum(FicheTypeEnum), nullable=False)  # palo / paratia
    panel_number = Column(String, nullable=True)

    # Per pali
    diameter_mm = Column(Integer, nullable=True)
    total_depth_m = Column(Float, nullable=True)

    # Per paratie
    paratia_depth_m = Column(Float, nullable=True)
    paratia_width_m = Column(Float, nullable=True)

    dig_date = Column(Date, nullable=True)
    cast_date = Column(Date, nullable=True)

    site = relationship("Site", back_populates="fiches")
    machine = relationship("Machine", back_populates="fiches")
    layers = relationship("StratigraphyLayer", back_populates="fiche")


class StratigraphyLayer(Base):
    __tablename__ = "stratigraphy_layers"

    id = Column(Integer, primary_key=True, index=True)
    fiche_id = Column(Integer, ForeignKey("fiches.id"), nullable=False)

    from_m = Column(Float, nullable=False)
    to_m = Column(Float, nullable=False)
    description = Column(Text, nullable=True)

    fiche = relationship("Fiche", back_populates="layers")