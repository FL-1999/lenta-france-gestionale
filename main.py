import logging
import os
import time
import re
import uuid
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta
from math import ceil
from typing import List

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from jose import JWTError, jwt

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import joinedload, load_only, Session
from sqlmodel import SQLModel

from database import Base, engine, SessionLocal, get_db
from auth import (
    router as auth_router,
    hash_password,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_current_active_user_api,
    get_current_active_user_html,
    get_current_role_from_request,
    get_default_route,
    get_user_by_email,
    resolve_user_active_role,
    set_current_role_cookie,
    _generate_token_for_user,
    get_redirect_for_role,
    can_switch_user_role,
    CURRENT_ROLE_COOKIE_NAME,
    SECRET_KEY,
    ALGORITHM,
)
from deps import get_site_for_user, scope_sites_query
from models import (
    User,
    Role,
    UserRole,
    RoleEnum,
    Report,
    Site,
    SiteTask,
    SiteTaskPriorityEnum,
    SiteTaskStatusEnum,
    SiteStrutLevel,
    SiteStatusEnum,
    Machine,
    FicheTypeEnum,
    Fiche,
    FicheStratigrafia,
    Personale,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    TrasportoViaggio,
    TrasportoTappa,
    TrasportoRichiestaAttrezzatura,
    TrasportoStatoEnum,
    Attrezzatura,
    AttrezzaturaStatoEnum,
    TrasportoAttrezzaturaViaggio,
    Depot,
)
from routers import users, sites, machines, reports, fiches, notifications
from routes import manager_personale, manager_veicoli, manager_depositi, magazzino, ordini, audit, reportistica, backup, trasporti, economics

from template_context import (
    build_template_context,
    get_cached_role_choices,
    get_cached_site_status_values,
    get_lang_from_request,
    register_manager_badges,
    register_permission_helpers,
    register_static_helpers,
    render_template,
)
from permissions import get_active_role, get_user_roles, has_perm, user_has_role
from notifications import notify_site_status_change
from audit_utils import log_audit_event
from logging_config import configure_logging

from db_upgrade import upgrade_db, check_db_schema
from utils.db_check import check_and_suggest_db_upgrade
from utils.trips import compute_trip_progress


configure_logging()

logger = logging.getLogger("lenta_france_gestionale.errors")
perf_logger = logging.getLogger("lenta_france_gestionale.performance")

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100
SITE_TASK_STATUSES = (
    SiteTaskStatusEnum.da_fare,
    SiteTaskStatusEnum.in_corso,
    SiteTaskStatusEnum.completato,
)
SITE_TASK_PRIORITIES = (
    SiteTaskPriorityEnum.bassa,
    SiteTaskPriorityEnum.media,
    SiteTaskPriorityEnum.alta,
)
APP_ENV = (
    os.getenv("APP_ENV")
    or os.getenv("ENVIRONMENT")
    or os.getenv("FASTAPI_ENV")
    or "development"
).strip().lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _get_or_create_role(db: Session, role: RoleEnum) -> Role:
    role_obj = db.query(Role).filter(Role.name == role).first()
    if role_obj:
        return role_obj
    role_obj = Role(name=role, description=f"Ruolo {role.value}")
    db.add(role_obj)
    db.flush()
    return role_obj


def _sync_user_roles(db: Session, user: User, roles: list[RoleEnum]) -> list[RoleEnum]:
    unique_roles: list[RoleEnum] = []
    seen: set[RoleEnum] = set()
    for role in roles:
        if role in seen:
            continue
        seen.add(role)
        unique_roles.append(role)

    if not unique_roles:
        raise ValueError("At least one role is required")

    existing_links = {link.role.name: link for link in (user.user_roles or []) if link.role}
    desired = set(unique_roles)

    for role in list(existing_links):
        if role not in desired:
            db.delete(existing_links[role])

    for role in unique_roles:
        if role in existing_links:
            continue
        db.add(UserRole(user=user, role=_get_or_create_role(db, role)))

    db.flush()
    db.refresh(user)
    return unique_roles


def _resolve_post_login_role(
    user: User,
    requested_role: RoleEnum | str | None = None,
) -> RoleEnum:
    return resolve_user_active_role(user, requested_role)


def _apply_access_token_cookie(
    response: RedirectResponse,
    access_token: str,
    active_role: RoleEnum | str | None = None,
) -> None:
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=60 * 60,
        path="/",
        samesite="lax",
    )
    set_current_role_cookie(response, active_role)


# -------------------------------------------------
# CREAZIONE TABELLE + ADMIN INIZIALE
# -------------------------------------------------

AUTO_FIX = os.getenv("DB_AUTO_FIX", "false").lower() == "true"
RUN_DB_CHECK = os.getenv("RUN_DB_CHECK", "false").lower() == "true"
DEBUG_DB_SCHEMA_CHECK = os.getenv("DEBUG_DB_SCHEMA_CHECK", "0") == "1"

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
ADMIN_LANGUAGE = os.getenv("ADMIN_LANGUAGE", "it")


def create_initial_admin():
    """
    Crea o aggiorna l'utente admin iniziale usando credenziali
    deterministiche.

    Per motivi di sicurezza le credenziali vengono lette da variabili
    d'ambiente (ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_LANGUAGE). Se non
    sono presenti, viene usato il fallback sicuro fornito.
    """
    admin_email = ADMIN_EMAIL or "lenta.federico@gmail.com"
    admin_password = ADMIN_PASSWORD or "Fulvio72"
    admin_language = ADMIN_LANGUAGE or "it"

    db = SessionLocal()
    hashed_password = hash_password(admin_password)
    try:
        admin = db.query(User).filter(User.email == admin_email).first()
        if admin:
            admin.full_name = admin.full_name or admin_email
            admin.role = RoleEnum.admin
            admin.language = admin_language
            admin.is_active = True
            admin.hashed_password = hashed_password
            message = "Admin iniziale aggiornato."
        else:
            admin = User(
                email=admin_email,
                full_name=admin_email,
                role=RoleEnum.admin,
                language=admin_language,
                hashed_password=hashed_password,
                is_active=True,
                can_switch_roles=False,
            )
            db.add(admin)
            db.flush()
            message = "Admin iniziale creato."

        _sync_user_roles(db, admin, [RoleEnum.admin])
        db.commit()
        print(message)
    except Exception as exc:
        db.rollback()
        print(f"Errore nella creazione/aggiornamento dell'admin iniziale: {exc}")
    finally:
        db.close()


def initialize_application() -> None:
    """Initialize database schema and bootstrap required data at startup."""
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)
    logger.info("Schema di base inizializzato.")


def run_post_startup_tasks() -> None:
    """Run idempotent maintenance tasks that are not required for port readiness."""
    logger.info("Avvio post-startup tasks (non bloccanti).")
    upgrade_db(engine)

    if DEBUG_DB_SCHEMA_CHECK:
        check_db_schema(engine)

    if RUN_DB_CHECK:
        check_and_suggest_db_upgrade(engine, Base, auto_fix=AUTO_FIX)

    create_initial_admin()
    logger.info("Post-startup tasks completati.")


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_cors_origins(raw: str | None) -> list[str]:
    if not raw:
        return []
    if raw.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def build_cors_settings() -> dict:
    raw_origins = os.getenv("CORS_ALLOW_ORIGINS")
    allow_origins = _parse_cors_origins(raw_origins)
    allow_credentials = _parse_bool_env("CORS_ALLOW_CREDENTIALS", True)
    allow_methods = _parse_cors_origins(os.getenv("CORS_ALLOW_METHODS")) or ["*"]
    allow_headers = _parse_cors_origins(os.getenv("CORS_ALLOW_HEADERS")) or ["*"]

    if IS_PRODUCTION:
        if not allow_origins or allow_origins == ["*"]:
            logger.error(
                "CORS produzione non valido: CORS_ALLOW_ORIGINS deve contenere origini esplicite (APP_ENV=%s).",
                APP_ENV,
            )
            raise RuntimeError("CORS_ALLOW_ORIGINS obbligatoria e non wildcard in production.")
    else:
        if not allow_origins:
            allow_origins = ["*"]

    if allow_credentials and "*" in allow_origins:
        if IS_PRODUCTION:
            logger.error(
                "CORS produzione incoerente: allow_credentials=true non compatibile con wildcard origin."
            )
            raise RuntimeError("Configurazione CORS non valida in production.")
        logger.warning(
            "CORS sviluppo: disabilito allow_credentials perché allow_origins contiene wildcard."
        )
        allow_credentials = False

    logger.info(
        "CORS configurato (env=%s, origins=%s, credentials=%s)",
        APP_ENV,
        ",".join(allow_origins),
        allow_credentials,
    )
    return {
        "allow_origins": allow_origins,
        "allow_credentials": allow_credentials,
        "allow_methods": allow_methods,
        "allow_headers": allow_headers,
    }


# -------------------------------------------------
# APP FASTAPI
# -------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup applicazione avviato (env=%s).", APP_ENV)
    initialize_application()
    post_startup_task = asyncio.create_task(asyncio.to_thread(run_post_startup_tasks))
    app.state.post_startup_task = post_startup_task
    logger.info("Startup applicazione completato (task pesanti deferiti in background).")
    try:
        yield
    finally:
        task = getattr(app.state, "post_startup_task", None)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

app = FastAPI(
    title="Lenta France Gestionale",
    description="Gestionale cantieri, macchinari, fiches e rapportini.",
    version="1.0.0",
    lifespan=lifespan,
)
cors_settings = build_cors_settings()
app.add_middleware(CORSMiddleware, **cors_settings)

_HASHED_ASSET_RE = re.compile(r"\\.[0-9a-f]{8,}\\.")


@app.middleware("http")
async def add_static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        if request.url.path == "/static/css/style.css":
            response.headers["Cache-Control"] = "no-cache"
        elif "v" in request.query_params or _HASHED_ASSET_RE.search(request.url.path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=86400"
    return response

# Static (CSS, immagini, JS)
app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

# Templates HTML (Jinja2)
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
register_static_helpers(templates)
register_permission_helpers(templates)


# -------------------------------------------------
# REQUEST ID + ERROR HANDLERS
# -------------------------------------------------

def _get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id or "unknown"


def _build_error_context(request: Request, status_code: int) -> dict:
    context = build_template_context(
        request,
        None,
        status_code=status_code,
        request_id=_get_request_id(request),
    )
    if not isinstance(context, dict):
        context = dict(context or {})
    else:
        context = dict(context)
    context["request"] = request
    context["status_code"] = status_code
    context["request_id"] = _get_request_id(request)
    return context


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = _get_request_id(request)
    status_code = exc.status_code
    logger.warning(
        "HTTP error %s %s -> %s (request_id=%s)",
        request.method,
        request.url.path,
        status_code,
        request_id,
    )

    exception_headers = dict(getattr(exc, "headers", {}) or {})

    if 300 <= status_code < 400 and exception_headers.get("Location"):
        response = RedirectResponse(
            url=exception_headers["Location"],
            status_code=status_code,
            headers=exception_headers,
        )
    elif status_code == status.HTTP_403_FORBIDDEN:
        response = templates.TemplateResponse(
            request,
            "errors/403.html",
            _build_error_context(request, status_code),
            status_code=status_code,
        )
    elif status_code == status.HTTP_404_NOT_FOUND:
        response = templates.TemplateResponse(
            request,
            "errors/404.html",
            _build_error_context(request, status_code),
            status_code=status_code,
        )
    else:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": exc.detail},
            headers=exception_headers,
        )

    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = _get_request_id(request)
    logger.exception(
        "Unhandled error %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
    )
    context = _build_error_context(request, status.HTTP_500_INTERNAL_SERVER_ERROR)

    response = templates.TemplateResponse(
        request,
        "errors/500.html",
        context,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    response.headers["X-Request-ID"] = request_id
    return response


# -------------------------------------------------
# MULTILINGUA (COOKIE) + HOMEPAGE TEMPLATE
# -------------------------------------------------
def _get_user_from_cookie(request: Request) -> User | None:
    cookie_token = request.cookies.get("access_token")
    if not cookie_token:
        return None

    token = cookie_token
    if token.startswith("Bearer "):
        token = token[len("Bearer ") :]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    email = payload.get("sub")
    if not email:
        return None

    db = SessionLocal()
    try:
        user = get_user_by_email(db, email=email)
        if user and getattr(user, "is_active", True):
            return user
    finally:
        db.close()
    return None


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    """
    Homepage con selezione lingua, login e accesso dashboard.
    Usa il template 'home.html'.
    """
    current_user = _get_user_from_cookie(request)
    if current_user:
        requested_role = get_current_role_from_request(request)
        destination = get_default_route(current_user, requested_role)
        return RedirectResponse(url=destination, status_code=303)

    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        request,
        "home.html",
        build_template_context(
            request,
            None,
            lang=lang,
        ),
    )

@app.get("/offline", response_class=HTMLResponse)
def offline(request: Request):
    """
    Pagina di fallback per modalità offline (PWA).
    """
    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        request,
        "offline.html",
        build_template_context(
            request,
            None,
            lang=lang,
            title="Sei offline",
            nuove_richieste_count=0,
        ),
    )


@app.get("/set-lang")
def set_lang(lang: str = "it"):
    """
    Imposta la lingua (it / fr) nel cookie e torna alla homepage.
    """
    if lang not in ("it", "fr"):
        lang = "it"
    response = RedirectResponse(url="/")
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response


@app.get("/set-language/{lang_code}")
async def set_language(lang_code: str, request: Request):
    """
    Set UI language via cookie and redirect back to the previous page.
    """
    lang = lang_code.lower()
    if lang not in ("it", "fr"):
        lang = "it"

    referer = request.headers.get("referer") or "/"
    response = RedirectResponse(url=referer, status_code=303)
    # Cookie non-HttpOnly per poterlo leggere anche lato client se necessario
    response.set_cookie(
        key="lang",
        value=lang,
        max_age=60 * 60 * 24 * 365,  # 1 year
        secure=False,
        httponly=False,
        samesite="lax",
    )
    return response


