from enum import Enum as PyEnum
import json
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
    Time,
    CheckConstraint,
    JSON,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import relationship
from sqlmodel import SQLModel, Field

from .base import Base
from utils.site_economics import compute_labor_flags, compute_labor_total


# ------------------------------------------------------------
# ENUM
# ------------------------------------------------------------

class RoleEnum(PyEnum):
    admin = "admin"
    manager = "manager"
    caposquadra = "caposquadra"
    magazzino = "magazzino"
    driver = "driver"


class TrasportoStatoEnum(PyEnum):
    programmato = "programmato"
    in_carico = "in_carico"
    in_viaggio = "in_viaggio"
    arrivato = "arrivato"
    completato = "completato"


class AttrezzaturaStatoEnum(PyEnum):
    disponibile = "disponibile"
    in_uso = "in_uso"
    in_trasporto = "in_trasporto"
    manutenzione = "manutenzione"


# Questi tre servono perché vengono importati in schemas.py

class SiteStatusEnum(PyEnum):
    # Stati in ITALIANO, compatibili con schemas.py (che usa .aperto)
    aperto = "aperto"
    chiuso = "chiuso"
    pianificato = "pianificato"


class MachineTypeEnum(PyEnum):
    macchina_base_cingoli = "macchina_base_cingoli"
    pala_gommata = "pala_gommata"
    scavatore = "scavatore"
    gru_cingolata = "gru_cingolata"
    kelly_diaframmi = "kelly_diaframmi"
    macchina_operatrice_diaframmi = "macchina_operatrice_diaframmi"
    macchina_operatrice_pali = "macchina_operatrice_pali"
    gruppo_elettrogeno = "gruppo_elettrogeno"
    dissabbiatore = "dissabbiatore"
    miscelatore = "miscelatore"
    pompa_bentonite = "pompa_bentonite"
    pompa_acqua = "pompa_acqua"
    saldatrice = "saldatrice"
    taglia_asfalto = "taglia_asfalto"


class FicheTypeEnum(PyEnum):
    produzione = "produzione"
    fermo_macchina = "fermo_macchina"
    controllo = "controllo"
    altro = "altro"


class MagazzinoRichiestaStatusEnum(PyEnum):
    in_attesa = "IN_ATTESA"
    approvata = "APPROVATA"
    rifiutata = "RIFIUTATA"
    parziale = "PARZIALE"
    evasa = "EVASA"


class MagazzinoRichiestaPrioritaEnum(PyEnum):
    low = "LOW"
    med = "MED"
    high = "HIGH"


class MagazzinoMovimentoTipoEnum(PyEnum):
    scarico = "scarico"
    carico = "carico"
    rettifica = "rettifica"


class DeliveryTypeEnum(PyEnum):
    SITE = "SITE"
    DEPOT = "DEPOT"
    PICKUP = "PICKUP"


class EmailLanguageEnum(PyEnum):
    IT = "IT"
    FR = "FR"
    EN = "EN"


class SiteEconomicEntryTypeEnum(PyEnum):
    revenue = "revenue"
    cost = "cost"


class SiteEconomicCategoryEnum(PyEnum):
    ricavi_previsti = "ricavi_previsti"
    ricavi_fatturati = "ricavi_fatturati"
    ricavi_maturati = "ricavi_maturati"
    materiali = "materiali"
    trasporti = "trasporti"
    mezzi = "mezzi"
    attrezzature = "attrezzature"
    manodopera = "manodopera"
    altri_costi = "altri_costi"


class SiteTaskStatusEnum(PyEnum):
    da_fare = "da_fare"
    in_corso = "in_corso"
    completato = "completato"


class SiteTaskPriorityEnum(PyEnum):
    bassa = "bassa"
    media = "media"
    alta = "alta"


# ------------------------------------------------------------
# MIXIN PER TIMESTAMP
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# MODELLI RUOLO / UTENTE
# ------------------------------------------------------------

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Enum(RoleEnum), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    user_links = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name}>"


