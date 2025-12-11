from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import User, RoleEnum

# =====================================
# CONFIGURAZIONE JWT
# =====================================

# 👉 Cambiala in produzione con una stringa lunga e segreta
SECRET_KEY = "cambia-questa-chiave-super-segreta-lenta-france-2025"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 ora


# =====================================
# PASSWORD HASHING (pbkdf2_sha256)
# =====================================

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Restituisce la versione hashata della password.
    Usata in main.py per creare/aggiornare l'admin iniziale.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Confronta password in chiaro con l'hash salvato nel DB.
    """
    return pwd_context.verify(plain_password, hashed_password)


# =====================================
# SCHEMI TOKEN
# =====================================

# Usato per OAuth2PasswordBearer (Swagger, dipendenze back-end)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


# Schema per login JSON dal frontend
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# =====================================
# FUNZIONI DI AUTENTICAZIONE
# =====================================

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Controlla che l'utente esista e che la password sia corretta.
    """
    user = get_user_by_email(db, email=email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un JWT con i dati forniti (es. {"sub": email, "role": "admin"}).
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# =====================================
# DIPENDENZE PER OTTENERE L'UTENTE CORRENTE
# =====================================

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Legge il token, decodifica la mail, carica l'utente dal DB.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide o token mancante",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception

    user = get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Qui puoi controllare se l'utente è attivo o meno.
    Per ora assumiamo che tutti gli utenti siano attivi.
    """
    # Se in models.User hai un campo "is_active", puoi fare:
    # if not current_user.is_active:
    #     raise HTTPException(status_code=400, detail="Utente disabilitato")
    return current_user


# Se in futuro vuoi un controllo solo per ADMIN / MANAGER:
async def get_current_manager_user(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """
    Dipendenza che accetta solo admin/manager.
    """
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti per questa operazione",
        )
    return current_user


# =====================================
# ROUTER FASTAPI
# =====================================

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
async def login_for_access_token_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Endpoint di login in stile OAuth2 (usato da Swagger /docs).
    - riceve username e password (username = email)
    - se ok, restituisce un JWT
    """
    user = authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Mettiamo NEL TOKEN anche il ruolo,
    # così il frontend può leggere decoded.role
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        },
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.post("/login", response_model=Token)
async def login_json(
    login_data: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Endpoint di login per il frontend:
    - riceve JSON { "email": "...", "password": "..." }
    - restituisce lo stesso token di /auth/token
    """
    user = authenticate_user(db, email=login_data.email, password=login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        },
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Restituisce le info dell'utente loggato.
    Utile per testare che il token funzioni.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": getattr(current_user, "full_name", None),
        "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        "language": getattr(current_user, "language", None),
    }