# -------------------------------------------------
# VALIDAZIONE DATI FICHE
# -------------------------------------------------

def _validate_fiche_geometria(
    diametro_palo_cm: float | None,
    larghezza_pannello: float | None,
    altezza_pannello: float | None,
    profondita_totale: float | None,
) -> None:
    has_diametro = diametro_palo_cm is not None
    has_larghezza = larghezza_pannello is not None
    has_altezza = altezza_pannello is not None

    if diametro_palo_cm is not None and diametro_palo_cm <= 0:
        raise HTTPException(
            status_code=400,
            detail="Il diametro del palo deve essere maggiore di zero.",
        )

    if larghezza_pannello is not None and larghezza_pannello <= 0:
        raise HTTPException(
            status_code=400,
            detail="La larghezza del pannello deve essere maggiore di zero.",
        )

    if altezza_pannello is not None and altezza_pannello <= 0:
        raise HTTPException(
            status_code=400,
            detail="L'altezza del pannello deve essere maggiore di zero.",
        )

    if profondita_totale is not None and profondita_totale <= 0:
        raise HTTPException(
            status_code=400,
            detail="La profondità totale deve essere maggiore di zero.",
        )

    if has_diametro and (has_larghezza or has_altezza):
        raise HTTPException(
            status_code=400,
            detail=(
                "Se inserisci il diametro del palo, lascia vuote le misure del pannello."
            ),
        )

    if has_larghezza or has_altezza:
        if not (has_larghezza and has_altezza):
            raise HTTPException(
                status_code=400,
                detail="Per il pannello devi indicare sia larghezza sia altezza.",
            )
        if has_diametro:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Se compili larghezza e altezza del pannello, il diametro del palo deve restare vuoto."
                ),
            )

    if (has_diametro or has_larghezza or has_altezza) and profondita_totale is None:
        raise HTTPException(
            status_code=400,
            detail="Se compili i dati geometrici devi indicare anche la profondità totale.",
        )


def _build_fiche_form_data(
    cantiere_id: int | str | None = None,
    macchinario_id: int | str | None = None,
    data_scavo: date | None = None,
    data_getto: date | None = None,
    metri_cubi_gettati: float | None = None,
    operatore: str | None = None,
    descrizione: str | None = None,
    ore_lavorate: float | None = None,
    note: str | None = None,
    tipologia_scavo: str | None = None,
    stratigrafia: str | None = None,
    materiale: str | None = None,
    profondita_totale: float | None = None,
    diametro_palo: float | None = None,
    diametro_palo_cm: float | None = None,
    larghezza_pannello: float | None = None,
    altezza_pannello: float | None = None,
    strato_da: list[float] | None = None,
    strato_a: list[float] | None = None,
    strato_materiale: list[str] | None = None,
) -> dict:
    def _fmt(value):
        return "" if value is None else str(value)

    strato_da = strato_da or []
    strato_a = strato_a or []
    strato_materiale = strato_materiale or []

    max_len = max(len(strato_da), len(strato_a), len(strato_materiale), 1)
    strati = []
    for i in range(max_len):
        strati.append(
            {
                "da": _fmt(strato_da[i]) if i < len(strato_da) else "",
                "a": _fmt(strato_a[i]) if i < len(strato_a) else "",
                "materiale": _fmt(strato_materiale[i])
                if i < len(strato_materiale)
                else "",
            }
        )

    cm_value = diametro_palo_cm
    if cm_value is None and diametro_palo is not None:
        cm_value = round(diametro_palo * 100, 1)

    return {
        "cantiere_id": _fmt(cantiere_id),
        "macchinario_id": _fmt(macchinario_id),
        "data_scavo": data_scavo.isoformat() if data_scavo else "",
        "data_getto": data_getto.isoformat() if data_getto else "",
        "metri_cubi_gettati": _fmt(metri_cubi_gettati),
        "operatore": operatore or "",
        "descrizione": descrizione or "",
        "ore_lavorate": _fmt(ore_lavorate),
        "note": note or "",
        "tipologia_scavo": tipologia_scavo or "",
        "stratigrafia": stratigrafia or "",
        "materiale": materiale or "",
        "profondita_totale": _fmt(profondita_totale),
        "diametro_palo": _fmt(diametro_palo),
        "diametro_palo_cm": _fmt(cm_value),
        "larghezza_pannello": _fmt(larghezza_pannello),
        "altezza_pannello": _fmt(altezza_pannello),
        "strati": strati,
    }


def _load_capo_form_collections(current_user: User) -> tuple[list[Site], list[Machine]]:
    db = SessionLocal()
    try:
        sites = _get_capo_assigned_sites(db, current_user)
        allowed_site_ids = [s.id for s in sites]

        machines_query = db.query(Machine).filter(Machine.is_active.is_(True))
        if allowed_site_ids:
            machines_query = machines_query.filter(Machine.site_id.in_(allowed_site_ids))
        machines = machines_query.order_by(Machine.name.asc()).all()
        return sites, machines
    finally:
        db.close()


def _load_manager_form_collections() -> tuple[list[Site], list[Machine]]:
    db = SessionLocal()
    try:
        sites = (
            db.query(Site)
            .filter(Site.is_active.is_(True))
            .order_by(Site.name.asc())
            .all()
        )
        machines = (
            db.query(Machine)
            .filter(Machine.is_active.is_(True))
            .order_by(Machine.name.asc())
            .all()
        )
        return sites, machines
    finally:
        db.close()


# -------------------------------------------------
# LOGIN FRONTEND (PAGINA + API SEMPLICE)
# -------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """
    Pagina di login HTML unica per tutti gli utenti.
    """
    current_user = _get_user_from_cookie(request)
    if current_user:
        requested_role = get_current_role_from_request(request)
        return RedirectResponse(
            url=get_default_route(current_user, requested_role),
            status_code=303,
        )

    return templates.TemplateResponse(
        request,
        "login.html",
        build_template_context(request, None),
    )


@app.post("/login")
@app.post("/auth/login", include_in_schema=False)
def login_api(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db=Depends(get_db),
):
    """
    Endpoint usato dal form di login.
    - Verifica le credenziali
    - Se ok, crea un JWT
    - Reindirizza automaticamente l'utente alla dashboard corretta
      in base al ruolo attivo
    """
    user = authenticate_user(db, email=email, password=password)
    if not user:
        # Torniamo la pagina di login con errore
        return templates.TemplateResponse(
            request,
            "login.html",
            build_template_context(
                request,
                None,
                login_error="Email o password non corretti",
            ),
            status_code=400,
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(status_code=400, detail="Utente disattivato")

    requested_role = get_current_role_from_request(request)
    active_role = _resolve_post_login_role(user, requested_role)
    db.commit()
    token_data = _generate_token_for_user(
        user,
        redirect_url=get_default_route(user, active_role),
        requested_role=active_role,
    )

    response = RedirectResponse(
        url=token_data.redirect_url or "/",
        status_code=303,
    )
    _apply_access_token_cookie(response, token_data.access_token, active_role)
    return response

@app.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key=CURRENT_ROLE_COOKIE_NAME, path="/")
    return response


@app.get("/switch-role/{role_name}")
def switch_role(
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
) -> RedirectResponse:
    try:
        requested_role = RoleEnum(role_name)
    except Exception:
        raise HTTPException(status_code=404, detail="Ruolo non valido")

    user_record = get_user_by_email(db, current_user.email)
    if not user_record:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if not getattr(current_user, "can_switch_roles", False):
        raise HTTPException(status_code=403, detail="Cambio ruolo non consentito")
    if not can_switch_user_role(user_record):
        raise HTTPException(status_code=403, detail="Cambio ruolo non consentito")
    if not user_has_role(user_record, requested_role):
        raise HTTPException(status_code=403, detail="Ruolo non assegnato all'utente")

    user_record.role = requested_role
    db.commit()
    db.refresh(user_record)

    token_data = _generate_token_for_user(
        user_record,
        redirect_url=get_default_route(user_record, requested_role),
        requested_role=requested_role,
    )
    response = RedirectResponse(url=token_data.redirect_url or "/", status_code=303)
    _apply_access_token_cookie(response, token_data.access_token, requested_role)
    return response


# -------------------------------------------------
# PAGINE FRONTEND — MANAGER & CAPOSQUADRA
# -------------------------------------------------

@app.get("/manager/dashboard", response_class=HTMLResponse, name="manager_dashboard")
def manager_dashboard(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Dashboard manager con accesso a cantieri, fiches, rapportini e macchinari.
    """
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    db = SessionLocal()
    sites_map_data: list[dict[str, object]] = []
    depots_map_data: list[dict[str, object]] = []
    transports_map_data: list[dict[str, object]] = []
    try:
        detail_url_template = str(
            request.url_for("manager_site_detail", site_id="__SITE_ID__")
        )
        query_started = time.monotonic()
        sites_with_coords = (
            db.query(Site)
            .options(
                load_only(
                    Site.id,
                    Site.name,
                    Site.address,
                    Site.city,
                    Site.country,
                    Site.lat,
                    Site.lng,
                    Site.status,
                    Site.is_active,
                    Site.caposquadra_id,
                ),
                joinedload(Site.caposquadra).load_only(
                    User.id,
                    User.full_name,
                    User.email,
                ),
            )
            .filter(
                Site.lat.isnot(None),
                Site.lng.isnot(None),
            )
            .order_by(Site.name)
            .all()
        )
        perf_logger.debug(
            "manager_dashboard sites_map query rows=%s duration_ms=%.2f",
            len(sites_with_coords),
            (time.monotonic() - query_started) * 1000,
        )
        sites_map_data = _build_sites_map_data(
            sites_with_coords,
            detail_url_template=detail_url_template,
        )
        depots_with_coords = (
            db.query(Depot)
            .filter(Depot.lat.isnot(None), Depot.lng.isnot(None))
            .order_by(Depot.name.asc())
            .all()
        )
        depots_map_data = _build_depots_map_data(
            depots_with_coords,
            detail_url_template=str(
                request.url_for("manager_depositi_edit", depot_id="__DEPOT_ID__")
            ),
        )
        active_trips = (
            db.query(TrasportoViaggio)
            .options(
                joinedload(TrasportoViaggio.autista).load_only(User.id, User.full_name, User.email),
                joinedload(TrasportoViaggio.mezzo),
                joinedload(TrasportoViaggio.origine_site).load_only(Site.id, Site.name, Site.lat, Site.lng),
                joinedload(TrasportoViaggio.origine_depot).load_only(Depot.id, Depot.name, Depot.lat, Depot.lng),
                joinedload(TrasportoViaggio.destinazione_site).load_only(Site.id, Site.name, Site.lat, Site.lng),
                joinedload(TrasportoViaggio.destinazione_depot).load_only(Depot.id, Depot.name, Depot.lat, Depot.lng),
                joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site).load_only(Site.id, Site.name, Site.lat, Site.lng),
                joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot).load_only(Depot.id, Depot.name, Depot.lat, Depot.lng),
            )
            .filter(
                TrasportoViaggio.stato.in_(
                    [
                        TrasportoStatoEnum.programmato,
                        TrasportoStatoEnum.in_carico,
                        TrasportoStatoEnum.in_viaggio,
                        TrasportoStatoEnum.arrivato,
                    ]
                )
            )
            .order_by(TrasportoViaggio.data_partenza.desc(), TrasportoViaggio.id.desc())
            .limit(250)
            .all()
        )
        transports_map_data = _build_transports_map_data(
            active_trips,
            trip_detail_url_template=str(
                request.url_for("manager_trasporti_viaggi_detail", viaggio_id="__TRIP_ID__")
            ),
        )
        query_started = time.monotonic()
        reports_list = (
            db.query(Report)
            .options(
                load_only(
                    Report.id,
                    Report.date,
                    Report.total_hours,
                    Report.site_id,
                    Report.site_name_or_code,
                ),
                joinedload(Report.site).load_only(Site.id, Site.name),
            )
            .order_by(Report.date.desc(), Report.id.desc())
            .limit(50)
            .all()
        )
        perf_logger.debug(
            "manager_dashboard reports_list rows=%s duration_ms=%.2f",
            len(reports_list),
            (time.monotonic() - query_started) * 1000,
        )

        start_date = date.today() - timedelta(days=30)

        query_started = time.monotonic()
        reports_last_30_days_rows = (
            db.query(Report.date.label("report_date"), func.count(Report.id).label("count"))
            .filter(Report.date >= start_date)
            .group_by(Report.date)
            .order_by(Report.date)
            .all()
        )
        perf_logger.debug(
            "manager_dashboard reports_last_30_days rows=%s duration_ms=%.2f",
            len(reports_last_30_days_rows),
            (time.monotonic() - query_started) * 1000,
        )
        reports_last_30_days = [
            {"date": row.report_date.isoformat(), "count": row.count}
            for row in reports_last_30_days_rows
        ]

        query_started = time.monotonic()
        hours_per_site_rows = (
            db.query(
                func.coalesce(Site.name, Report.site_name_or_code).label("site_name"),
                func.sum(Report.total_hours).label("hours"),
            )
            .outerjoin(Site, Site.id == Report.site_id)
            .filter(Report.date >= start_date)
            .group_by("site_name")
            .order_by(func.sum(Report.total_hours).desc())
            .all()
        )
        perf_logger.debug(
            "manager_dashboard hours_per_site rows=%s duration_ms=%.2f",
            len(hours_per_site_rows),
            (time.monotonic() - query_started) * 1000,
        )
        hours_per_site_30_days = [
            {"site_name": row.site_name or "Senza nome", "hours": float(row.hours or 0)}
            for row in hours_per_site_rows
        ]

        query_started = time.monotonic()
        reports_by_status_rows = (
            db.query(
                case(
                    (func.coalesce(Report.total_hours, 0) > 0, "Chiusi"),
                    else_="Aperti",
                ).label("status"),
                func.count(Report.id).label("count"),
            )
            .group_by("status")
            .all()
        )
        perf_logger.debug(
            "manager_dashboard reports_by_status rows=%s duration_ms=%.2f",
            len(reports_by_status_rows),
            (time.monotonic() - query_started) * 1000,
        )
        reports_by_status_counts = {"Aperti": 0, "Chiusi": 0}
        for row in reports_by_status_rows:
            reports_by_status_counts[row.status] = int(row.count or 0)
        reports_by_status = [
            {"status": key, "count": value}
            for key, value in reports_by_status_counts.items()
        ]

        query_started = time.monotonic()
        reports_count = db.query(func.count(Report.id)).scalar() or 0
        sites_count = (
            db.query(func.count(Site.id))
            .filter(Site.is_active.is_(True))
            .scalar()
            or 0
        )
        machines_count = db.query(func.count(Machine.id)).scalar() or 0
        users_count = (
            db.query(func.count(User.id))
            .filter(User.role.in_([RoleEnum.manager, RoleEnum.caposquadra]))
            .scalar()
            or 0
        )
        perf_logger.debug(
            "manager_dashboard kpi_counts duration_ms=%.2f",
            (time.monotonic() - query_started) * 1000,
        )

        logistics_active_trips = (
            db.query(func.count(TrasportoViaggio.id))
            .filter(
                TrasportoViaggio.stato.in_(
                    [TrasportoStatoEnum.in_carico, TrasportoStatoEnum.in_viaggio, TrasportoStatoEnum.arrivato]
                )
            )
            .scalar()
            or 0
        )
        logistics_trucks_in_travel = (
            db.query(func.count(TrasportoViaggio.id)).filter(TrasportoViaggio.stato == TrasportoStatoEnum.in_viaggio).scalar() or 0
        )
        logistics_equipment_moving = (
            db.query(func.count(Attrezzatura.id)).filter(Attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto).scalar() or 0
        )
        logistics_alerts = (
            db.query(func.count(TrasportoViaggio.id))
            .join(TrasportoRichiestaAttrezzatura, TrasportoRichiestaAttrezzatura.viaggio_id == TrasportoViaggio.id)
            .outerjoin(
                TrasportoAttrezzaturaViaggio,
                TrasportoAttrezzaturaViaggio.viaggio_id == TrasportoViaggio.id,
            )
            .group_by(TrasportoViaggio.id)
            .having(func.count(TrasportoAttrezzaturaViaggio.id) < func.sum(TrasportoRichiestaAttrezzatura.quantita))
            .count()
        )
        response = render_template(
            templates,
            request,
            "manager/home_manager.html",
            {
                "user_role": "manager",
                "reports": reports_list,
                "reports_count": reports_count,
                "sites_count": sites_count,
                "machines_count": machines_count,
                "users_count": users_count,
                "chart_reports_last_30_days": jsonable_encoder(reports_last_30_days),
                "chart_hours_per_site_30_days": jsonable_encoder(hours_per_site_30_days),
                "chart_reports_by_status": jsonable_encoder(reports_by_status),
                "cantieri_map_data": jsonable_encoder(sites_map_data),
                "operations_map_data": jsonable_encoder(
                    {
                        "sites": sites_map_data,
                        "depots": depots_map_data,
                        "transports": transports_map_data,
                    }
                ),
                "detail_url_template": detail_url_template,
                "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY"),
                "logistics_overview": {
                    "trucks_in_travel": logistics_trucks_in_travel,
                    "equipment_moving": logistics_equipment_moving,
                    "active_trips": logistics_active_trips,
                    "alerts": logistics_alerts,
                },
            },
            db,
            current_user,
        )
    finally:
        db.close()
    return response