class UserRole(Base, TimestampMixin):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_links")

    @property
    def role_name(self) -> RoleEnum | None:
        return self.role.name if self.role else None


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
    can_switch_roles = Column(Boolean, default=False, nullable=False)

    # Relazioni
    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reports = relationship("Report", back_populates="created_by", cascade="all, delete-orphan")
    fiches = relationship("Fiche", back_populates="created_by", cascade="all, delete-orphan")
    assigned_sites = relationship("Site", back_populates="caposquadra")
    magazzino_movimenti_creati = relationship(
        "MagazzinoMovimento",
        foreign_keys="MagazzinoMovimento.creato_da_user_id",
        back_populates="creato_da_user",
    )
    magazzino_movimenti_caposquadra = relationship(
        "MagazzinoMovimento",
        foreign_keys="MagazzinoMovimento.caposquadra_id",
        back_populates="caposquadra",
    )
    economic_entries_created = relationship(
        "SiteEconomicEntry",
        back_populates="created_by",
        foreign_keys="SiteEconomicEntry.created_by_id",
    )
    economic_entries_updated = relationship(
        "SiteEconomicEntry",
        back_populates="updated_by",
        foreign_keys="SiteEconomicEntry.updated_by_id",
    )
    labor_cost_entries_created = relationship(
        "SiteLaborCostEntry",
        back_populates="created_by",
        foreign_keys="SiteLaborCostEntry.created_by_id",
    )
    economic_budgets_created = relationship(
        "SiteEconomicBudget",
        back_populates="created_by",
        foreign_keys="SiteEconomicBudget.created_by_id",
    )
    economic_budgets_updated = relationship(
        "SiteEconomicBudget",
        back_populates="updated_by",
        foreign_keys="SiteEconomicBudget.updated_by_id",
    )
    economic_auto_params_created = relationship(
        "SiteEconomicAutoParams",
        back_populates="created_by",
        foreign_keys="SiteEconomicAutoParams.created_by_id",
    )
    economic_auto_params_updated = relationship(
        "SiteEconomicAutoParams",
        back_populates="updated_by",
        foreign_keys="SiteEconomicAutoParams.updated_by_id",
    )
    site_tasks_created = relationship(
        "SiteTask",
        back_populates="created_by",
        foreign_keys="SiteTask.created_by_id",
    )
    site_tasks_updated = relationship(
        "SiteTask",
        back_populates="updated_by",
        foreign_keys="SiteTask.updated_by_id",
    )
    site_tasks_completed = relationship(
        "SiteTask",
        back_populates="completed_by",
        foreign_keys="SiteTask.completed_by_id",
    )

    @property
    def active_role(self) -> RoleEnum | None:
        return self.role

    @property
    def assigned_role_names(self) -> list[RoleEnum]:
        roles: list[RoleEnum] = []
        seen: set[RoleEnum] = set()
        for user_role in self.user_roles or []:
            role_name = user_role.role_name
            if role_name is None or role_name in seen:
                continue
            seen.add(role_name)
            roles.append(role_name)
        if self.role and self.role not in seen:
            roles.append(self.role)
        return roles

    @property
    def assigned_role_values(self) -> list[str]:
        return [role.value for role in self.assigned_role_names]

    def has_role(self, role: RoleEnum | str | None) -> bool:
        if role is None:
            return False
        try:
            normalized = role if isinstance(role, RoleEnum) else RoleEnum(str(role))
        except Exception:
            try:
                normalized = RoleEnum[str(role).split(".")[-1]]
            except Exception:
                return False
        return normalized in self.assigned_role_names

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"


# ------------------------------------------------------------
# MODELLO AUDIT LOG
# ------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(255), nullable=False)
    target_type = Column("entity", String(255), nullable=False)
    target_id = Column("entity_id", Integer, nullable=True)
    extra_data = Column("details", JSON, nullable=True)

    user = relationship("User")

    @property
    def extra_data_text(self) -> str | None:
        if self.extra_data is None:
            return None
        if isinstance(self.extra_data, str):
            return self.extra_data
        return json.dumps(self.extra_data, ensure_ascii=False)

    def __repr__(self) -> str:
        return (
            "<AuditLog "
            f"id={self.id} action={self.action} target_type={self.target_type} target_id={self.target_id}>"
        )


# ------------------------------------------------------------
# MODELLO NOTIFICA
# ------------------------------------------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    notification_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    recipient_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    recipient_role = Column(Enum(RoleEnum), nullable=True)
    target_url = Column(String(255), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    recipient_user = relationship("User")

    def __repr__(self) -> str:
        return (
            "<Notification "
            f"id={self.id} type={self.notification_type} recipient_user_id={self.recipient_user_id}>"
        )


# ------------------------------------------------------------
# MODELLO CANTIERE (SITE)
# ------------------------------------------------------------

class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, index=True, nullable=True)
    address = Column(String(255), nullable=True)
    place_id = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True, default="France")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(Enum(SiteStatusEnum), nullable=False, default=SiteStatusEnum.aperto)
    is_active = Column(Boolean, default=True, nullable=False)
    cordoli_total_m = Column(Float, nullable=True)
    cordoli_done_m = Column(Float, nullable=True)
    paratie_total_panels = Column(Integer, nullable=True)
    paratie_done_panels = Column(Integer, nullable=True)
    totale_paratie_da_scavare = Column(Integer, nullable=True)
    numero_totale_paratie = Column(Integer, nullable=True)
    numero_totale_pali = Column(Integer, nullable=True)
    strut_levels_count = Column(Integer, nullable=True)
    installazione_cantiere_pct = Column(Integer, nullable=False, default=0)
    rabotage_pct = Column(Integer, nullable=False, default=0)
    pozzi_pompaggio_pct = Column(Integer, nullable=False, default=0)
    labor_cost_per_person = Column(Float, nullable=False, default=0.0)
    material_unit_prices = Column(Text, nullable=True)
    auto_cost_materials_enabled = Column(Boolean, nullable=False, default=True)
    auto_cost_labor_enabled = Column(Boolean, nullable=False, default=True)
    manual_material_entries_override_auto = Column(Boolean, nullable=False, default=True)

    caposquadra_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    caposquadra = relationship("User", back_populates="assigned_sites")

    # Relazioni
    reports = relationship("Report", back_populates="site", cascade="all, delete-orphan")
    fiches = relationship("Fiche", back_populates="site", cascade="all, delete-orphan")
    progress_grid_names = relationship(
        "SiteProgressGridName",
        back_populates="site",
        cascade="all, delete-orphan",
    )
    coupes = relationship(
        "SiteCoupe",
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="SiteCoupe.id",
    )
    machines = relationship("Machine", back_populates="site", cascade="all, delete-orphan")
    strut_levels = relationship(
        "SiteStrutLevel",
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="SiteStrutLevel.level_index",
    )
    economic_entries = relationship(
        "SiteEconomicEntry",
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="desc(SiteEconomicEntry.entry_date)",
    )
    labor_cost_entries = relationship(
        "SiteLaborCostEntry",
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="desc(SiteLaborCostEntry.work_date)",
    )
    economic_budget = relationship(
        "SiteEconomicBudget",
        back_populates="site",
        cascade="all, delete-orphan",
        uselist=False,
    )
    economic_auto_params = relationship(
        "SiteEconomicAutoParams",
        back_populates="site",
        cascade="all, delete-orphan",
        uselist=False,
    )
    tasks = relationship(
        "SiteTask",
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="desc(SiteTask.created_at)",
    )

    def __repr__(self) -> str:
        return f"<Site id={self.id} code={self.code} name={self.name}>"


