from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import User, RoleEnum
from permissions import has_perm
from auth import get_current_active_user, hash_password

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


# ---------------------------
# SCHEMI Pydantic
# ---------------------------

class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None
    role: RoleEnum
    language: str | None = "it"


class UserOut(UserBase):
    id: int

    class Config:
        orm_mode = True


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: RoleEnum
    language: str | None = "it"


# ---------------------------
# ENDPOINTS
# ---------------------------


@router.get("/", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Restituisce la lista di tutti gli utenti.
    Accesso consentito agli utenti con permesso di lettura.
    """
    if not (
        has_perm(current_user, "users.read")
        and has_perm(current_user, "manager.access")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per vedere la lista utenti.",
        )

    users = db.query(User).order_by(User.id).all()
    return users


@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Crea un nuovo utente.
    Solo admin.
    """
    if not has_perm(current_user, "users.create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per creare nuovi utenti.",
        )

    # Controllo se l'email esiste già
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esiste già un utente con questa email.",
        )

    if len(user_in.password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La password deve avere almeno 4 caratteri.",
        )

    db_user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        role=user_in.role,
        language=user_in.language or "it",
        hashed_password=hash_password(user_in.password),
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.get("/me", response_model=UserOut)
def read_current_user(
    current_user: User = Depends(get_current_active_user),
):
    """
    Restituisce i dati dell'utente corrente (dal token).
    Utile per debug o per sapere chi è loggato.
    """
    return current_user
