from pydantic import BaseModel, EmailStr, Field
from datetime import date
from typing import Optional, List

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
    model: Optional[str] = None
    type: MachineTypeEnum
    current_site_id: Optional[int] = None
    notes: Optional[str] = None


class MachineCreate(MachineBase):
    pass


class MachineRead(MachineBase):
    id: int
    has_issue: bool
    issue_notes: Optional[str] = None

    class Config:
        from_attributes = True


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

class StratigraphyLayerBase(BaseModel):
    from_m: float
    to_m: float
    description: Optional[str] = None


class StratigraphyLayerCreate(StratigraphyLayerBase):
    pass


class StratigraphyLayerRead(StratigraphyLayerBase):
    id: int

    class Config:
        from_attributes = True


class FicheBase(BaseModel):
    site_id: int
    machine_id: Optional[int] = None
    type: FicheTypeEnum
    panel_number: Optional[str] = None

    # pali
    diameter_mm: Optional[int] = None
    total_depth_m: Optional[float] = None

    # paratie
    paratia_depth_m: Optional[float] = None
    paratia_width_m: Optional[float] = None

    dig_date: Optional[date] = None
    cast_date: Optional[date] = None


class FicheCreate(FicheBase):
    layers: List[StratigraphyLayerCreate] = []


class FicheRead(FicheBase):
    id: int
    layers: List[StratigraphyLayerRead] = []

    class Config:
        from_attributes = True