class SiteTask(Base, TimestampMixin):
    __tablename__ = "site_tasks"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(SiteTaskStatusEnum), nullable=False, default=SiteTaskStatusEnum.da_fare)
    priority = Column(Enum(SiteTaskPriorityEnum), nullable=False, default=SiteTaskPriorityEnum.media)
    due_date = Column(Date, nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    completed = Column(Boolean, nullable=False, default=False)
    completed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    completed_at = Column(DateTime, nullable=True)

    site = relationship("Site", back_populates="tasks")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    created_by = relationship("User", foreign_keys=[created_by_id], back_populates="site_tasks_created")
    updated_by = relationship("User", foreign_keys=[updated_by_id], back_populates="site_tasks_updated")
    completed_by = relationship("User", foreign_keys=[completed_by_id], back_populates="site_tasks_completed")

    def __repr__(self) -> str:
        return (
            "<SiteTask "
            f"id={self.id} site_id={self.site_id} status={self.status.value} priority={self.priority.value}>"
        )



# ------------------------------------------------------------
# MODELLO LIVELLI PUNTONI
# ------------------------------------------------------------

class SiteStrutLevel(Base):
    __tablename__ = "site_strut_levels"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    level_index = Column(Integer, nullable=False)
    level_quota = Column(String(50), nullable=True)
    total_struts_level = Column(Integer, nullable=False, default=0)
    done_struts_level = Column(Integer, nullable=False, default=0)

    site = relationship("Site", back_populates="strut_levels")

    __table_args__ = (
        UniqueConstraint("site_id", "level_index", name="uq_site_strut_levels_index"),
    )

    def __repr__(self) -> str:
        return (
            "<SiteStrutLevel "
            f"id={self.id} site_id={self.site_id} level_index={self.level_index}>"
        )


# ------------------------------------------------------------
# MODELLO TIPO MACCHINARIO
# ------------------------------------------------------------

class MachineType(Base):
    __tablename__ = "machine_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(255), unique=True, nullable=False)
    label_it = Column(String(255), nullable=False)
    label_fr = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    machines = relationship("Machine", back_populates="machine_type_rel")

    def __repr__(self) -> str:
        return f"<MachineType id={self.id} code={self.code}>"


# ------------------------------------------------------------
# MODELLO MACCHINARIO
# ------------------------------------------------------------

class Machine(Base, TimestampMixin):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, index=True, nullable=True)

    brand = Column(String(255), nullable=True)
    model_name = Column(String(255), nullable=True)

    machine_type = Column(Enum(MachineTypeEnum), nullable=True)
    machine_type_id = Column(Integer, ForeignKey("machine_types.id"), nullable=True)
    plate = Column(String(50), nullable=True)  # targa / matricola, se presente

    status = Column(String(50), nullable=False, default="attivo")
    notes = Column(Text, nullable=True)

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site = relationship("Site", back_populates="machines")
    machine_type_rel = relationship("MachineType", back_populates="machines")

    fiches = relationship("Fiche", back_populates="machine")
    notes_history = relationship(
        "MachineNote",
        back_populates="machine",
        cascade="all, delete-orphan",
        order_by="desc(MachineNote.created_at)",
    )
    assignments = relationship(
        "MachineSiteAssignment",
        back_populates="machine",
        order_by="desc(MachineSiteAssignment.assigned_at)",
    )

    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Machine id={self.id} code={self.code} name={self.name}>"


