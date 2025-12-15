from datetime import date
from typing import Optional, List

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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


# ---------- FICHES + STRATIGRAFIA ----------

class FicheCreate(BaseModel):
    date: date
    site_id: int
    machine_id: Optional[int] = None
    fiche_type: FicheTypeEnum
    description: str
    operator: Optional[str] = None
    hours: float
    notes: Optional[str] = None
    tipologia_scavo: Optional[str] = None
    stratigrafia: Optional[str] = None
    materiale: Optional[str] = None

    model_config = {"from_attributes": True}


class FicheRead(BaseModel):
    id: int
    date: date
    site_id: int
    machine_id: Optional[int]
    fiche_type: FicheTypeEnum
    description: str
    operator: Optional[str]
    hours: float
    notes: Optional[str]
    tipologia_scavo: Optional[str] = None
    stratigrafia: Optional[str] = None
    materiale: Optional[str] = None
    site_name: str
    machine_name: Optional[str]
    created_by_name: str
    created_by_role: str

    model_config = {"from_attributes": True}


class FicheListItem(BaseModel):
    id: int
    date: date
    site_name: str
    machine_name: Optional[str]
    fiche_type: FicheTypeEnum
    operator: Optional[str]
    hours: float
    tipologia_scavo: Optional[str] = None
    stratigrafia: Optional[str] = None
    materiale: Optional[str] = None
    created_by_name: str

    model_config = {"from_attributes": True}