def _build_sites_map_data(
    sites: list[Site],
    *,
    detail_url_template: str | None = None,
) -> list[dict[str, object]]:
    sites_map_data = []
    for site in sites:
        address_parts = [part for part in [site.address, site.city, site.country] if part]
        status_value = site.status.value if site.status else None
        caposquadra_name = None
        if "caposquadra" in site.__dict__ and site.caposquadra:
            caposquadra_name = site.caposquadra.full_name or site.caposquadra.email
        sites_map_data.append(
            {
                "id": int(site.id) if site.id is not None else None,
                "name": str(site.name) if site.name is not None else "",
                "lat": float(site.lat) if site.lat is not None else None,
                "lng": float(site.lng) if site.lng is not None else None,
                "address": ", ".join(str(part) for part in address_parts),
                "status": str(status_value) if status_value is not None else None,
                "is_active": site.is_active if site.is_active is not None else None,
                "caposquadra_id": (
                    int(site.caposquadra_id) if site.caposquadra_id is not None else None
                ),
                "caposquadra_name": (
                    str(caposquadra_name) if caposquadra_name is not None else None
                ),
                "type": "site",
                "detail_url": (
                    detail_url_template.replace("__SITE_ID__", str(site.id))
                    if detail_url_template and site.id is not None
                    else None
                ),
            }
        )
    return sites_map_data


def _build_depots_map_data(
    depots: list[Depot],
    *,
    detail_url_template: str | None = None,
) -> list[dict[str, object]]:
    depots_map_data: list[dict[str, object]] = []
    for depot in depots:
        address_parts = [part for part in [depot.address, depot.city, depot.province, depot.country] if part]
        depots_map_data.append(
            {
                "id": int(depot.id) if depot.id is not None else None,
                "name": str(depot.name) if depot.name is not None else "",
                "lat": float(depot.lat) if depot.lat is not None else None,
                "lng": float(depot.lng) if depot.lng is not None else None,
                "address": ", ".join(str(part) for part in address_parts),
                "is_active": bool(depot.is_active),
                "type": "depot",
                "detail_url": (
                    detail_url_template.replace("__DEPOT_ID__", str(depot.id))
                    if detail_url_template and depot.id is not None
                    else None
                ),
            }
        )
    return depots_map_data


def _build_trip_route_points_for_dashboard(viaggio: TrasportoViaggio) -> list[dict[str, object]]:
    def _point_from_place(
        *,
        site: Site | None,
        depot: Depot | None,
        fallback_name: str | None,
        role: str,
        sequence: int,
    ) -> dict[str, object]:
        if site:
            return {
                "id": int(site.id) if site.id is not None else None,
                "sequence": sequence,
                "role": role,
                "name": site.name or "—",
                "type": "site",
                "lat": site.lat,
                "lng": site.lng,
            }
        if depot:
            return {
                "id": int(depot.id) if depot.id is not None else None,
                "sequence": sequence,
                "role": role,
                "name": depot.name or "—",
                "type": "depot",
                "lat": depot.lat,
                "lng": depot.lng,
            }
        return {
            "id": None,
            "sequence": sequence,
            "role": role,
            "name": fallback_name or "—",
            "type": "unknown",
            "lat": None,
            "lng": None,
        }

    points = [
        _point_from_place(
            site=viaggio.origine_site,
            depot=viaggio.origine_depot,
            fallback_name=viaggio.origine,
            role="origin",
            sequence=1,
        )
    ]
    for index, tappa in enumerate(viaggio.tappe or [], start=2):
        points.append(
            _point_from_place(
                site=tappa.site,
                depot=tappa.depot,
                fallback_name=tappa.destinazione,
                role="stop",
                sequence=index,
            )
        )
    points.append(
        _point_from_place(
            site=viaggio.destinazione_site,
            depot=viaggio.destinazione_depot,
            fallback_name=viaggio.destinazione,
            role="destination",
            sequence=len(points) + 1,
        )
    )
    return points