# ------------------------------------------------------------
# MODELLO STORICO ASSEGNAZIONI MACCHINARI
# ------------------------------------------------------------

class MachineSiteAssignment(Base):
    __tablename__ = "machine_site_assignments"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    unassigned_at = Column(DateTime, nullable=True)
    location_label = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)

    machine = relationship("Machine", back_populates="assignments")
    site = relationship("Site")

    def __repr__(self) -> str:
        return (
            "<MachineSiteAssignment "
            f"id={self.id} machine_id={self.machine_id} site_id={self.site_id}>"
        )


# ------------------------------------------------------------
# MODELLO REPORT (RAPPORTINO GIORNALIERO)
# ------------------------------------------------------------

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
    workers = relationship(
        "ReportWorker",
        back_populates="report",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Report id={self.id} date={self.date} site={self.site_name_or_code}>"


# ------------------------------------------------------------
# MODELLO FICHE DI CANTIERE
# ------------------------------------------------------------


class SiteProgressGridName(Base, TimestampMixin):
    __tablename__ = "site_progress_grid_names"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "tipologia_scavo",
            "numero_elemento",
            name="uq_site_progress_grid_names_site_tipologia_numero",
        ),
        CheckConstraint(
            "numero_elemento > 0",
            name="ck_site_progress_grid_names_numero_positive",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    site = relationship("Site", back_populates="progress_grid_names")
    tipologia_scavo = Column(String(50), nullable=False)
    numero_elemento = Column(Integer, nullable=False)
    nome_personalizzato = Column(String(100), nullable=False)


class SiteCoupe(Base, TimestampMixin):
    __tablename__ = "site_coupes"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    site = relationship("Site", back_populates="coupes")
    nome = Column(String(100), nullable=False)
    quota_tn = Column(Float, nullable=True)
    quota_testa = Column(Float, nullable=True)
    quota_fondo_teorica = Column(Float, nullable=True)
    profondita_teorica = Column(Float, nullable=True)
    spessore = Column(Float, nullable=True)
    terreno_teorico = Column(Text, nullable=True)
    note = Column(Text, nullable=True)

    fiches = relationship("Fiche", back_populates="coupe")


class Fiche(Base, TimestampMixin):
    __tablename__ = "fiches"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "tipologia_scavo",
            "numero_pannello",
            name="uq_fiches_site_tipologia_numero_pannello",
        ),
        CheckConstraint("numero_pannello > 0", name="ck_fiches_numero_pannello_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)

    date = Column(Date, nullable=False)
    numero_pannello = Column(Integer, nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    site = relationship("Site", back_populates="fiches")

    coupe_id = Column(Integer, ForeignKey("site_coupes.id"), nullable=True)
    coupe = relationship("SiteCoupe", back_populates="fiches")

    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    machine = relationship("Machine", back_populates="fiches")

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", back_populates="fiches")

    fiche_type = Column(Enum(FicheTypeEnum), nullable=False)
    description = Column(Text, nullable=False)
    operator = Column(String(255), nullable=True)
    hours = Column(Float, nullable=True)
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
    quota_ngf_testa = Column(Float, nullable=True)
    quota_ngf_fondo = Column(Float, nullable=True)
    quota_ngf_note = Column(Text, nullable=True)
    scavo_da_tn = Column(Boolean, nullable=False, default=True)
    quota_partenza = Column(Float, nullable=True)
    quota_testa_getto = Column(Float, nullable=True)

    layers = relationship("StratigraphyLayer", back_populates="fiche", cascade="all, delete-orphan")
    stratigrafie = relationship(
        "FicheStratigrafia",
        back_populates="fiche",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Fiche id={self.id} date={self.date} type={self.fiche_type}>"


# ------------------------------------------------------------
# MODELLO STRATIGRAFIA FICHE (MULTI-LAYER)
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# MODELLO STRATO (STRATIGRAPHY LAYER)
# ------------------------------------------------------------

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


class MagazzinoCategoria(Base, TimestampMixin):
    __tablename__ = "magazzino_categorie"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=False, unique=True)
    ordine = Column(Integer, nullable=False, default=0)
    attiva = Column(Boolean, default=True, nullable=False)
    macro_id = Column(Integer, ForeignKey("magazzino_macro.id"), nullable=True)
    icon = Column(String(32), nullable=True, default="📦")
    color = Column(String(20), nullable=True, default="indigo")

    macro = relationship("MagazzinoMacro", back_populates="categorie")

    def __repr__(self) -> str:
        return f"<MagazzinoCategoria id={self.id} nome={self.nome} slug={self.slug}>"


class MagazzinoItem(Base, TimestampMixin):
    __tablename__ = "magazzino_items"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    codice = Column(String(120), nullable=False, default="")
    descrizione = Column(Text, nullable=True)
    unita_misura = Column(String(50), nullable=False, default="pz")
    categoria_id = Column(Integer, ForeignKey("magazzino_categorie.id"), nullable=True)
    quantita_disponibile = Column(Float, nullable=False, default=0.0)
    soglia_minima = Column(Float, nullable=True)
    attivo = Column(Boolean, default=True, nullable=False)
    preferito = Column(Boolean, default=False, nullable=False)

    categoria = relationship("MagazzinoCategoria")
    righe_richiesta = relationship("MagazzinoRichiestaRiga", back_populates="item")

    def __repr__(self) -> str:
        return (
            f"<MagazzinoItem id={self.id} codice={self.codice} nome={self.nome} "
            f"unita={self.unita_misura}>"
        )


class MagazzinoMacro(Base):
    __tablename__ = "magazzino_macro"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True)
    ordine = Column(Integer, nullable=False, default=0)
    icon = Column(String(32), nullable=True)
    color = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    categorie = relationship("MagazzinoCategoria", back_populates="macro")

    def __repr__(self) -> str:
        return f"<MagazzinoMacro id={self.id} name={self.name}>"


class MagazzinoRichiesta(Base, TimestampMixin):
    __tablename__ = "magazzino_richieste"

    id = Column(Integer, primary_key=True, index=True)
    priorita = Column(
        Enum(MagazzinoRichiestaPrioritaEnum),
        nullable=False,
        default=MagazzinoRichiestaPrioritaEnum.med,
    )
    stato = Column(
        Enum(MagazzinoRichiestaStatusEnum),
        nullable=False,
        default=MagazzinoRichiestaStatusEnum.in_attesa,
    )

    richiesto_da_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cantiere_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    note = Column(Text, nullable=True)
    data_necessaria = Column(Date, nullable=True)

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
    quantita_evasa = Column(Float, nullable=False, default=0.0)

    richiesta = relationship("MagazzinoRichiesta", back_populates="righe")
    item = relationship("MagazzinoItem", back_populates="righe_richiesta")

    def __repr__(self) -> str:
        return (
            "<MagazzinoRichiestaRiga "
            f"id={self.id} richiesta_id={self.richiesta_id} item_id={self.item_id}>"
        )


class MagazzinoMovimento(Base, TimestampMixin):
    __tablename__ = "magazzino_movimenti"
    __table_args__ = (
        CheckConstraint("quantita > 0", name="chk_magazzino_movimenti_quantita_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("magazzino_items.id"), nullable=False)
    tipo = Column(Enum(MagazzinoMovimentoTipoEnum), nullable=False)
    quantita = Column(Float, nullable=False)
    cantiere_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    deposito_id = Column(Integer, ForeignKey("depots.id"), nullable=True)
    riferimento_richiesta_id = Column(
        Integer, ForeignKey("magazzino_richieste.id"), nullable=True
    )
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    purchase_delivery_id = Column(
        Integer, ForeignKey("purchase_deliveries.id"), nullable=True
    )
    creato_da_user_id = Column("user_id", Integer, ForeignKey("users.id"), nullable=True)
    caposquadra_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)

    item = relationship("MagazzinoItem")
    cantiere = relationship("Site")
    deposito = relationship("Depot")
    creato_da_user = relationship(
        "User",
        foreign_keys=[creato_da_user_id],
        back_populates="magazzino_movimenti_creati",
    )
    caposquadra = relationship(
        "User",
        foreign_keys=[caposquadra_id],
        back_populates="magazzino_movimenti_caposquadra",
    )
    richiesta = relationship("MagazzinoRichiesta")
    purchase_order = relationship("PurchaseOrder")
    purchase_delivery = relationship("PurchaseDelivery")


class Personale(SQLModel, table=True):
    __tablename__ = "personale"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, unique=True, index=True, nullable=True),
    )
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


