from datetime import date
from typing import Optional, List, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from models import RoleEnum, SiteStatusEnum, MachineTypeEnum, FicheTypeEnum


# ---------- UTENTI ----------

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    language: str = "it"


class UserCreate(UserBase):
    password: str
    role: RoleEnum


class UserRead(UserBase):
    id: int
    role: RoleEnum
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ---------- AUTH ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- CANTIERI ----------

class SiteBase(BaseModel):
    name: str
    location: Optional[str] = None
    status: SiteStatusEnum = SiteStatusEnum.aperto
    progress: int = Field(0, ge=0, le=100)
    description: Optional[str] = None


class SiteCreate(SiteBase):
    pass


class SiteRead(SiteBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- MACCHINARI ----------

class MachineBase(BaseModel):
    name: str
    code: Optional[str] = None
    machine_type: Optional[MachineTypeEnum] = Field(default=None, alias="type")
    brand: Optional[str] = None
    model_name: Optional[str] = Field(default=None, alias="model")
    plate: Optional[str] = None
    notes: Optional[str] = None
    status: str
    site_id: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)


class MachineCreate(MachineBase):
    pass


class MachineRead(MachineBase):
    id: int

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MachineIssueUpdate(BaseModel):
    issue_notes: Optional[str] = None
    has_issue: bool = True


# ---------- RAPPORTINI ----------

class DailyReportBase(BaseModel):
    site_id: int
    date: Optional[date] = None
    weather: Optional[str] = None
    num_workers: int = 0
    hours_worked: float = 0.0
    notes: Optional[str] = None


class DailyReportCreate(DailyReportBase):
    pass


class DailyReportRead(DailyReportBase):
    id: int
    author_id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- FICHES + STRATIGRAFIA ----------

class FicheCreate(BaseModel):
    date: date
    site_id: int
    numero_pannello: int = Field(..., gt=0)
    machine_id: Optional[int] = None
    capocantiere_id: Optional[int] = None
    fiche_type: FicheTypeEnum
    description: str
    operator: Optional[str] = None
    hours: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    tipologia_scavo: Optional[str] = None
    materiale: Optional[str] = None
    profondita_totale: Optional[float] = Field(default=None, gt=0)
    diametro_palo: Optional[float] = Field(default=None, gt=0)
    larghezza_pannello: Optional[float] = Field(default=None, gt=0)
    altezza_pannello: Optional[float] = Field(default=None, gt=0)
    data_getto: Optional[date] = None
    metri_cubi_gettati: float = Field(..., ge=0)
    courbe_beton_active: bool = False
    courbe_beton_realisee: Optional[List[dict[str, Any]]] = None
    courbe_beton_tube: Optional[List[dict[str, Any]]] = None
    courbe_beton_volume_total: Optional[float] = Field(default=None, ge=0)
    courbe_beton_hauteur_initiale: Optional[float] = None
    courbe_beton_hauteur_finale: Optional[float] = 0

    model_config = {"from_attributes": True}


class FicheRead(BaseModel):
    id: int
    date: date
    site_id: int
    numero_pannello: int
    machine_id: Optional[int]
    capocantiere_id: Optional[int] = None
    fiche_type: FicheTypeEnum
    description: str
    operator: Optional[str]
    hours: Optional[float]
    notes: Optional[str]
    tipologia_scavo: Optional[str] = None
    stratigrafia: Optional[str] = None
    materiale: Optional[str] = None
    profondita_totale: Optional[float] = None
    diametro_palo: Optional[float] = None
    larghezza_pannello: Optional[float] = None
    altezza_pannello: Optional[float] = None
    data_getto: Optional[date] = None
    metri_cubi_gettati: Optional[float] = None
    quota_ngf_testa: Optional[float] = None
    quota_ngf_fondo: Optional[float] = None
    quota_ngf_note: Optional[str] = None
    courbe_beton_active: bool = False
    courbe_beton_realisee: Optional[List[dict[str, Any]]] = None
    courbe_beton_tube: Optional[List[dict[str, Any]]] = None
    courbe_beton_volume_total: Optional[float] = None
    courbe_beton_hauteur_initiale: Optional[float] = None
    courbe_beton_hauteur_finale: Optional[float] = None
    site_name: str
    machine_name: Optional[str]
    capocantiere_name: Optional[str] = None
    created_by_name: str
    created_by_role: str

    model_config = {"from_attributes": True}


class FicheListItem(BaseModel):
    id: int
    date: date
    site_name: str
    numero_pannello: int
    machine_name: Optional[str]
    fiche_type: FicheTypeEnum
    operator: Optional[str]
    hours: Optional[float]
    tipologia_scavo: Optional[str] = None
    stratigrafia: Optional[str] = None
    materiale: Optional[str] = None
    profondita_totale: Optional[float] = None
    diametro_palo: Optional[float] = None
    larghezza_pannello: Optional[float] = None
    altezza_pannello: Optional[float] = None
    data_getto: Optional[date] = None
    metri_cubi_gettati: Optional[float] = None
    created_by_name: str

    model_config = {"from_attributes": True}
