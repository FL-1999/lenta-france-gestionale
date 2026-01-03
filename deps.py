from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database import get_db
from models import Site, User, RoleEnum
from auth import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Non autenticato",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != RoleEnum.admin:
        raise HTTPException(status_code=403, detail="Solo admin")
    return current_user


def require_manager_or_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Solo manager o admin")
    return current_user


def require_caposquadra_or_above(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")
    return current_user


def scope_sites_query(query, current_user: User):
    if current_user.role == RoleEnum.caposquadra:
        return query.filter(Site.caposquadra_id == current_user.id)
    return query


def get_site_for_user(db: Session, site_id: int, current_user: User) -> Site:
    query = db.query(Site).filter(Site.id == site_id)
    query = scope_sites_query(query, current_user)
    site = query.first()
    if site:
        return site
    if current_user.role == RoleEnum.caposquadra:
        exists = db.query(Site.id).filter(Site.id == site_id).first()
        if exists:
            raise HTTPException(status_code=403, detail="Cantiere non assegnato")
    raise HTTPException(status_code=404, detail="Cantiere non trovato")


def get_authorized_site(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_caposquadra_or_above),
) -> Site:
    return get_site_for_user(db, site_id, current_user)