def _format_duration_for_map(value: timedelta | None) -> str:
    if not value:
        return "0 min"
    total_minutes = max(int(value.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes} min"
    if hours:
        return f"{hours}h"
    return f"{minutes} min"


def _trip_progress_for_map(viaggio: TrasportoViaggio) -> dict[str, object]:
    progress_data = compute_trip_progress(viaggio)
    if not progress_data["is_available"]:
        return {
            "percent": None,
            "status": "non_disponibile",
            "status_label": "Stima non disponibile",
            "timing_text": "Stima non disponibile",
            "color": "unknown",
        }

    status = str(progress_data["status"])
    if status == "non_partito":
        color = "green"
        timing_text = "Non ancora partito"
    elif status == "in_ritardo":
        color = "red"
        timing_text = f"In ritardo di {_format_duration_for_map(progress_data['tempo_ritardo'])}"
    else:
        percent = int(progress_data["progress_percent"] or 0)
        color = "orange" if percent >= 80 else "green"
        timing_text = (
            f"Partito da {_format_duration_for_map(progress_data['tempo_trascorso'])} · "
            f"Arrivo stimato tra {_format_duration_for_map(progress_data['tempo_rimanente'])}"
        )

    return {
        "percent": progress_data["progress_percent"],
        "status": status,
        "status_label": progress_data["status_label"],
        "timing_text": timing_text,
        "color": color,
    }


def _build_transports_map_data(
    viaggi: list[TrasportoViaggio],
    *,
    trip_detail_url_template: str,
) -> list[dict[str, object]]:
    transports_map_data: list[dict[str, object]] = []
    for viaggio in viaggi:
        route_points = _build_trip_route_points_for_dashboard(viaggio)
        has_coords = any(
            point.get("lat") is not None and point.get("lng") is not None for point in route_points
        )
        if not has_coords:
            continue
        autista_name = None
        if viaggio.autista:
            autista_name = viaggio.autista.full_name or viaggio.autista.email
        mezzo_label = None
        if viaggio.mezzo:
            mezzo_label = " ".join(
                part
                for part in [
                    (viaggio.mezzo.marca or "").strip(),
                    (viaggio.mezzo.modello or "").strip(),
                    f"({viaggio.mezzo.targa})" if viaggio.mezzo.targa else "",
                ]
                if part
            )
        trip_detail_url = trip_detail_url_template.replace("__TRIP_ID__", str(viaggio.id))
        progress = _trip_progress_for_map(viaggio)
        transports_map_data.append(
            {
                "id": int(viaggio.id),
                "code": viaggio.codice_viaggio or f"V-{viaggio.id}",
                "status": viaggio.stato.value if viaggio.stato else None,
                "date": viaggio.data_partenza.isoformat() if viaggio.data_partenza else None,
                "driver_id": int(viaggio.autista_id) if viaggio.autista_id else None,
                "driver_name": autista_name,
                "vehicle_id": int(viaggio.mezzo_id) if viaggio.mezzo_id else None,
                "vehicle_name": mezzo_label,
                "route_points": route_points,
                "detail_url": trip_detail_url,
                "progress": progress,
            }
        )
    return transports_map_data


@app.get(
    "/manager/fiches/nuova",
    response_class=HTMLResponse,
    name="manager_fiche_new_form",
)
def manager_fiche_new_form(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    sites, machines = _load_manager_form_collections()

    return templates.TemplateResponse(
        request,
        "manager/fiches_form.html",
        build_template_context(
            request,
            current_user,
            cantieri=sites,
            macchinari=machines,
            is_edit=False,
            form_data=_build_fiche_form_data(),
            error_message=None,
        ),
    )


@app.post(
    "/manager/fiches/nuova",
    response_class=HTMLResponse,
    name="manager_fiche_create",
)
async def manager_fiche_create(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
    cantiere_id: int = Form(...),
    macchinario_id: str | None = Form(None),
    data_scavo: date = Form(...),
    data_getto: date | None = Form(None),
    metri_cubi_gettati: float | None = Form(None),
    operatore: str = Form(...),
    descrizione: str = Form(""),
    ore_lavorate: float = Form(...),
    note: str | None = Form(None),
    tipologia_scavo: str | None = Form(None),
    stratigrafia: str | None = Form(None),
    materiale: str | None = Form(None),
    profondita_totale: float | None = Form(None),
    diametro_palo_cm: float | None = Form(None),
    larghezza_pannello: float | None = Form(None),
    altezza_pannello: float | None = Form(None),
    strato_da: List[float] = Form(default_factory=list),
    strato_a: List[float] = Form(default_factory=list),
    strato_materiale: List[str] = Form(default_factory=list),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    try:
        parsed_machine_id: int | None = None
        if macchinario_id not in (None, ""):
            parsed_machine_id = int(macchinario_id)

        diametro_value_cm = diametro_palo_cm
        diametro_value_m = (
            diametro_value_cm / 100 if diametro_value_cm is not None else None
        )

        _validate_fiche_geometria(
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            profondita_totale=profondita_totale,
        )

        db = SessionLocal()
        try:
            site = db.query(Site).filter(Site.id == cantiere_id).first()
            if not site:
                raise HTTPException(status_code=400, detail="Cantiere non trovato")

            if parsed_machine_id is not None:
                machine = (
                    db.query(Machine).filter(Machine.id == parsed_machine_id).first()
                )
                if not machine:
                    raise HTTPException(status_code=400, detail="Macchinario non trovato")

            fiche = Fiche(
                date=data_scavo,
                site_id=cantiere_id,
                machine_id=parsed_machine_id,
                fiche_type=FicheTypeEnum.produzione,
                description=descrizione or "",
                operator=operatore,
                hours=ore_lavorate,
                notes=note,
                tipologia_scavo=tipologia_scavo or None,
                stratigrafia=stratigrafia or None,
                materiale=materiale or None,
                profondita_totale=profondita_totale,
                diametro_palo=diametro_value_m,
                larghezza_pannello=larghezza_pannello,
                altezza_pannello=altezza_pannello,
                data_getto=data_getto,
                metri_cubi_gettati=metri_cubi_gettati,
                created_by_id=current_user.id,
            )
            db.add(fiche)
            db.commit()
            db.refresh(fiche)

            for da_val, a_val, mat in zip(strato_da, strato_a, strato_materiale):
                if not mat:
                    continue
                if da_val is None or a_val is None:
                    continue
                if a_val <= da_val:
                    continue
                layer = FicheStratigrafia(
                    fiche_id=fiche.id,
                    da_profondita=da_val,
                    a_profondita=a_val,
                    materiale=mat,
                )
                db.add(layer)
            db.commit()
        finally:
            db.close()
    except ValueError:
        # macchinario_id non numerico
        form_data = _build_fiche_form_data(
            cantiere_id=cantiere_id,
            macchinario_id=macchinario_id,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            stratigrafia=stratigrafia,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo=diametro_value_m,
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
        )
        sites, machines = _load_manager_form_collections()
        return templates.TemplateResponse(
            request,
            "manager/fiches_form.html",
            build_template_context(
                request,
                current_user,
                cantieri=sites,
                macchinari=machines,
                is_edit=False,
                form_data=form_data,
                error_message="Macchinario non valido",
            ),
            status_code=400,
        )
    except HTTPException as exc:
        status_code = exc.status_code or 400
        form_data = _build_fiche_form_data(
            cantiere_id=cantiere_id,
            macchinario_id=macchinario_id,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            stratigrafia=stratigrafia,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo=diametro_value_m,
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
        )
        sites, machines = _load_manager_form_collections()
        return templates.TemplateResponse(
            request,
            "manager/fiches_form.html",
            build_template_context(
                request,
                current_user,
                cantieri=sites,
                macchinari=machines,
                is_edit=False,
                form_data=form_data,
                error_message=exc.detail,
            ),
            status_code=status_code,
        )

    return RedirectResponse(
        url=request.url_for("manager_fiches_list"), status_code=303
    )


@app.get("/manager/utenti", response_class=HTMLResponse)
def manager_users(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        users_list = (
            db.query(User)
            .options(
                joinedload(User.assigned_sites),
                joinedload(User.user_roles).joinedload(UserRole.role),
            )
            .order_by(User.email)
            .all()
        )
        user_sites_map = {
            user.id: list(user.assigned_sites or []) for user in users_list
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/users.html",
        build_template_context(
            request,
            current_user,
            user_role="admin",
            users=users_list,
            user_sites_map=user_sites_map,
        ),
    )


@app.get("/admin/users", response_class=JSONResponse)
def admin_users(
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )
    return {"status": "ok"}


@app.get("/admin/permessi-magazzino", response_class=HTMLResponse)
def admin_magazzino_permissions(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "settings.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        users_list = db.query(User).options(joinedload(User.user_roles).joinedload(UserRole.role)).order_by(User.email).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "admin/permessi_magazzino.html",
        build_template_context(
            request,
            current_user,
            users=users_list,
        ),
    )


@app.post("/admin/permessi-magazzino/{user_id}/toggle", response_class=HTMLResponse)
def admin_magazzino_permissions_toggle(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "settings.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        user_to_toggle = db.query(User).filter(User.id == user_id).first()
        if not user_to_toggle:
            raise HTTPException(status_code=404, detail="Utente non trovato")

        user_to_toggle.is_magazzino_manager = not bool(
            user_to_toggle.is_magazzino_manager
        )
        log_audit_event(
            db,
            current_user,
            "SETTINGS_MAGAZZINO_PERMISSION",
            "settings",
            user_to_toggle.id,
            {
                "email": user_to_toggle.email,
                "is_magazzino_manager": user_to_toggle.is_magazzino_manager,
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Errore durante l'aggiornamento dei permessi",
        )
    finally:
        db.close()

    return RedirectResponse(url="/admin/permessi-magazzino", status_code=303)


@app.get("/manager/utenti/nuovo", response_class=HTMLResponse)
async def manager_new_user_get(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    return templates.TemplateResponse(
        request,
        "manager/user_form.html",
        build_template_context(
            request,
            current_user,
            mode="create",
            user_obj=None,
            user_id=None,
            role_choices=get_cached_role_choices(),
            language_choices=["it", "fr"],
            error_message=None,
            form_email="",
            form_full_name="",
            form_roles=[],
            form_active_role="",
            form_language="",
            form_can_switch_roles=False,
        ),
    )


@app.post("/manager/utenti/nuovo", response_class=HTMLResponse)
async def manager_new_user_post(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    form = await request.form()
    email = (form.get("email") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    password = (form.get("password") or "").strip()
    role_values = [str(value).strip() for value in form.getlist("roles") if str(value).strip()]
    active_role_value = (form.get("active_role") or "").strip()
    language = (form.get("language") or "").strip() or None
    can_switch_roles = (form.get("can_switch_roles") or "").strip().lower() in {"1", "true", "on", "yes"}

    def render_form(error_message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "manager/user_form.html",
            build_template_context(
                request,
                current_user,
                mode="create",
                user_obj=None,
                user_id=None,
                role_choices=get_cached_role_choices(),
                language_choices=["it", "fr"],
                error_message=error_message,
                form_email=email,
                form_full_name=full_name,
                form_roles=role_values,
                form_active_role=active_role_value,
                form_language=language or "",
                form_can_switch_roles=can_switch_roles,
            ),
            status_code=status_code,
        )

    if not email:
        return render_form("Email obbligatoria.")
    if not password:
        return render_form("Password obbligatoria.")
    if len(password) < 4:
        return render_form("La password deve avere almeno 4 caratteri.")
    if not role_values:
        return render_form("Seleziona almeno un ruolo.")

    parsed_roles: list[RoleEnum] = []
    for value in role_values:
        try:
            parsed_roles.append(RoleEnum(value))
        except Exception:
            return render_form(f"Ruolo non valido: {value}")

    if not active_role_value:
        active_role_value = role_values[0]
    try:
        active_role = RoleEnum(active_role_value)
    except Exception:
        return render_form("Ruolo attivo non valido.")
    if active_role not in parsed_roles:
        return render_form("Il ruolo attivo deve essere tra quelli assegnati.")

    can_switch_roles = bool(
        can_switch_roles
        and len(parsed_roles) > 1
    )

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return render_form("Esiste già un utente con questa email.", status_code=400)

        hashed_password = hash_password(password)
        new_user = User(
            email=email,
            full_name=full_name or None,
            hashed_password=hashed_password,
            role=active_role,
            language=language,
            can_switch_roles=can_switch_roles,
        )
        if hasattr(User, "is_active"):
            new_user.is_active = True

        db.add(new_user)
        db.flush()
        _sync_user_roles(db, new_user, parsed_roles)
        log_audit_event(
            db,
            current_user,
            "USER_CREATED",
            "user",
            new_user.id,
            {
                "email": new_user.email,
                "roles": [role.value for role in parsed_roles],
                "active_role": active_role.value,
                "can_switch_roles": new_user.can_switch_roles,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        return render_form("Errore durante la creazione dell'utente. Riprova.")
    finally:
        db.close()

    return RedirectResponse(url="/manager/utenti", status_code=303)


@app.get("/manager/utenti/{user_id}/modifica", response_class=HTMLResponse)
async def manager_edit_user_get(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        user_to_edit = (
            db.query(User)
            .options(joinedload(User.user_roles).joinedload(UserRole.role))
            .filter(User.id == user_id)
            .first()
        )
        if not user_to_edit:
            raise HTTPException(status_code=404, detail="Utente non trovato")
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/user_form.html",
        build_template_context(
            request,
            current_user,
            mode="edit",
            user_obj=user_to_edit,
            user_id=user_to_edit.id,
            role_choices=get_cached_role_choices(),
            language_choices=["it", "fr"],
            error_message=None,
            form_email=user_to_edit.email,
            form_full_name=user_to_edit.full_name or "",
            form_roles=[role.value for role in get_user_roles(user_to_edit)],
            form_active_role=user_to_edit.role.value if user_to_edit.role else "",
            form_language=user_to_edit.language or "",
            form_can_switch_roles=bool(getattr(user_to_edit, "can_switch_roles", False)),
        ),
    )


@app.post("/manager/utenti/{user_id}/modifica", response_class=HTMLResponse)
async def manager_edit_user_post(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    form = await request.form()
    email = (form.get("email") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    role_values = [str(value).strip() for value in form.getlist("roles") if str(value).strip()]
    active_role_value = (form.get("active_role") or "").strip()
    language = (form.get("language") or "").strip() or None
    can_switch_roles = (form.get("can_switch_roles") or "").strip().lower() in {"1", "true", "on", "yes"}
    user_obj = None

    def render_form(error_message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "manager/user_form.html",
            build_template_context(
                request,
                current_user,
                mode="edit",
                user_obj=user_obj,
                user_id=user_id,
                role_choices=get_cached_role_choices(),
                language_choices=["it", "fr"],
                error_message=error_message,
                form_email=email,
                form_full_name=full_name,
                form_roles=role_values,
                form_active_role=active_role_value,
                form_language=language or "",
                form_can_switch_roles=can_switch_roles,
            ),
            status_code=status_code,
        )

    if not email:
        return render_form("Email obbligatoria.")
    if not role_values:
        return render_form("Seleziona almeno un ruolo.")

    parsed_roles: list[RoleEnum] = []
    for value in role_values:
        try:
            parsed_roles.append(RoleEnum(value))
        except Exception:
            return render_form(f"Ruolo non valido: {value}")

    if not active_role_value:
        active_role_value = role_values[0]
    try:
        active_role = RoleEnum(active_role_value)
    except Exception:
        return render_form("Ruolo attivo non valido.")
    if active_role not in parsed_roles:
        return render_form("Il ruolo attivo deve essere tra quelli assegnati.")

    can_switch_roles = bool(
        can_switch_roles
        and len(parsed_roles) > 1
    )

    db = SessionLocal()
    try:
        user_to_edit = (
            db.query(User)
            .options(joinedload(User.user_roles).joinedload(UserRole.role))
            .filter(User.id == user_id)
            .first()
        )
        if not user_to_edit:
            raise HTTPException(status_code=404, detail="Utente non trovato")
        user_obj = user_to_edit

        existing = (
            db.query(User)
            .filter(User.email == email, User.id != user_to_edit.id)
            .first()
        )
        if existing:
            return render_form("Esiste già un utente con questa email.", status_code=400)

        previous_active_role = user_to_edit.role.value if user_to_edit.role else None
        previous_roles = [role.value for role in get_user_roles(user_to_edit)]

        if previous_active_role != active_role.value and not has_perm(current_user, "users.update_role"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permessi insufficienti",
            )

        user_to_edit.email = email
        user_to_edit.full_name = full_name or None
        user_to_edit.role = active_role
        user_to_edit.language = language
        user_to_edit.can_switch_roles = can_switch_roles
        _sync_user_roles(db, user_to_edit, parsed_roles)

        log_audit_event(
            db,
            current_user,
            "USER_ROLE_CHANGED" if previous_active_role != active_role.value or previous_roles != [role.value for role in parsed_roles] else "USER_UPDATED",
            "user",
            user_to_edit.id,
            {
                "email": user_to_edit.email,
                "previous_role": previous_active_role,
                "new_role": active_role.value,
                "previous_roles": previous_roles,
                "new_roles": [role.value for role in parsed_roles],
                "can_switch_roles": user_to_edit.can_switch_roles,
            },
        )

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        return render_form("Errore durante l'aggiornamento dell'utente. Riprova.")
    finally:
        db.close()

    return RedirectResponse(url="/manager/utenti", status_code=303)


@app.post("/manager/utenti/{user_id}/toggle-attivo", response_class=HTMLResponse)
async def manager_toggle_user_active(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        user_to_toggle = db.query(User).filter(User.id == user_id).first()
        if not user_to_toggle:
            raise HTTPException(status_code=404, detail="Utente non trovato")

        if user_to_toggle.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Non puoi modificare il tuo stato attivo",
            )

        user_to_toggle.is_active = not bool(user_to_toggle.is_active)
        log_audit_event(
            db,
            current_user,
            "USER_STATUS_TOGGLED",
            "user",
            user_to_toggle.id,
            {
                "email": user_to_toggle.email,
                "is_active": user_to_toggle.is_active,
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Errore durante l'aggiornamento dello stato utente",
        )
    finally:
        db.close()

    return RedirectResponse(url="/manager/utenti", status_code=303)


@app.get("/manager/utenti/{user_id}/reset-password", response_class=HTMLResponse)
async def manager_reset_password_get(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        user_to_update = db.query(User).filter(User.id == user_id).first()
        if not user_to_update:
            raise HTTPException(status_code=404, detail="Utente non trovato")
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/user_reset_password.html",
        build_template_context(
            request,
            current_user,
            target_user=user_to_update,
            error_message=None,
        ),
    )


@app.post("/manager/utenti/{user_id}/reset-password", response_class=HTMLResponse)
async def manager_reset_password_post(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    form = await request.form()
    password = (form.get("password") or "").strip()
    password_confirm = (form.get("password_confirm") or "").strip()
    target_user = None

    def render_form(error_message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "manager/user_reset_password.html",
            build_template_context(
                request,
                current_user,
                target_user=target_user,
                error_message=error_message,
            ),
            status_code=status_code,
        )

    if not password:
        db = SessionLocal()
        try:
            target_user = db.query(User).filter(User.id == user_id).first()
            if not target_user:
                raise HTTPException(status_code=404, detail="Utente non trovato")
        finally:
            db.close()
        return render_form("Password obbligatoria.")

    db = SessionLocal()
    try:
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="Utente non trovato")

        if password_confirm and password != password_confirm:
            return render_form("Le password non coincidono.")

        target_user.hashed_password = hash_password(password)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        return render_form("Errore durante il reset della password. Riprova.")
    finally:
        db.close()

    return RedirectResponse(url="/manager/utenti", status_code=303)


@app.get("/manager/cantieri", response_class=HTMLResponse)
def manager_cantieri(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    page, per_page = _normalize_pagination(page, per_page)
    db = SessionLocal()
    try:
        query = (
            db.query(Site)
            .options(
                load_only(
                    Site.id,
                    Site.name,
                    Site.code,
                    Site.city,
                    Site.status,
                    Site.is_active,
                    Site.lat,
                    Site.lng,
                    Site.address,
                    Site.start_date,
                ),
                joinedload(Site.caposquadra).load_only(
                    User.id,
                    User.full_name,
                    User.email,
                ),
            )
            .order_by(
                Site.is_active.desc(),
                Site.start_date.desc(),
                Site.name,
            )
        )
        total_count = query.count()
        query_started = time.monotonic()
        sites_list = query.offset((page - 1) * per_page).limit(per_page).all()
        perf_logger.debug(
            "manager_cantieri rows=%s total=%s page=%s per_page=%s duration_ms=%.2f",
            len(sites_list),
            total_count,
            page,
            per_page,
            (time.monotonic() - query_started) * 1000,
        )
        site_caposquadra_map = {
            site.id: site.caposquadra for site in sites_list
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/cantieri.html",
        build_template_context(
            request,
            current_user,
            sites=sites_list,
            site_caposquadra_map=site_caposquadra_map,
            page=page,
            per_page=per_page,
            total_pages=max(1, ceil(total_count / per_page)),
        ),
    )


def _progress_percent(done_value: float, total_value: float) -> int:
    if total_value <= 0:
        return 0
    return int(round((done_value / total_value) * 100))


def _progress_status(percent: int, lang: str) -> str:
    if percent >= 100:
        return "Completato" if lang == "it" else "Terminé"
    if percent <= 0:
        return "Da avviare" if lang == "it" else "À démarrer"
    return "In corso" if lang == "it" else "En cours"


def _format_progress_value(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(int(value))


def _clamp_progress_percent(value: str | int | float | None) -> int:
    if value in ("", None):
        return 0
    try:
        numeric_value = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, numeric_value))


def _apply_extra_site_progress(
    site: Site,
    installazione_cantiere_pct: str | int | float | None,
    rabotage_pct: str | int | float | None,
    pozzi_pompaggio_pct: str | int | float | None,
) -> None:
    if (
        installazione_cantiere_pct is None
        and rabotage_pct is None
        and pozzi_pompaggio_pct is None
    ):
        return
    site.installazione_cantiere_pct = _clamp_progress_percent(installazione_cantiere_pct)
    site.rabotage_pct = _clamp_progress_percent(rabotage_pct)
    site.pozzi_pompaggio_pct = _clamp_progress_percent(pozzi_pompaggio_pct)


def _build_site_progress(
    site: Site, lang: str
) -> tuple[dict[str, dict[str, object]], list[dict[str, int | str]], int]:
    cordoli_total = float(site.cordoli_total_m or 0)
    cordoli_done = float(site.cordoli_done_m or 0)
    paratie_total = int(site.paratie_total_panels or 0)
    paratie_done = int(site.paratie_done_panels or 0)
    installazione_cantiere_pct = _clamp_progress_percent(site.installazione_cantiere_pct)
    rabotage_pct = _clamp_progress_percent(site.rabotage_pct)
    pozzi_pompaggio_pct = _clamp_progress_percent(site.pozzi_pompaggio_pct)

    strut_levels = list(site.strut_levels or [])
    strut_total = sum(level.total_struts_level or 0 for level in strut_levels)
    strut_done = sum(level.done_struts_level or 0 for level in strut_levels)

    labels = {
        "cordoli": "Cordoli guida" if lang == "it" else "Guides (cordons)",
        "paratie": "Scavo + paratie" if lang == "it" else "Excavation + parois",
        "puntoni": "Posa puntoni" if lang == "it" else "Pose des butons",
        "installazione_cantiere": "Installazione cantiere" if lang == "it" else "Installation chantier",
        "rabotage": "Rabotage" if lang == "it" else "Rabotage",
        "pozzi_pompaggio": "Pozzi pompaggio" if lang == "it" else "Puits de pompage",
    }
    units = {
        "cordoli": "m",
        "paratie": "pannelli" if lang == "it" else "panneaux",
        "puntoni": "puntoni" if lang == "it" else "butons",
        "installazione_cantiere": "%",
        "rabotage": "%",
        "pozzi_pompaggio": "%",
    }

    cordoli_done_display = _format_progress_value(cordoli_done)
    cordoli_total_display = _format_progress_value(cordoli_total)
    paratie_done_display = _format_progress_value(paratie_done)
    paratie_total_display = _format_progress_value(paratie_total)
    strut_done_display = _format_progress_value(strut_done)
    strut_total_display = _format_progress_value(strut_total)

    progress_summary = {
        "installazione_cantiere": {
            "label": labels["installazione_cantiere"],
            "total": 100,
            "done": installazione_cantiere_pct,
            "percent": installazione_cantiere_pct,
            "unit": units["installazione_cantiere"],
            "subtitle": f"{installazione_cantiere_pct}{units['installazione_cantiere']}",
        },
        "cordoli": {
            "label": labels["cordoli"],
            "total": cordoli_total,
            "done": cordoli_done,
            "percent": _progress_percent(cordoli_done, cordoli_total),
            "unit": units["cordoli"],
            "subtitle": f"{cordoli_done_display} / {cordoli_total_display} {units['cordoli']}",
        },
        "paratie": {
            "label": labels["paratie"],
            "total": paratie_total,
            "done": paratie_done,
            "percent": _progress_percent(paratie_done, paratie_total),
            "unit": units["paratie"],
            "subtitle": f"{paratie_done_display} / {paratie_total_display} {units['paratie']}",
        },
        "pozzi_pompaggio": {
            "label": labels["pozzi_pompaggio"],
            "total": 100,
            "done": pozzi_pompaggio_pct,
            "percent": pozzi_pompaggio_pct,
            "unit": units["pozzi_pompaggio"],
            "subtitle": f"{pozzi_pompaggio_pct}{units['pozzi_pompaggio']}",
        },
        "rabotage": {
            "label": labels["rabotage"],
            "total": 100,
            "done": rabotage_pct,
            "percent": rabotage_pct,
            "unit": units["rabotage"],
            "subtitle": f"{rabotage_pct}{units['rabotage']}",
        },
        "puntoni": {
            "label": labels["puntoni"],
            "total": strut_total,
            "done": strut_done,
            "percent": _progress_percent(strut_done, strut_total),
            "unit": units["puntoni"],
            "subtitle": f"{strut_done_display} / {strut_total_display} {units['puntoni']}",
        },
    }
    for key in progress_summary:
        percent = progress_summary[key]["percent"]
        progress_summary[key]["status"] = _progress_status(percent, lang)

    strut_levels_count = max(site.strut_levels_count or 0, len(strut_levels), 1)
    strut_levels_by_index = {level.level_index: level for level in strut_levels}
    strut_levels_view = []
    for index in range(1, strut_levels_count + 1):
        level = strut_levels_by_index.get(index)
        total_level = int(level.total_struts_level or 0) if level else 0
        done_level = int(level.done_struts_level or 0) if level else 0
        quota = level.level_quota if level else ""
        strut_levels_view.append(
            {
                "level_index": index,
                "level_quota": quota,
                "total": total_level,
                "done": done_level,
                "percent": _progress_percent(done_level, total_level),
            }
        )

    progress_summary["puntoni"]["levels"] = strut_levels_view

    return progress_summary, strut_levels_view, strut_levels_count


def _get_site_for_detail(db: Session, site_id: int, current_user: User) -> Site:
    query = db.query(Site).options(
        joinedload(Site.caposquadra),
        joinedload(Site.strut_levels),
    )
    query = scope_sites_query(query, current_user)
    site = query.filter(Site.id == site_id).first()
    if site:
        return site
    if current_user.role == RoleEnum.caposquadra:
        exists = db.query(Site.id).filter(Site.id == site_id).first()
        if exists:
            raise HTTPException(status_code=403, detail="Cantiere non assegnato")
    raise HTTPException(status_code=404, detail="Cantiere non trovato")


def _parse_site_task_status(value: str | None) -> SiteTaskStatusEnum:
    cleaned = (value or "").strip()
    for status_value in SITE_TASK_STATUSES:
        if cleaned == status_value.value:
            return status_value
    return SiteTaskStatusEnum.da_fare


def _parse_site_task_priority(value: str | None) -> SiteTaskPriorityEnum:
    cleaned = (value or "").strip()
    for priority_value in SITE_TASK_PRIORITIES:
        if cleaned == priority_value.value:
            return priority_value
    return SiteTaskPriorityEnum.media


def _parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_task_completion(task: SiteTask, user_id: int | None = None) -> None:
    is_completed = task.status == SiteTaskStatusEnum.completato or bool(task.completed)
    task.completed = is_completed
    if is_completed:
        if task.status != SiteTaskStatusEnum.completato:
            task.status = SiteTaskStatusEnum.completato
        if task.completed_at is None:
            task.completed_at = datetime.utcnow()
        if task.completed_by_id is None:
            task.completed_by_id = user_id
    else:
        task.completed_at = None
        task.completed_by_id = None


def _site_task_completed_clause():
    return or_(
        SiteTask.completed.is_(True),
        SiteTask.status == SiteTaskStatusEnum.completato,
    )


def _site_task_open_clause():
    return and_(
        SiteTask.completed.is_(False),
        SiteTask.status != SiteTaskStatusEnum.completato,
    )


def _is_task_completed(task: SiteTask) -> bool:
    return bool(task.completed) or task.status == SiteTaskStatusEnum.completato


def _request_wants_json(request: Request) -> bool:
    requested_with = (request.headers.get("x-requested-with") or "").lower()
    accept = (request.headers.get("accept") or "").lower()
    return requested_with == "xmlhttprequest" or "application/json" in accept


def _format_user_label(user: User | None) -> str | None:
    if not user:
        return None
    return user.full_name or user.email


def _serialize_site_task(task: SiteTask) -> dict:
    return {
        "id": task.id,
        "site_id": task.site_id,
        "title": task.title,
        "description": task.description or "",
        "status_value": task.status.value if task.status else SiteTaskStatusEnum.da_fare.value,
        "priority_value": task.priority.value if task.priority else SiteTaskPriorityEnum.media.value,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assigned_to_id": task.assigned_to_id,
        "assigned_to_label": _format_user_label(task.assigned_to),
        "created_by_label": _format_user_label(task.created_by),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "completed_at_display": task.completed_at.strftime("%d/%m/%Y %H:%M") if task.completed_at else "—",
        "completed_by_label": _format_user_label(task.completed_by),
        "site_name": task.site.name if task.site else None,
    }


def _get_overview_site_ids(db: Session, current_user: User) -> list[int]:
    scoped_sites = (
        scope_sites_query(
            db.query(Site.id),
            current_user,
        )
        .filter(
            Site.is_active.is_(True),
            Site.status.in_([SiteStatusEnum.aperto, SiteStatusEnum.pianificato]),
        )
        .all()
    )
    return [row[0] for row in scoped_sites]


def _get_recent_completed_tasks_for_overview(db: Session, current_user: User, limit: int = 5) -> list[SiteTask]:
    site_ids = _get_overview_site_ids(db, current_user)
    if not site_ids:
        return []
    return (
        db.query(SiteTask)
        .options(
            joinedload(SiteTask.site),
            joinedload(SiteTask.created_by),
            joinedload(SiteTask.completed_by),
        )
        .filter(
            SiteTask.site_id.in_(site_ids),
            _site_task_completed_clause(),
        )
        .order_by(
            SiteTask.completed_at.desc().nulls_last(),
            SiteTask.updated_at.desc(),
        )
        .limit(limit)
        .all()
    )


def _get_open_count_for_site(db: Session, site_id: int) -> int:
    count = (
        db.query(func.count(SiteTask.id))
        .filter(
            SiteTask.site_id == site_id,
            _site_task_open_clause(),
        )
        .scalar()
    )
    return int(count or 0)


def _build_site_task_redirect_url(request: Request, site_id: int, *, fallback_filter: str = "aperte") -> str:
    next_url = (request.query_params.get("next") or "").strip()
    if next_url.startswith("/manager/"):
        return next_url
    filter_value = (request.query_params.get("task_filter") or fallback_filter).strip().lower()
    return f"/manager/cantieri/{site_id}?task_filter={filter_value}#todo-operative"


def _load_site_tasks_for_site_detail(
    db: Session,
    site_id: int,
) -> tuple[list[SiteTask], list[SiteTask], list[SiteTask]]:
    open_tasks = (
        db.query(SiteTask)
        .options(
            joinedload(SiteTask.assigned_to),
            joinedload(SiteTask.created_by),
            joinedload(SiteTask.updated_by),
            joinedload(SiteTask.completed_by),
        )
        .filter(
            SiteTask.site_id == site_id,
            _site_task_open_clause(),
        )
        .order_by(
            SiteTask.priority.desc(),
            SiteTask.due_date.asc().nulls_last(),
            SiteTask.created_at.desc(),
        )
        .all()
    )
    completed_tasks = (
        db.query(SiteTask)
        .options(
            joinedload(SiteTask.assigned_to),
            joinedload(SiteTask.created_by),
            joinedload(SiteTask.updated_by),
            joinedload(SiteTask.completed_by),
        )
        .filter(
            SiteTask.site_id == site_id,
            _site_task_completed_clause(),
        )
        .order_by(
            SiteTask.completed_at.desc().nulls_last(),
            SiteTask.updated_at.desc(),
            SiteTask.created_at.desc(),
        )
        .all()
    )
    return open_tasks + completed_tasks, open_tasks, completed_tasks


def _create_site_task(
    db: Session,
    *,
    site_id: int,
    title: str,
    description: str | None,
    status_value: str,
    priority_value: str,
    assigned_to_id: str | None,
    due_date: str | None,
    current_user: User,
) -> SiteTask:
    site = _get_site_for_detail(db, site_id, current_user)
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Titolo obbligatorio")

    assigned_to = None
    if assigned_to_id not in (None, ""):
        try:
            assigned_user_id = int(assigned_to_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Assegnatario non valido") from exc
        assigned_to = db.query(User).filter(User.id == assigned_user_id).first()
        if not assigned_to:
            raise HTTPException(status_code=400, detail="Assegnatario non trovato")
    task = SiteTask(
        site_id=site_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        status=_parse_site_task_status(status_value),
        priority=_parse_site_task_priority(priority_value),
        due_date=_parse_optional_date(due_date),
        assigned_to_id=assigned_to.id if assigned_to else None,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    _normalize_task_completion(task, current_user.id)
    db.add(task)
    db.commit()
    return task


@app.post(
    "/manager/sites/{site_id}/progress/cordoli",
    name="manager_site_progress_cordoli",
)
def manager_site_progress_cordoli(
    request: Request,
    site_id: int,
    cordoli_total_m: float | None = Form(None),
    cordoli_done_m: float | None = Form(None),
    installazione_cantiere_pct: str | None = Form(None),
    rabotage_pct: str | None = Form(None),
    pozzi_pompaggio_pct: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")

        total_value = max(float(cordoli_total_m or 0), 0.0)
        done_value = max(float(cordoli_done_m or 0), 0.0)
        site.cordoli_total_m = total_value
        site.cordoli_done_m = done_value
        _apply_extra_site_progress(
            site,
            installazione_cantiere_pct,
            rabotage_pct,
            pozzi_pompaggio_pct,
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/modifica#progress-cordoli",
        status_code=303,
    )


@app.post(
    "/manager/sites/{site_id}/progress/paratie",
    name="manager_site_progress_paratie",
)
def manager_site_progress_paratie(
    request: Request,
    site_id: int,
    paratie_total_panels: int | None = Form(None),
    paratie_done_panels: int | None = Form(None),
    installazione_cantiere_pct: str | None = Form(None),
    rabotage_pct: str | None = Form(None),
    pozzi_pompaggio_pct: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")

        total_value = max(int(paratie_total_panels or 0), 0)
        done_value = max(int(paratie_done_panels or 0), 0)
        site.paratie_total_panels = total_value
        site.paratie_done_panels = done_value
        _apply_extra_site_progress(
            site,
            installazione_cantiere_pct,
            rabotage_pct,
            pozzi_pompaggio_pct,
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/modifica#progress-paratie",
        status_code=303,
    )


@app.post(
    "/manager/sites/{site_id}/progress/puntoni",
    name="manager_site_progress_puntoni",
)
def manager_site_progress_puntoni(
    request: Request,
    site_id: int,
    levels_count: int = Form(1),
    level_index: list[int] = Form(default_factory=list),
    level_quota: list[str] = Form(default_factory=list),
    total_struts_level: list[int] = Form(default_factory=list),
    done_struts_level: list[int] = Form(default_factory=list),
    installazione_cantiere_pct: str | None = Form(None),
    rabotage_pct: str | None = Form(None),
    pozzi_pompaggio_pct: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    def _safe_int(value: int | str | None) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    normalized_count = max(_safe_int(levels_count), 1)
    levels_data: dict[int, dict[str, object]] = {}
    for idx, raw_index in enumerate(level_index):
        index_value = _safe_int(raw_index)
        if index_value <= 0:
            continue
        quota_value = (level_quota[idx] if idx < len(level_quota) else "") or ""
        total_value = _safe_int(total_struts_level[idx] if idx < len(total_struts_level) else 0)
        done_value = _safe_int(done_struts_level[idx] if idx < len(done_struts_level) else 0)
        levels_data[index_value] = {
            "quota": quota_value.strip() or None,
            "total": total_value,
            "done": done_value,
        }

    db = SessionLocal()
    try:
        site = db.query(Site).options(joinedload(Site.strut_levels)).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")

        existing_levels = {level.level_index: level for level in site.strut_levels}
        for index in range(1, normalized_count + 1):
            payload = levels_data.get(index, {})
            level = existing_levels.get(index)
            if not level:
                level = SiteStrutLevel(site_id=site.id, level_index=index)
                db.add(level)
            level.level_quota = payload.get("quota")
            level.total_struts_level = int(payload.get("total") or 0)
            level.done_struts_level = int(payload.get("done") or 0)

        for index, level in existing_levels.items():
            if index > normalized_count:
                db.delete(level)

        site.strut_levels_count = normalized_count
        _apply_extra_site_progress(
            site,
            installazione_cantiere_pct,
            rabotage_pct,
            pozzi_pompaggio_pct,
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/modifica#progress-puntoni",
        status_code=303,
    )


@app.get("/manager/cantieri/nuovo", response_class=HTMLResponse)
def manager_cantiere_nuovo_get(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "sites.create"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    site_status_values = get_cached_site_status_values()
    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    db = SessionLocal()
    try:
        capisquadra = (
            db.query(User)
            .filter(User.role == RoleEnum.caposquadra)
            .filter(User.is_active.is_(True))
            .order_by(User.full_name, User.email)
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/cantiere_form.html",
        build_template_context(
            request,
            current_user,
            mode="create",
            site=None,
            site_status_values=site_status_values,
            capisquadra=capisquadra,
            google_maps_api_key=google_maps_api_key,
        ),
    )


@app.post("/manager/cantieri/nuovo")
def manager_cantiere_nuovo_post(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    address: str | None = Form(None),
    lat: str | None = Form(None),
    lng: str | None = Form(None),
    place_id: str | None = Form(None),
    confirm_unverified: str | None = Form(None),
    city: str | None = Form(None),
    country: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    status: str = Form(...),
    is_active: str | None = Form(None),
    caposquadra_id: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "sites.create"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    errors: list[str] = []
    if not name or not name.strip():
        errors.append("Il nome del cantiere è obbligatorio.")
    if not code or not code.strip():
        errors.append("Il codice del cantiere è obbligatorio.")

    def parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def parse_caposquadra(value: str | None) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def parse_coordinate(value: str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    start_date_parsed = parse_date(start_date)
    end_date_parsed = parse_date(end_date)
    lat_value = parse_coordinate(lat)
    lng_value = parse_coordinate(lng)
    has_address = bool(address and address.strip())

    if start_date and start_date_parsed is None:
        errors.append("La data di inizio non è valida.")
    if end_date and end_date_parsed is None:
        errors.append("La data di fine non è valida.")
    if lat not in (None, "") and lat_value is None:
        errors.append("La latitudine inserita non è valida.")
    if lng not in (None, "") and lng_value is None:
        errors.append("La longitudine inserita non è valida.")

    if status not in SiteStatusEnum.__members__:
        errors.append("Lo stato selezionato non è valido.")
        status_value = SiteStatusEnum.aperto
    else:
        status_value = SiteStatusEnum[status]

    if (
        has_address
        and (lat_value is None or lng_value is None)
        and confirm_unverified is None
    ):
        errors.append(
            "Seleziona un indirizzo dai suggerimenti o clicca sulla mappa per "
            "impostare la posizione, oppure conferma per salvare senza coordinate."
        )

    db = SessionLocal()
    try:
        parsed_capo_id = parse_caposquadra(caposquadra_id)
        if caposquadra_id not in (None, "") and parsed_capo_id is None:
            errors.append("Il caposquadra selezionato non è valido.")
        elif parsed_capo_id is not None:
            capo = (
                db.query(User)
                .filter(User.id == parsed_capo_id)
                .filter(User.role == RoleEnum.caposquadra)
                .filter(User.is_active.is_(True))
                .first()
            )
            if not capo:
                errors.append("Il caposquadra selezionato non è valido.")

        if errors:
            logger.warning(
                "Validation error on site create (request_id=%s): %s",
                _get_request_id(request),
                errors,
            )
            site_status_values = get_cached_site_status_values()
            google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
            capisquadra = (
                db.query(User)
                .filter(User.role == RoleEnum.caposquadra)
                .filter(User.is_active.is_(True))
                .order_by(User.full_name, User.email)
                .all()
            )
            return templates.TemplateResponse(
                request,
                "manager/cantiere_form.html",
                build_template_context(
                    request,
                    current_user,
                    mode="create",
                    site=None,
                    site_status_values=site_status_values,
                    capisquadra=capisquadra,
                    google_maps_api_key=google_maps_api_key,
                    error_message=errors[0],
                    form_data={
                        "name": name,
                        "code": code,
                        "address": address or "",
                        "lat": lat_value,
                        "lng": lng_value,
                        "place_id": place_id or "",
                        "city": city or "",
                        "country": country or "",
                        "start_date": start_date or "",
                        "end_date": end_date or "",
                        "status": status,
                        "is_active": is_active,
                        "caposquadra_id": parsed_capo_id,
                        "confirm_unverified": confirm_unverified,
                    },
                    form_submitted=True,
                ),
                status_code=400,
            )

        new_site = Site(
            name=name,
            code=code,
            address=address,
            lat=lat_value,
            lng=lng_value,
            place_id=place_id or None,
            city=city,
            country=country,
            start_date=start_date_parsed,
            end_date=end_date_parsed,
            status=status_value,
            is_active=is_active is not None,
            caposquadra_id=parsed_capo_id,
        )
        db.add(new_site)
        db.flush()
        log_audit_event(
            db,
            current_user,
            "SITE_CREATED",
            "site",
            new_site.id,
            {
                "name": new_site.name,
                "code": new_site.code,
                "status": new_site.status.value if new_site.status else None,
            },
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/manager/cantieri", status_code=303)


@app.get("/manager/cantieri/{site_id}", response_class=HTMLResponse, name="manager_site_detail")
@app.get("/manager/sites/{site_id}", response_class=HTMLResponse)
def manager_site_detail(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access") and current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    lang = request.cookies.get("lang", "it")
    task_filter = (request.query_params.get("task_filter") or "tutte").strip().lower()
    db = SessionLocal()
    try:
        site = _get_site_for_detail(db, site_id, current_user)
        progress_summary, strut_levels_view, strut_levels_count = _build_site_progress(
            site, lang
        )
        site_tasks, open_tasks, completed_tasks = _load_site_tasks_for_site_detail(db, site_id)
        manager_users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .filter(User.role.in_([RoleEnum.admin, RoleEnum.manager]))
            .order_by(User.full_name, User.email)
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/site_detail.html",
        build_template_context(
            request,
            current_user,
            site=site,
            progress_summary=progress_summary,
            strut_levels=strut_levels_view,
            strut_levels_count=strut_levels_count,
            site_tasks=site_tasks,
            open_tasks=open_tasks,
            completed_tasks=completed_tasks,
            task_filter=task_filter,
            site_task_status_values=SITE_TASK_STATUSES,
            site_task_priority_values=SITE_TASK_PRIORITIES,
            manager_users=manager_users,
        ),
    )


@app.post("/manager/cantieri/{site_id}/tasks", name="manager_site_task_create")
def manager_site_task_create(
    request: Request,
    site_id: int,
    title: str = Form(...),
    description: str = Form(""),
    status_value: str = Form("da_fare"),
    priority_value: str = Form("media"),
    assigned_to_id: str | None = Form(None),
    due_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    wants_json = _request_wants_json(request)
    db = SessionLocal()
    try:
        task = _create_site_task(
            db,
            site_id=site_id,
            title=title,
            description=description,
            status_value=status_value,
            priority_value=priority_value,
            assigned_to_id=assigned_to_id,
            due_date=due_date,
            current_user=current_user,
        )
        db.flush()
        db.refresh(task)
        open_count = _get_open_count_for_site(db, site_id)
        db.commit()
        if wants_json:
            return JSONResponse(
                {
                    "success": True,
                    "message": "Nota operativa creata con successo",
                    "task": _serialize_site_task(task),
                    "open_count": open_count,
                }
            )
    finally:
        db.close()
    return RedirectResponse(
        url=_build_site_task_redirect_url(request, site_id),
        status_code=303,
    )


@app.post("/manager/note-operative/tasks", response_class=JSONResponse, name="manager_site_task_create_from_overview")
def manager_site_task_create_from_overview(
    request: Request,
    site_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    status_value: str = Form("da_fare"),
    priority_value: str = Form("media"),
    assigned_to_id: str | None = Form(None),
    due_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_api),
):
    db = SessionLocal()
    try:
        if not has_perm(current_user, "manager.access"):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"success": False, "message": "Permessi insufficienti"},
            )

        try:
            task = _create_site_task(
                db,
                site_id=site_id,
                title=title,
                description=description,
                status_value=status_value,
                priority_value=priority_value,
                assigned_to_id=assigned_to_id,
                due_date=due_date,
                current_user=current_user,
            )
            db.flush()
            db.refresh(task)
            open_count = _get_open_count_for_site(db, task.site_id)
            db.commit()
        finally:
            db.close()

        return JSONResponse(
            {
                "success": True,
                "message": "Nota operativa creata con successo",
                "task": _serialize_site_task(task),
                "open_count": open_count,
            }
        )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": str(exc.detail) if exc.detail else "Errore durante la creazione della nota",
            },
        )
    except Exception:
        logger.exception("Errore inatteso durante la creazione della nota operativa da modal")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "Errore inatteso durante la creazione della nota operativa",
            },
        )


@app.post("/manager/cantieri/{site_id}/tasks/{task_id}/edit", name="manager_site_task_update")
def manager_site_task_update(
    request: Request,
    site_id: int,
    task_id: int,
    title: str = Form(...),
    description: str = Form(""),
    status_value: str = Form("da_fare"),
    priority_value: str = Form("media"),
    assigned_to_id: str | None = Form(None),
    due_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    wants_json = _request_wants_json(request)
    db = SessionLocal()
    try:
        _get_site_for_detail(db, site_id, current_user)
        task = db.query(SiteTask).filter(SiteTask.id == task_id, SiteTask.site_id == site_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task non trovato")
        if not title.strip():
            raise HTTPException(status_code=400, detail="Titolo obbligatorio")
        task.title = title.strip()
        task.description = (description or "").strip() or None
        task.status = _parse_site_task_status(status_value)
        task.priority = _parse_site_task_priority(priority_value)
        task.due_date = _parse_optional_date(due_date)
        task.updated_by_id = current_user.id
        if assigned_to_id in (None, ""):
            task.assigned_to_id = None
        else:
            try:
                assigned_user_id = int(assigned_to_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Assegnatario non valido") from exc
            assigned_to = db.query(User).filter(User.id == assigned_user_id).first()
            if not assigned_to:
                raise HTTPException(status_code=400, detail="Assegnatario non trovato")
            task.assigned_to_id = assigned_user_id
        _normalize_task_completion(task, current_user.id)
        db.add(task)
        db.flush()
        db.refresh(task)
        open_count = _get_open_count_for_site(db, site_id)
        recent_completed_tasks = []
        if _is_task_completed(task):
            recent_completed_tasks = _get_recent_completed_tasks_for_overview(db, current_user)
        db.commit()
        if wants_json:
            return JSONResponse(
                {
                    "success": True,
                    "message": "Nota aggiornata",
                    "task": _serialize_site_task(task),
                    "open_count": open_count,
                    "recent_completed_tasks": [
                        _serialize_site_task(completed_task) for completed_task in recent_completed_tasks
                    ],
                }
            )
    finally:
        db.close()
    return RedirectResponse(
        url=_build_site_task_redirect_url(request, site_id),
        status_code=303,
    )


@app.post("/manager/cantieri/{site_id}/tasks/{task_id}/complete", name="manager_site_task_complete")
def manager_site_task_complete(
    request: Request,
    site_id: int,
    task_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    wants_json = _request_wants_json(request)
    db = SessionLocal()
    try:
        _get_site_for_detail(db, site_id, current_user)
        task = db.query(SiteTask).filter(SiteTask.id == task_id, SiteTask.site_id == site_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task non trovato")
        task.status = SiteTaskStatusEnum.completato
        task.completed = True
        task.updated_by_id = current_user.id
        _normalize_task_completion(task, current_user.id)
        db.add(task)
        db.flush()
        db.refresh(task)
        open_count = _get_open_count_for_site(db, site_id)
        recent_completed_tasks = _get_recent_completed_tasks_for_overview(db, current_user)
        db.commit()
        if wants_json:
            return JSONResponse(
                {
                    "success": True,
                    "message": "Nota completata",
                    "task": _serialize_site_task(task),
                    "open_count": open_count,
                    "recent_completed_tasks": [
                        _serialize_site_task(completed_task) for completed_task in recent_completed_tasks
                    ],
                }
            )
    finally:
        db.close()
    return RedirectResponse(
        url=_build_site_task_redirect_url(request, site_id),
        status_code=303,
    )


@app.post("/manager/cantieri/{site_id}/tasks/{task_id}/reopen", name="manager_site_task_reopen")
def manager_site_task_reopen(
    request: Request,
    site_id: int,
    task_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    wants_json = _request_wants_json(request)
    db = SessionLocal()
    try:
        _get_site_for_detail(db, site_id, current_user)
        task = db.query(SiteTask).filter(SiteTask.id == task_id, SiteTask.site_id == site_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task non trovato")
        task.status = SiteTaskStatusEnum.da_fare
        task.completed = False
        task.updated_by_id = current_user.id
        _normalize_task_completion(task, current_user.id)
        db.add(task)
        db.flush()
        db.refresh(task)
        open_count = _get_open_count_for_site(db, site_id)
        recent_completed_tasks = _get_recent_completed_tasks_for_overview(db, current_user)
        db.commit()
        if wants_json:
            return JSONResponse(
                {
                    "success": True,
                    "message": "Nota riaperta",
                    "task": _serialize_site_task(task),
                    "open_count": open_count,
                    "recent_completed_tasks": [
                        _serialize_site_task(completed_task) for completed_task in recent_completed_tasks
                    ],
                }
            )
    finally:
        db.close()
    return RedirectResponse(
        url=_build_site_task_redirect_url(request, site_id),
        status_code=303,
    )


@app.post("/manager/cantieri/{site_id}/tasks/{task_id}/delete", name="manager_site_task_delete")
def manager_site_task_delete(
    request: Request,
    site_id: int,
    task_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    wants_json = _request_wants_json(request)
    db = SessionLocal()
    try:
        _get_site_for_detail(db, site_id, current_user)
        task = db.query(SiteTask).filter(SiteTask.id == task_id, SiteTask.site_id == site_id).first()
        if not task:
            if wants_json:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": "Task non trovato"},
                )
            return RedirectResponse(
                url=_build_site_task_redirect_url(request, site_id),
                status_code=303,
            )
        if task:
            db.delete(task)
            db.flush()
            open_count = _get_open_count_for_site(db, site_id)
            recent_completed_tasks = _get_recent_completed_tasks_for_overview(db, current_user)
            db.commit()
            if wants_json:
                return JSONResponse(
                    {
                        "success": True,
                        "message": "Nota eliminata",
                        "task_id": task_id,
                        "site_id": site_id,
                        "open_count": open_count,
                        "recent_completed_tasks": [
                            _serialize_site_task(completed_task) for completed_task in recent_completed_tasks
                        ],
                    }
                )
    finally:
        db.close()
    return RedirectResponse(
        url=_build_site_task_redirect_url(request, site_id),
        status_code=303,
    )


@app.get("/manager/note-operative", response_class=HTMLResponse, name="manager_site_tasks_overview")
def manager_site_tasks_overview(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        sites = (
            scope_sites_query(
                db.query(Site).options(joinedload(Site.caposquadra)),
                current_user,
            )
            .filter(
                Site.is_active.is_(True),
                Site.status.in_([SiteStatusEnum.aperto, SiteStatusEnum.pianificato]),
            )
            .order_by(Site.name.asc())
            .all()
        )
        site_ids = [site.id for site in sites]
        tasks_by_site: dict[int, dict[str, list[SiteTask]]] = {site.id: {"open": []} for site in sites}
        open_counts_by_site: dict[int, int] = {site.id: 0 for site in sites}
        recent_completed_tasks: list[SiteTask] = []

        if site_ids:
            open_tasks = (
                db.query(SiteTask)
                .options(
                    joinedload(SiteTask.assigned_to),
                    joinedload(SiteTask.created_by),
                    joinedload(SiteTask.updated_by),
                    joinedload(SiteTask.completed_by),
                )
                .filter(
                    SiteTask.site_id.in_(site_ids),
                    _site_task_open_clause(),
                )
                .order_by(
                    SiteTask.site_id.asc(),
                    SiteTask.priority.desc(),
                    SiteTask.due_date.asc().nulls_last(),
                    SiteTask.created_at.desc(),
                )
                .all()
            )
            for task in open_tasks:
                tasks_by_site.setdefault(task.site_id, {"open": []})["open"].append(task)

            open_count_rows = (
                db.query(SiteTask.site_id, func.count(SiteTask.id))
                .filter(
                    SiteTask.site_id.in_(site_ids),
                    _site_task_open_clause(),
                )
                .group_by(SiteTask.site_id)
                .all()
            )
            open_counts_by_site = {site_id: int(count or 0) for site_id, count in open_count_rows}
            recent_completed_tasks = (
                db.query(SiteTask)
                .options(
                    joinedload(SiteTask.site),
                    joinedload(SiteTask.created_by),
                    joinedload(SiteTask.completed_by),
                )
                .filter(
                    SiteTask.site_id.in_(site_ids),
                    _site_task_completed_clause(),
                )
                .order_by(
                    SiteTask.completed_at.desc().nulls_last(),
                    SiteTask.updated_at.desc(),
                )
                .limit(5)
                .all()
            )

        manager_users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .filter(User.role.in_([RoleEnum.admin, RoleEnum.manager]))
            .order_by(User.full_name, User.email)
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/site_tasks_overview.html",
        build_template_context(
            request,
            current_user,
            active_sites=sites,
            tasks_by_site=tasks_by_site,
            open_counts_by_site=open_counts_by_site,
            recent_completed_tasks=recent_completed_tasks,
            manager_users=manager_users,
            site_task_status_values=SITE_TASK_STATUSES,
            site_task_priority_values=SITE_TASK_PRIORITIES,
        ),
    )


@app.get("/manager/note-operative/storico", response_class=HTMLResponse, name="manager_site_tasks_history")
def manager_site_tasks_history(
    request: Request,
    site_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    priority: str | None = None,
    completed_by_id: str | None = None,
    q: str | None = None,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        sites = (
            scope_sites_query(
                db.query(Site),
                current_user,
            )
            .order_by(Site.name.asc())
            .all()
        )
        site_ids = [site.id for site in sites]

        query = (
            db.query(SiteTask)
            .options(
                joinedload(SiteTask.site),
                joinedload(SiteTask.assigned_to),
                joinedload(SiteTask.created_by),
                joinedload(SiteTask.completed_by),
            )
            .filter(
                SiteTask.site_id.in_(site_ids),
                _site_task_completed_clause(),
            )
        )

        selected_site_id: int | None = None
        if site_id and site_id.isdigit():
            selected_site_id = int(site_id)
            query = query.filter(SiteTask.site_id == selected_site_id)

        selected_completed_by_id: int | None = None
        if completed_by_id and completed_by_id.isdigit():
            selected_completed_by_id = int(completed_by_id)
            query = query.filter(SiteTask.completed_by_id == selected_completed_by_id)

        selected_priority = None
        if priority:
            selected_priority = _parse_site_task_priority(priority)
            query = query.filter(SiteTask.priority == selected_priority)

        parsed_date_from = _parse_optional_date(date_from)
        if parsed_date_from:
            query = query.filter(func.date(SiteTask.completed_at) >= parsed_date_from)

        parsed_date_to = _parse_optional_date(date_to)
        if parsed_date_to:
            query = query.filter(func.date(SiteTask.completed_at) <= parsed_date_to)

        search_term = (q or "").strip()
        if search_term:
            pattern = f"%{search_term}%"
            query = query.filter(
                or_(
                    SiteTask.title.ilike(pattern),
                    SiteTask.description.ilike(pattern),
                )
            )

        completed_tasks = query.order_by(
            SiteTask.completed_at.desc().nulls_last(),
            SiteTask.updated_at.desc(),
        ).all()

        completer_ids = {task.completed_by_id for task in completed_tasks if task.completed_by_id}
        completers = (
            db.query(User)
            .filter(User.id.in_(completer_ids))
            .order_by(User.full_name, User.email)
            .all()
            if completer_ids
            else []
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/site_tasks_history.html",
        build_template_context(
            request,
            current_user,
            completed_tasks=completed_tasks,
            sites=sites,
            completers=completers,
            selected_site_id=selected_site_id,
            selected_priority=selected_priority.value if selected_priority else "",
            selected_completed_by_id=selected_completed_by_id,
            date_from=date_from or "",
            date_to=date_to or "",
            q=q or "",
            site_task_priority_values=SITE_TASK_PRIORITIES,
        ),
    )


@app.get("/manager/cantieri/{site_id}/modifica", response_class=HTMLResponse)
def manager_cantiere_modifica_get(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role == RoleEnum.caposquadra:
        pass
    elif not has_perm(current_user, "sites.update"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    lang = request.cookies.get("lang", "it")
    db = SessionLocal()
    try:
        site = (
            db.query(Site)
            .options(joinedload(Site.strut_levels))
            .filter(Site.id == site_id)
            .first()
        )
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        if current_user.role == RoleEnum.caposquadra and site.caposquadra_id != current_user.id:
            raise HTTPException(status_code=403, detail="Permessi insufficienti")
        site_status_values = get_cached_site_status_values()
        capisquadra = (
            db.query(User)
            .filter(User.role == RoleEnum.caposquadra)
            .filter(User.is_active.is_(True))
            .order_by(User.full_name, User.email)
            .all()
        )
        scarichi_recenti = (
            db.query(MagazzinoMovimento)
            .options(
                joinedload(MagazzinoMovimento.item),
                joinedload(MagazzinoMovimento.creato_da_user),
            )
            .filter(
                MagazzinoMovimento.cantiere_id == site_id,
                MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
            )
            .order_by(MagazzinoMovimento.created_at.desc())
            .limit(20)
            .all()
        )
        progress_summary, strut_levels_view, strut_levels_count = _build_site_progress(
            site, lang
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/cantiere_form.html",
        build_template_context(
            request,
            current_user,
            mode="edit",
            site=site,
            site_status_values=site_status_values,
            scarichi_recenti=scarichi_recenti,
            capisquadra=capisquadra,
            google_maps_api_key=google_maps_api_key,
            progress_summary=progress_summary,
            strut_levels=strut_levels_view,
            strut_levels_count=strut_levels_count,
        ),
    )


@app.post("/manager/cantieri/{site_id}/modifica")
def manager_cantiere_modifica_post(
    request: Request,
    site_id: int,
    name: str = Form(...),
    code: str = Form(...),
    address: str | None = Form(None),
    lat: str | None = Form(None),
    lng: str | None = Form(None),
    place_id: str | None = Form(None),
    confirm_unverified: str | None = Form(None),
    city: str | None = Form(None),
    country: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    status: str = Form(...),
    is_active: str | None = Form(None),
    caposquadra_id: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role == RoleEnum.caposquadra:
        pass
    elif not has_perm(current_user, "sites.update"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    is_caposquadra = current_user.role == RoleEnum.caposquadra

    if not name or not code:
        raise HTTPException(status_code=400, detail="Nome e codice sono obbligatori")

    def parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def parse_caposquadra(value: str | None) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def parse_coordinate(value: str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    start_date_parsed = parse_date(start_date)
    end_date_parsed = parse_date(end_date)
    lat_value = parse_coordinate(lat)
    lng_value = parse_coordinate(lng)
    has_address = bool(address and address.strip())

    if status not in SiteStatusEnum.__members__:
        raise HTTPException(status_code=400, detail="Stato non valido")
    status_value = SiteStatusEnum[status]

    if not is_caposquadra:
        if (
            has_address
            and (lat_value is None or lng_value is None)
            and confirm_unverified is None
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Seleziona un indirizzo dai suggerimenti o clicca sulla mappa per "
                    "impostare la posizione, oppure conferma per salvare senza coordinate."
                ),
            )

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        if is_caposquadra and site.caposquadra_id != current_user.id:
            raise HTTPException(status_code=403, detail="Permessi insufficienti")

        if is_caposquadra:
            address = site.address
            lat_value = site.lat
            lng_value = site.lng
            place_id = site.place_id

        parsed_capo_id = parse_caposquadra(caposquadra_id)
        if parsed_capo_id is not None:
            capo = (
                db.query(User)
                .filter(User.id == parsed_capo_id)
                .filter(User.role == RoleEnum.caposquadra)
                .filter(User.is_active.is_(True))
                .first()
            )
            if not capo:
                raise HTTPException(status_code=400, detail="Caposquadra non valido")

        previous_status = site.status.value if site.status else None
        site.name = name
        site.code = code
        site.address = address
        site.lat = lat_value
        site.lng = lng_value
        site.place_id = place_id or None
        site.city = city
        site.country = country
        site.start_date = start_date_parsed
        site.end_date = end_date_parsed
        site.status = status_value
        site.is_active = is_active is not None
        site.caposquadra_id = parsed_capo_id

        new_status = site.status.value if site.status else None
        if previous_status != new_status:
            notify_site_status_change(
                db,
                site,
                previous_status,
                new_status,
                current_user,
            )

        log_audit_event(
            db,
            current_user,
            "SITE_UPDATED",
            "site",
            site.id,
            {
                "name": site.name,
                "code": site.code,
                "status": site.status.value if site.status else None,
                "is_active": site.is_active,
            },
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/manager/cantieri", status_code=303)


@app.get(
    "/capo/cantieri/{site_id}",
    response_class=HTMLResponse,
    name="capo_site_detail",
)
def capo_site_detail(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = get_site_for_user(db, site_id, current_user)
        site_tasks, open_tasks, completed_tasks = _load_site_tasks_for_site_detail(db, site_id)
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capo/site_detail.html",
        build_template_context(
            request,
            current_user,
            site=site,
            site_tasks=site_tasks,
            open_tasks=open_tasks,
            completed_tasks=completed_tasks,
            can_add_tasks=has_perm(current_user, "manager.access"),
        ),
    )


@app.get("/capo/dashboard", response_class=HTMLResponse)
def capo_dashboard(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Dashboard caposquadra con funzioni limitate ai cantieri assegnati.
    """
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    db = SessionLocal()
    try:
        query_started = time.monotonic()
        assigned_sites_query = db.query(Site).filter(
            Site.is_active.is_(True),
            Site.lat.isnot(None),
            Site.lng.isnot(None),
        )
        assigned_sites_query = scope_sites_query(assigned_sites_query, current_user)
        assigned_sites_with_coords = (
            assigned_sites_query.options(
                load_only(
                    Site.id,
                    Site.name,
                    Site.address,
                    Site.city,
                    Site.country,
                    Site.lat,
                    Site.lng,
                    Site.status,
                    Site.is_active,
                    Site.caposquadra_id,
                )
            )
            .order_by(Site.name)
            .all()
        )
        perf_logger.debug(
            "capo_dashboard assigned_sites rows=%s duration_ms=%.2f",
            len(assigned_sites_with_coords),
            (time.monotonic() - query_started) * 1000,
        )
        assigned_sites_map_data = _build_sites_map_data(assigned_sites_with_coords)

        query_started = time.monotonic()
        kpi_reports_today = (
            db.query(func.count(Report.id))
            .filter(Report.created_by_id == current_user.id)
            .filter(Report.date == today)
            .scalar()
            or 0
        )
        perf_logger.debug(
            "capo_dashboard kpi_reports_today duration_ms=%.2f",
            (time.monotonic() - query_started) * 1000,
        )

        query_started = time.monotonic()
        kpi_hours_this_week = (
            db.query(func.coalesce(func.sum(Report.total_hours), 0.0))
            .filter(Report.created_by_id == current_user.id)
            .filter(Report.date >= start_of_week)
            .scalar()
            or 0
        )
        perf_logger.debug(
            "capo_dashboard kpi_hours_this_week duration_ms=%.2f",
            (time.monotonic() - query_started) * 1000,
        )

        query_started = time.monotonic()
        kpi_assigned_sites = (
            db.query(func.count(Site.id))
            .filter(Site.caposquadra_id == current_user.id)
            .filter(Site.is_active.is_(True))
            .scalar()
            or 0
        )
        perf_logger.debug(
            "capo_dashboard kpi_assigned_sites duration_ms=%.2f",
            (time.monotonic() - query_started) * 1000,
        )

        query_started = time.monotonic()
        kpi_open_reports = (
            db.query(func.count(Report.id))
            .filter(Report.created_by_id == current_user.id)
            .filter(func.coalesce(Report.total_hours, 0) <= 0)
            .scalar()
            or 0
        )
        perf_logger.debug(
            "capo_dashboard kpi_open_reports duration_ms=%.2f",
            (time.monotonic() - query_started) * 1000,
        )

    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capo/home_capo.html",
        build_template_context(
            request,
            current_user,
            user_role="capo",
            kpi_reports_today=kpi_reports_today,
            kpi_hours_this_week=kpi_hours_this_week,
            kpi_assigned_sites=kpi_assigned_sites,
            kpi_open_reports=kpi_open_reports,
            cantieri_map_data=jsonable_encoder(assigned_sites_map_data),
            detail_url_template=str(
                request.url_for("capo_site_detail", site_id="__SITE_ID__")
            ),
            google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        ),
    )


def _get_capo_assigned_sites(db: SessionLocal, capo: User) -> list[Site]:
    return (
        db.query(Site)
        .filter(Site.caposquadra_id == capo.id)
        .filter(Site.is_active.is_(True))
        .order_by(Site.name.asc())
        .all()
    )


@app.get("/capo/rapportini/nuovo", response_class=HTMLResponse)
def pagina_nuovo_rapportino_capo(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Pagina per creare un nuovo rapportino giornaliero (caposquadra).
    Il JS della pagina chiamerà l'API POST /reports con il token JWT.
    """
    db = SessionLocal()
    try:
        cantieri = _get_capo_assigned_sites(db, current_user)
        operai_attivi = (
            db.query(Personale)
            .filter(Personale.attivo.is_(True))
            .order_by(Personale.cognome, Personale.nome)
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capo_nuovo_rapportino.html",
        build_template_context(
            request,
            current_user,
            cantieri=cantieri,
            operai_attivi=operai_attivi,
        ),
    )


@app.get("/capo/fiches/nuova", response_class=HTMLResponse)
def capo_fiche_nuova_get(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    sites, machines = _load_capo_form_collections(current_user)

    return templates.TemplateResponse(
        request,
        "capo/fiches_form.html",
        build_template_context(
            request,
            current_user,
            cantieri=sites,
            macchinari=machines,
            form_data=_build_fiche_form_data(),
            error_message=None,
        ),
    )


@app.post("/capo/fiches/nuova")
async def capo_fiche_nuova_post(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
    cantiere_id: int = Form(...),
    macchinario_id: str | None = Form(None),
    data_scavo: date = Form(...),
    data_getto: date | None = Form(None),
    metri_cubi_gettati: float | None = Form(None),
    operatore: str = Form(...),
    descrizione: str = Form(""),
    ore_lavorate: float = Form(...),
    note: str | None = Form(None),
    tipologia_scavo: str | None = Form(None),
    stratigrafia: str | None = Form(None),
    materiale: str | None = Form(None),
    profondita_totale: float | None = Form(None),
    diametro_palo_cm: float | None = Form(None),
    larghezza_pannello: float | None = Form(None),
    altezza_pannello: float | None = Form(None),
    strato_da: List[float] = Form(default_factory=list),
    strato_a: List[float] = Form(default_factory=list),
    strato_materiale: List[str] = Form(default_factory=list),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    try:
        parsed_machine_id: int | None = None
        if macchinario_id not in (None, ""):
            parsed_machine_id = int(macchinario_id)

        diametro_value_cm = diametro_palo_cm
        diametro_value_m = (
            diametro_value_cm / 100 if diametro_value_cm is not None else None
        )

        _validate_fiche_geometria(
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            profondita_totale=profondita_totale,
        )

        db = SessionLocal()
        try:
            allowed_sites = _get_capo_assigned_sites(db, current_user)
            allowed_site_ids = {s.id for s in allowed_sites}
            site = db.query(Site).filter(Site.id == cantiere_id).first()
            if not site or (allowed_site_ids and site.id not in allowed_site_ids):
                raise HTTPException(status_code=403, detail="Cantiere non valido")

            if parsed_machine_id is not None:
                machine = (
                    db.query(Machine).filter(Machine.id == parsed_machine_id).first()
                )
                if not machine:
                    raise HTTPException(status_code=400, detail="Macchinario non trovato")

            fiche = Fiche(
                date=data_scavo,
                site_id=cantiere_id,
                machine_id=parsed_machine_id,
                fiche_type=FicheTypeEnum.produzione,
                description=descrizione or "",
                operator=operatore,
                hours=ore_lavorate,
                notes=note or None,
                tipologia_scavo=tipologia_scavo or None,
                stratigrafia=stratigrafia or None,
                materiale=materiale or None,
                profondita_totale=profondita_totale,
                diametro_palo=diametro_value_m,
                larghezza_pannello=larghezza_pannello,
                altezza_pannello=altezza_pannello,
                data_getto=data_getto,
                metri_cubi_gettati=metri_cubi_gettati,
                created_by_id=current_user.id,
            )
            db.add(fiche)
            db.commit()
            db.refresh(fiche)

            for da_val, a_val, mat in zip(strato_da, strato_a, strato_materiale):
                if not mat:
                    continue
                if da_val is None or a_val is None:
                    continue
                if a_val <= da_val:
                    continue
                layer = FicheStratigrafia(
                    fiche_id=fiche.id,
                    da_profondita=da_val,
                    a_profondita=a_val,
                    materiale=mat,
                )
                db.add(layer)
            db.commit()
        finally:
            db.close()
    except ValueError:
        form_data = _build_fiche_form_data(
            cantiere_id=cantiere_id,
            macchinario_id=macchinario_id,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            stratigrafia=stratigrafia,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo=diametro_value_m,
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
        )
        sites, machines = _load_capo_form_collections(current_user)
        return templates.TemplateResponse(
            request,
            "capo/fiches_form.html",
            build_template_context(
                request,
                current_user,
                cantieri=sites,
                macchinari=machines,
                form_data=form_data,
                error_message="Macchinario non valido",
            ),
            status_code=400,
        )
    except HTTPException as exc:
        status_code = exc.status_code or 400
        form_data = _build_fiche_form_data(
            cantiere_id=cantiere_id,
            macchinario_id=macchinario_id,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            stratigrafia=stratigrafia,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo=diametro_value_m,
            diametro_palo_cm=diametro_value_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
        )
        sites, machines = _load_capo_form_collections(current_user)
        return templates.TemplateResponse(
            request,
            "capo/fiches_form.html",
            build_template_context(
                request,
                current_user,
                cantieri=sites,
                macchinari=machines,
                form_data=form_data,
                error_message=exc.detail,
            ),
            status_code=status_code,
        )

    return RedirectResponse(url="/capo/dashboard", status_code=303)


@app.get(
    "/manager/fiches",
    response_class=HTMLResponse,
    name="manager_fiches_list",
)
def manager_fiches(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    site_id: str | None = None,
    fiche_type: str | None = None,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()

    parsed_from_date: date | None = None
    parsed_to_date: date | None = None
    parsed_site_id: int | None = None
    parsed_fiche_type: FicheTypeEnum | None = None

    try:
        if from_date:
            try:
                parsed_from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
            except ValueError:
                parsed_from_date = None

        if to_date:
            try:
                parsed_to_date = datetime.strptime(to_date, "%Y-%m-%d").date()
            except ValueError:
                parsed_to_date = None

        if site_id:
            try:
                parsed_site_id = int(site_id)
            except ValueError:
                parsed_site_id = None

        if fiche_type:
            try:
                parsed_fiche_type = FicheTypeEnum(fiche_type)
            except ValueError:
                parsed_fiche_type = None

        query = db.query(Fiche).options(
            joinedload(Fiche.site),
            joinedload(Fiche.machine),
            joinedload(Fiche.created_by),
        )

        if parsed_from_date:
            query = query.filter(Fiche.date >= parsed_from_date)
        if parsed_to_date:
            query = query.filter(Fiche.date <= parsed_to_date)
        if parsed_site_id:
            query = query.filter(Fiche.site_id == parsed_site_id)
        if parsed_fiche_type:
            query = query.filter(Fiche.fiche_type == parsed_fiche_type)

        fiches_list = query.order_by(Fiche.date.desc(), Fiche.id.desc()).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/fiches_list.html",
        build_template_context(
            request,
            current_user,
            fiches=fiches_list,
            total_fiches=len(fiches_list),
        ),
    )


@app.get(
    "/manager/fiches/{fiche_id}",
    response_class=HTMLResponse,
    name="manager_fiches_detail",
)
def manager_fiche_dettaglio(
    request: Request,
    fiche_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()
    try:
        fiche = (
            db.query(Fiche)
            .options(
                joinedload(Fiche.site),
                joinedload(Fiche.machine),
                joinedload(Fiche.created_by),
                joinedload(Fiche.stratigrafie),
                joinedload(Fiche.layers),
            )
            .filter(Fiche.id == fiche_id)
            .first()
        )
        if not fiche:
            return RedirectResponse(
                url=request.url_for("manager_fiches_list"), status_code=303
            )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/fiches/fiche_detail.html",
        build_template_context(
            request,
            current_user,
            fiche=fiche,
        ),
    )


# -------------------------------------------------
# INCLUDE DEI ROUTER API
# -------------------------------------------------

app.include_router(auth_router)       # /auth/token, /auth/me
app.include_router(users.router)      # /users
app.include_router(sites.router)      # /sites
app.include_router(machines.router)   # /machines
app.include_router(reports.router)    # /reports
app.include_router(fiches.router)     # /fiches
app.include_router(notifications.router)
app.include_router(manager_personale.router)
app.include_router(manager_veicoli.router)
app.include_router(manager_depositi.router)
app.include_router(magazzino.router)
app.include_router(ordini.router)
app.include_router(audit.router)
app.include_router(reportistica.router)
app.include_router(backup.router)
app.include_router(trasporti.router)
app.include_router(economics.router)
