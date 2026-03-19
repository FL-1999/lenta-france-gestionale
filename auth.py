import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import RoleEnum, User, UserRole
from permissions import get_active_role, get_user_roles, has_perm, user_has_role

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    warnings.warn(
        "SECRET_KEY non impostata: utilizzare una variabile d'ambiente in produzione",
        RuntimeWarning,
    )
    SECRET_KEY = "changeme"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class Token(BaseModel):
    access_token: str = Field(...)
    token_type: str = Field(default="bearer")
    active_role: Optional[str] = Field(default=None)
    available_roles: list[str] = Field(default_factory=list)
    can_switch_roles: bool = Field(default=False)
    redirect_url: Optional[str] = Field(default=None)


class TokenData(BaseModel):
    email: Optional[EmailStr] = Field(default=None)
    role: Optional[str] = Field(default=None)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def get_redirect_for_role(role: RoleEnum | str | None) -> str:
    try:
        normalized_role = role if isinstance(role, RoleEnum) else RoleEnum(str(role))
    except Exception:
        return "/"

    if normalized_role in (RoleEnum.admin, RoleEnum.manager):
        return "/manager/dashboard"
    if normalized_role == RoleEnum.driver:
        return "/driver/trasporti/viaggi"
    if normalized_role == RoleEnum.magazzino:
        return "/manager/magazzino/dashboard"
    if normalized_role == RoleEnum.caposquadra:
        return "/capo/dashboard"
    return "/"


def get_role_redirect_url(role: RoleEnum | str | None) -> str:
    return get_redirect_for_role(role)


def can_switch_user_role(user: User | None) -> bool:
    if not user:
        return False
    return bool(getattr(user, "can_switch_roles", False) and len(get_assigned_roles(user)) > 1)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return (
        db.query(User)
        .options(joinedload(User.user_roles).joinedload(UserRole.role))
        .filter(User.email == email)
        .first()
    )


def get_assigned_roles(user: User | None) -> tuple[RoleEnum, ...]:
    if not user:
        return tuple()

    collected: list[RoleEnum] = []
    seen: set[RoleEnum] = set()
    for user_role in getattr(user, "user_roles", []) or []:
        role_obj = getattr(user_role, "role", None)
        role_name = getattr(role_obj, "name", None)
        if role_name is None or role_name in seen:
            continue
        seen.add(role_name)
        collected.append(role_name)
    return tuple(collected)


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email=email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def resolve_user_active_role(
    user: User,
    requested_role: RoleEnum | str | None = None,
) -> RoleEnum:
    available_roles = list(get_assigned_roles(user))
    if not available_roles:
        fallback_role = get_active_role(user)
        if fallback_role is not None:
            available_roles = [fallback_role]
    if not available_roles:
        return RoleEnum.caposquadra

    normalized_requested_role = None
    if requested_role is not None:
        try:
            normalized_requested_role = (
                requested_role
                if isinstance(requested_role, RoleEnum)
                else RoleEnum(str(requested_role))
            )
        except Exception:
            normalized_requested_role = None

    if normalized_requested_role and normalized_requested_role in available_roles:
        if user.role != normalized_requested_role:
            user.role = normalized_requested_role
        return normalized_requested_role

    current_role = get_active_role(user)
    if current_role in available_roles:
        return current_role

    first_role = available_roles[0]
    if user.role != first_role:
        user.role = first_role
    return first_role


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide o token mancante",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        token_role = payload.get("role")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception

    resolved_role = resolve_user_active_role(user, token_role)
    if token_role and not user_has_role(user, token_role):
        raise credentials_exception
    user.role = resolved_role
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if hasattr(current_user, "is_active") and current_user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utente disattivato",
        )
    return current_user


async def get_current_user_html(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    redirect_exception = HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/login"},
    )

    cookie_token = request.cookies.get("access_token")
    if not cookie_token:
        raise redirect_exception

    token = cookie_token
    if token.startswith("Bearer "):
        token = token[len("Bearer ") :]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        token_role = payload.get("role")
        if email is None:
            raise redirect_exception
    except JWTError:
        raise redirect_exception

    user = get_user_by_email(db, email=email)
    if user is None:
        raise redirect_exception
    if token_role and not user_has_role(user, token_role):
        raise redirect_exception
    user.role = resolve_user_active_role(user, token_role)
    return user


async def get_current_active_user_html(
    current_user: Annotated[User, Depends(get_current_user_html)],
) -> User:
    if hasattr(current_user, "is_active") and current_user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utente disattivato",
        )
    return current_user


async def get_current_manager_user(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti per questa operazione",
        )
    return current_user


router = APIRouter(prefix="/auth", tags=["auth"])


def _generate_token_for_user(
    user: User,
    *,
    redirect_url: str | None = None,
    requested_role: RoleEnum | str | None = None,
) -> Token:
    active_role = resolve_user_active_role(user, requested_role)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    available_roles = [role.value for role in get_user_roles(user)]
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": active_role.value,
            "roles": available_roles,
            "can_switch_roles": can_switch_user_role(user),
        },
        expires_delta=access_token_expires,
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        active_role=active_role.value,
        available_roles=available_roles,
        can_switch_roles=can_switch_user_role(user),
        redirect_url=redirect_url or get_redirect_for_role(active_role),
    )


@router.post("/token", response_model=Token)
async def login_for_access_token_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    user = authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti oppure utente disattivato",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(status_code=400, detail="Utente disattivato")
    return _generate_token_for_user(user)


@router.post("/login", response_model=Token)
async def login_json(
    login_data: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
):
    user = authenticate_user(db, email=login_data.email, password=login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti oppure utente disattivato",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(status_code=400, detail="Utente disattivato")
    return _generate_token_for_user(user)


@router.get("/me")
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    active_role = get_active_role(current_user)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": getattr(current_user, "full_name", None),
        "role": active_role.value if active_role else None,
        "roles": [role.value for role in get_user_roles(current_user)],
        "can_switch_roles": can_switch_user_role(current_user),
        "language": getattr(current_user, "language", None),
    }
