from enum import Enum as PyEnum
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
    active = "active"
    closed = "closed"
    planned = "planned"


class MachineTypeEnum(PyEnum):
    escavatore = "escavatore"
    autocarro = "autocarro"
    furgone = "furgone"
    altro = "altro"


class FicheTypeEnum(PyEnum):
    sicurezza = "sicurezza"
    produzione = "produzione"
    qualita = "qualita"
    altro = "altro"


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

    status = Column(Enum(SiteStatusEnum), nullable=False, default=SiteStatusEnum.active)

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

    machine_type = Column(Enum(MachineTypeEnum), nullable=True)
    plate = Column(String(50), nullable=True)  # targa, se presente

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site = relationship("Site", back_populates="machines")

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

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    fiche_type = Column(Enum(FicheTypeEnum), nullable=True)

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site = relationship("Site", back_populates="fiches")

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", back_populates="fiches")

    def __repr__(self) -> str:
        return f"<Fiche id={self.id} date={self.date} title={self.title}>"