class ReportWorker(Base, TimestampMixin):
    __tablename__ = "report_workers"
    __table_args__ = (
        UniqueConstraint("report_id", "personale_id", name="uq_report_workers_report_personale"),
        CheckConstraint("hours_worked >= 0", name="ck_report_workers_hours_worked_non_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    personale_id = Column(Integer, ForeignKey(Personale.__table__.c.id), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    attendance_date = Column(Date, nullable=False, index=True)
    role_label = Column(String(120), nullable=True)
    note = Column(Text, nullable=True)
    hours_worked = Column(Float, nullable=False, default=8.0)
    day_type = Column(String(20), nullable=False, default="FULL")

    report = relationship("Report", back_populates="workers")
    worker = relationship(Personale)
    site = relationship("Site")


class SiteEconomicEntry(Base, TimestampMixin):
    __tablename__ = "site_economic_entries"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    entry_type = Column(Enum(SiteEconomicEntryTypeEnum), nullable=False, index=True)
    category = Column(Enum(SiteEconomicCategoryEnum), nullable=False, index=True)
    amount = Column(Float, nullable=False, default=0.0)
    description = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    site = relationship("Site", back_populates="economic_entries")
    created_by = relationship("User", back_populates="economic_entries_created", foreign_keys=[created_by_id])
    updated_by = relationship("User", back_populates="economic_entries_updated", foreign_keys=[updated_by_id])

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_site_economic_entries_amount_positive"),
    )


class SiteEconomicBudget(Base, TimestampMixin):
    __tablename__ = "site_economic_budgets"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_economic_budgets_site"),
        CheckConstraint("ricavo_previsto >= 0", name="ck_site_economic_budgets_ricavo_previsto_positive"),
        CheckConstraint("materiali_previsti >= 0", name="ck_site_economic_budgets_materiali_previsti_positive"),
        CheckConstraint("manodopera_prevista >= 0", name="ck_site_economic_budgets_manodopera_prevista_positive"),
        CheckConstraint("trasporti_previsti >= 0", name="ck_site_economic_budgets_trasporti_previsti_positive"),
        CheckConstraint("mezzi_previsti >= 0", name="ck_site_economic_budgets_mezzi_previsti_positive"),
        CheckConstraint("attrezzature_previste >= 0", name="ck_site_economic_budgets_attrezzature_previste_positive"),
        CheckConstraint("altri_costi_previsti >= 0", name="ck_site_economic_budgets_altri_costi_previsti_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    ricavo_previsto = Column(Float, nullable=False, default=0.0)
    materiali_previsti = Column(Float, nullable=False, default=0.0)
    manodopera_prevista = Column(Float, nullable=False, default=0.0)
    trasporti_previsti = Column(Float, nullable=False, default=0.0)
    mezzi_previsti = Column(Float, nullable=False, default=0.0)
    attrezzature_previste = Column(Float, nullable=False, default=0.0)
    altri_costi_previsti = Column(Float, nullable=False, default=0.0)
    note = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    site = relationship("Site", back_populates="economic_budget")
    created_by = relationship("User", back_populates="economic_budgets_created", foreign_keys=[created_by_id])
    updated_by = relationship("User", back_populates="economic_budgets_updated", foreign_keys=[updated_by_id])


class SiteLaborCostEntry(Base, TimestampMixin):
    __tablename__ = "site_labor_cost_entries"
    __table_args__ = (
        UniqueConstraint("site_id", "work_date", name="uq_site_labor_cost_entries_site_work_date"),
        CheckConstraint("worker_count >= 0", name="ck_site_labor_cost_entries_worker_count_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_site_labor_cost_entries_unit_cost_positive"),
        CheckConstraint("total_cost >= 0", name="ck_site_labor_cost_entries_total_cost_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, index=True)
    worker_count = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Float, nullable=False, default=0.0)
    total_cost = Column(Float, nullable=False, default=0.0)
    is_weekend = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    site = relationship("Site", back_populates="labor_cost_entries")
    created_by = relationship("User", back_populates="labor_cost_entries_created", foreign_keys=[created_by_id])

    @property
    def computed_total_cost(self) -> float:
        if not self.is_active:
            return 0.0
        return float((self.worker_count or 0) * (self.unit_cost or 0.0))


def _sync_site_labor_flags_and_total(target: SiteLaborCostEntry) -> None:
    work_date = getattr(target, "work_date", None)
    if not work_date:
        return

    target.is_weekend, target.is_active = compute_labor_flags(work_date, bool(target.is_active))
    target.total_cost = compute_labor_total(target.worker_count or 0, target.unit_cost or 0.0, bool(target.is_active))


@event.listens_for(SiteLaborCostEntry, "before_insert")
def _site_labor_before_insert(_mapper, _connection, target: SiteLaborCostEntry) -> None:
    _sync_site_labor_flags_and_total(target)


@event.listens_for(SiteLaborCostEntry, "before_update")
def _site_labor_before_update(_mapper, _connection, target: SiteLaborCostEntry) -> None:
    _sync_site_labor_flags_and_total(target)


class SiteEconomicAutoParams(Base, TimestampMixin):
    __tablename__ = "site_economic_auto_params"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_economic_auto_params_site"),
        CheckConstraint("costo_manodopera_persona_giorno >= 0", name="ck_site_auto_params_labor_positive"),
        CheckConstraint("costo_cemento_mc >= 0", name="ck_site_auto_params_cemento_positive"),
        CheckConstraint("costo_ferro_ton >= 0", name="ck_site_auto_params_ferro_ton_positive"),
        CheckConstraint("costo_ferro_kg >= 0", name="ck_site_auto_params_ferro_kg_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    costo_manodopera_persona_giorno = Column(Float, nullable=False, default=0.0)
    costo_cemento_mc = Column(Float, nullable=False, default=0.0)
    costo_ferro_ton = Column(Float, nullable=False, default=0.0)
    costo_ferro_kg = Column(Float, nullable=False, default=0.0)
    altri_prezzi_json = Column(Text, nullable=True)
    manual_material_entries_override_auto = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    site = relationship("Site", back_populates="economic_auto_params")
    created_by = relationship("User", back_populates="economic_auto_params_created", foreign_keys=[created_by_id])
    updated_by = relationship("User", back_populates="economic_auto_params_updated", foreign_keys=[updated_by_id])


class PersonalePresenza(SQLModel, table=True):
    __tablename__ = "personale_presenze"
    __table_args__ = (
        UniqueConstraint("personale_id", "date", name="uq_personale_presenze_personale_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    report_id: Optional[int] = Field(default=None, index=True)
    personale_id: int = Field(foreign_key="personale.id", index=True)
    attendance_date: date = Field(
        sa_column=Column("date", Date, index=True, nullable=False)
    )
    site_id: Optional[int] = Field(default=None, index=True)
    status: str = Field(max_length=20)
    hours: Optional[float] = None
    note: Optional[str] = None
    created_at: datetime = Field(
        sa_column=Column(DateTime, default=datetime.utcnow, nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
            nullable=False,
        )
    )


class VeicoloTrasporto(Base):
    __tablename__ = "veicoli"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String(120), nullable=False)
    modello = Column(String(120), nullable=False)
    targa = Column(String(50), nullable=False, unique=True, index=True)
    visibile_trasporti = Column(Boolean, nullable=False, default=False)
    categoria = Column(String(50), nullable=False, default="altro")
    gps_device_id = Column(String(100), nullable=True, index=True)
    provider_vehicle_id = Column(String(100), nullable=True, index=True)
    gps_last_latitude = Column(Float, nullable=True)
    gps_last_longitude = Column(Float, nullable=True)
    gps_last_timestamp = Column(DateTime, nullable=True)
    gps_last_speed_kmh = Column(Float, nullable=True)
    gps_last_status = Column(String(100), nullable=True)

    viaggi = relationship("TrasportoViaggio", back_populates="mezzo")
    gps_track_points = relationship(
        "VehicleGpsTrackPoint",
        back_populates="vehicle",
        cascade="all, delete-orphan",
        order_by="VehicleGpsTrackPoint.recorded_at.desc()",
    )


class VehicleGpsTrackPoint(Base, TimestampMixin):
    __tablename__ = "vehicle_gps_track_points"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("veicoli.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    recorded_at = Column(DateTime, nullable=False, index=True)
    speed_kmh = Column(Float, nullable=True)
    vehicle_status = Column(String(100), nullable=True)
    payload = Column(JSON, nullable=True)

    vehicle = relationship("VeicoloTrasporto", back_populates="gps_track_points")


class TrasportoMezzo(Base, TimestampMixin):
    __tablename__ = "trasporti_mezzi"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    targa = Column(String(20), nullable=False, unique=True, index=True)
    tipo = Column(String(100), nullable=True)



class Attrezzatura(Base, TimestampMixin):
    __tablename__ = "attrezzature"

    id = Column(Integer, primary_key=True, index=True)
    codice = Column(String(50), nullable=False, unique=True, index=True)
    qr_code = Column(String(50), nullable=False, unique=True, index=True)
    nome = Column(String(255), nullable=False)
    tipo = Column(String(100), nullable=False, index=True)
    stato = Column(
        Enum(AttrezzaturaStatoEnum),
        nullable=False,
        default=AttrezzaturaStatoEnum.disponibile,
    )
    posizione_attuale = Column(String(255), nullable=True)

    notes_history = relationship(
        "MachineNote",
        back_populates="attrezzatura",
        cascade="all, delete-orphan",
        order_by="desc(MachineNote.created_at)",
    )


class MachineNote(Base, TimestampMixin):
    __tablename__ = "machine_notes"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    attrezzatura_id = Column(Integer, ForeignKey("attrezzature.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    note_type = Column(String(50), nullable=True, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    machine = relationship("Machine", back_populates="notes_history")
    attrezzatura = relationship("Attrezzatura", back_populates="notes_history")
    site = relationship("Site")
    operator = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "(machine_id IS NOT NULL AND attrezzatura_id IS NULL) OR "
            "(machine_id IS NULL AND attrezzatura_id IS NOT NULL)",
            name="ck_machine_notes_single_asset",
        ),
    )

    def __repr__(self) -> str:
        return f"<MachineNote id={self.id} machine_id={self.machine_id} attrezzatura_id={self.attrezzatura_id}>"


class TrasportoViaggio(Base, TimestampMixin):
    __tablename__ = "trasporti_viaggi"

    id = Column(Integer, primary_key=True, index=True)
    codice_viaggio = Column(String(50), nullable=False, unique=True, index=True)
    data_partenza = Column(Date, nullable=False, index=True)
    orario_partenza = Column(Time, nullable=True)
    data_arrivo_prevista = Column(Date, nullable=True)
    arrivo_stimato = Column(Time, nullable=True)
    arrivo_stimato_manuale = Column(Boolean, nullable=False, default=False)
    durata_stimata_minuti = Column(Integer, nullable=True)
    autista_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    mezzo_id = Column(Integer, ForeignKey("veicoli.id"), nullable=True, index=True)
    origine_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    origine_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True, index=True)
    destinazione_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    destinazione_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True, index=True)
    origine = Column(String(255), nullable=False)
    destinazione = Column(String(255), nullable=False)
    materiali_attrezzature = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    stato = Column(
        Enum(TrasportoStatoEnum),
        nullable=False,
        default=TrasportoStatoEnum.programmato,
        index=True,
    )

    autista = relationship("User")
    mezzo = relationship("VeicoloTrasporto", back_populates="viaggi")
    origine_site = relationship("Site", foreign_keys=[origine_site_id])
    origine_depot = relationship("Depot", foreign_keys=[origine_depot_id])
    destinazione_site = relationship("Site", foreign_keys=[destinazione_site_id])
    destinazione_depot = relationship("Depot", foreign_keys=[destinazione_depot_id])
    richieste_attrezzature = relationship(
        "TrasportoRichiestaAttrezzatura",
        back_populates="viaggio",
        cascade="all, delete-orphan",
    )
    assegnazioni_attrezzature = relationship(
        "TrasportoAttrezzaturaViaggio",
        back_populates="viaggio",
        cascade="all, delete-orphan",
    )
    tappe = relationship(
        "TrasportoTappa",
        back_populates="viaggio",
        cascade="all, delete-orphan",
        order_by="TrasportoTappa.ordine",
    )


class TrasportoTappa(Base):
    __tablename__ = "trasporto_tappe"
    __table_args__ = (
        UniqueConstraint("viaggio_id", "ordine", name="uq_trasporto_tappa_viaggio_ordine"),
    )

    id = Column(Integer, primary_key=True, index=True)
    viaggio_id = Column(Integer, ForeignKey("trasporti_viaggi.id"), nullable=False, index=True)
    ordine = Column(Integer, nullable=False, default=1)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True, index=True)
    destinazione = Column(String(255), nullable=False)

    viaggio = relationship("TrasportoViaggio", back_populates="tappe")
    site = relationship("Site", foreign_keys=[site_id])
    depot = relationship("Depot", foreign_keys=[depot_id])
    richieste_attrezzature = relationship(
        "TrasportoRichiestaAttrezzatura",
        back_populates="tappa",
        cascade="all, delete-orphan",
    )


class TrasportoRichiestaAttrezzatura(Base):
    __tablename__ = "trasporto_richiesta_attrezzature"

    id = Column(Integer, primary_key=True, index=True)
    viaggio_id = Column(Integer, ForeignKey("trasporti_viaggi.id"), nullable=False, index=True)
    tappa_id = Column(Integer, ForeignKey("trasporto_tappe.id"), nullable=True, index=True)
    tipo_attrezzatura = Column(String(100), nullable=False, index=True)
    quantita = Column(Integer, nullable=False, default=1)

    viaggio = relationship("TrasportoViaggio", back_populates="richieste_attrezzature")
    tappa = relationship("TrasportoTappa", back_populates="richieste_attrezzature")


class TrasportoAttrezzaturaViaggio(Base):
    __tablename__ = "trasporto_attrezzature_viaggio"
    __table_args__ = (
        UniqueConstraint("viaggio_id", "attrezzatura_id", name="uq_trasporto_viaggio_attrezzatura"),
    )

    id = Column(Integer, primary_key=True, index=True)
    viaggio_id = Column(Integer, ForeignKey("trasporti_viaggi.id"), nullable=False, index=True)
    attrezzatura_id = Column(Integer, ForeignKey("attrezzature.id"), nullable=False, index=True)
    tappa_destinazione_id = Column(Integer, ForeignKey("trasporto_tappe.id"), nullable=True, index=True)
    caricato = Column(Boolean, nullable=False, default=False)
    scaricato = Column(Boolean, nullable=False, default=False)

    viaggio = relationship("TrasportoViaggio", back_populates="assegnazioni_attrezzature")
    attrezzatura = relationship("Attrezzatura")
    tappa_destinazione = relationship("TrasportoTappa")


class MovimentoAttrezzatura(Base):
    __tablename__ = "movimenti_attrezzature"

    id = Column(Integer, primary_key=True, index=True)
    attrezzatura_id = Column(Integer, ForeignKey("attrezzature.id"), nullable=False, index=True)
    viaggio_id = Column(Integer, ForeignKey("trasporti_viaggi.id"), nullable=False, index=True)
    origine_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    origine_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True, index=True)
    destinazione_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    destinazione_depot_id = Column(Integer, ForeignKey("depots.id"), nullable=True, index=True)
    origine = Column(String(255), nullable=False)
    destinazione = Column(String(255), nullable=False)
    data = Column(DateTime, nullable=False, default=datetime.utcnow)
    autista_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    attrezzatura = relationship("Attrezzatura")
    viaggio = relationship("TrasportoViaggio")
    autista = relationship("User")
    origine_site = relationship("Site", foreign_keys=[origine_site_id])
    origine_depot = relationship("Depot", foreign_keys=[origine_depot_id])
    destinazione_site = relationship("Site", foreign_keys=[destinazione_site_id])
    destinazione_depot = relationship("Depot", foreign_keys=[destinazione_depot_id])
