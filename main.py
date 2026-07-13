import logging
import json
import os
import time
import re
import uuid
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta
from math import ceil, pi
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
    ReportWorker,
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
    SiteProgressGridName,
    SiteCoupe,
    SiteCoupeAssignment,
    SiteSpecialEquipmentConfig,
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
from notifications import (
    notify_new_fiche,
    notify_new_report,
    notify_new_site_task,
    notify_site_status_change,
)
from services.personale_profiles import ensure_user_personale_profile
from audit_utils import log_audit_event
from logging_config import configure_logging

from db_upgrade import upgrade_db, check_db_schema
from utils.db_check import check_and_suggest_db_upgrade
from utils.trips import compute_trip_progress
from utils.reports import report_man_hours, report_total_hours
from utils.production_stats import compute_site_production


configure_logging()

logger = logging.getLogger("lenta_france_gestionale.errors")
perf_logger = logging.getLogger("lenta_france_gestionale.performance")

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100
CAPO_REPORT_CREATED_REDIRECT_URL = "/capo/dashboard?rapportino_created=1"
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
templates.env.globals["report_total_hours"] = report_total_hours
templates.env.globals["report_man_hours"] = report_man_hours


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
    tipologia_scavo: str,
    diametro_palo_cm: float | None,
    larghezza_pannello: float | None,
    altezza_pannello: float | None,
    profondita_totale: float | None,
) -> None:
    if profondita_totale is None or profondita_totale <= 0:
        raise HTTPException(
            status_code=400,
            detail="La profondità totale deve essere maggiore di zero.",
        )

    if tipologia_scavo == "palo":
        if diametro_palo_cm is None:
            raise HTTPException(
                status_code=400,
                detail="Inserisci il diametro del palo in centimetri.",
            )
        if diametro_palo_cm <= 0:
            raise HTTPException(
                status_code=400,
                detail="Il diametro del palo deve essere maggiore di zero.",
            )
        return

    if tipologia_scavo == "paratia":
        if larghezza_pannello is None or altezza_pannello is None:
            raise HTTPException(
                status_code=400,
                detail="Per la paratia devi indicare larghezza e spessore pannello.",
            )
        if larghezza_pannello <= 0:
            raise HTTPException(
                status_code=400,
                detail="La larghezza del pannello deve essere maggiore di zero.",
            )
        if altezza_pannello <= 0:
            raise HTTPException(
                status_code=400,
                detail="Lo spessore del pannello deve essere maggiore di zero.",
            )


FICHE_STRATIGRAFIA_DEPTH_ERROR = (
    "La profondità totale scavata deve corrispondere all’ultimo strato di stratigrafia"
)


def _parse_decimal_comma_float(
    value: str | int | float | None, field_label: str
) -> float | None:
    if value in (None, ""):
        return None
    normalized_value = str(value).strip().replace(",", ".")
    if not normalized_value:
        return None
    try:
        return float(normalized_value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Il campo {field_label} non è valido.",
        )


def _parse_decimal_comma_float_list(
    values: list[str | int | float | None] | None, field_label: str
) -> list[float | None]:
    return [
        _parse_decimal_comma_float(value, field_label)
        for value in (values or [])
    ]


def _parse_courbe_points(
    volumes: list[str | int | float | None] | None,
    hauteurs: list[str | int | float | None] | None,
    *,
    label: str,
) -> list[dict[str, float]]:
    volumes = volumes or []
    hauteurs = hauteurs or []
    max_len = max(len(volumes), len(hauteurs), 0)
    points: list[dict[str, float]] = []
    for index in range(max_len):
        volume_raw = volumes[index] if index < len(volumes) else None
        hauteur_raw = hauteurs[index] if index < len(hauteurs) else None
        volume = _parse_decimal_comma_float(volume_raw, f"{label} volume")
        hauteur = _parse_decimal_comma_float(hauteur_raw, f"{label} hauteur")
        if volume is None and hauteur is None:
            continue
        if volume is None or hauteur is None:
            raise HTTPException(
                status_code=400,
                detail=f"Chaque ligne {label} doit avoir Volume (m³) et Hauteur (m).",
            )
        if volume < 0:
            raise HTTPException(status_code=400, detail=f"Le volume {label} ne peut pas être négatif.")
        points.append({"volume": volume, "hauteur": hauteur})
    points.sort(key=lambda point: point["volume"])
    return points


def _serialize_courbe_points(points: list[dict[str, float]]) -> str | None:
    if not points:
        return None
    return json.dumps(points, ensure_ascii=False, separators=(",", ":"))


def _deserialize_courbe_points(raw_points: str | None) -> list[dict[str, float]]:
    if not raw_points:
        return []
    try:
        decoded = json.loads(raw_points)
    except (TypeError, ValueError):
        return []
    points: list[dict[str, float]] = []
    for item in decoded if isinstance(decoded, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            volume = float(item.get("volume"))
            hauteur = float(item.get("hauteur"))
        except (TypeError, ValueError):
            continue
        points.append({"volume": volume, "hauteur": hauteur})
    points.sort(key=lambda point: point["volume"])
    return points


def _apply_courbe_beton_fields(
    fiche: Fiche,
    *,
    courbe_beton_active: str | bool | None,
    courbe_realisee_volume: list[str | float | None] | None,
    courbe_realisee_hauteur: list[str | float | None] | None,
    courbe_tube_volume: list[str | float | None] | None = None,
    courbe_tube_hauteur: list[str | float | None] | None = None,
    courbe_beton_volume_total: str | float | None = None,
    courbe_beton_hauteur_initiale: str | float | None = None,
    courbe_beton_hauteur_finale: str | float | None = None,
) -> None:
    active = courbe_beton_active in (True, "1", "true", "on", "yes", "oui", "si")
    fiche.courbe_beton_active = active
    if not active:
        fiche.courbe_beton_realisee = None
        fiche.courbe_beton_tube = None
        fiche.courbe_beton_volume_total = None
        fiche.courbe_beton_hauteur_initiale = None
        fiche.courbe_beton_hauteur_finale = None
        return

    fiche.courbe_beton_realisee = _serialize_courbe_points(
        _parse_courbe_points(courbe_realisee_volume, courbe_realisee_hauteur, label="Réalisée")
    )
    fiche.courbe_beton_tube = _serialize_courbe_points(
        _parse_courbe_points(courbe_tube_volume, courbe_tube_hauteur, label="Tube")
    )
    volume_total = _parse_decimal_comma_float(courbe_beton_volume_total, "volume total théorique")
    hauteur_initiale = _parse_decimal_comma_float(courbe_beton_hauteur_initiale, "hauteur initiale")
    if volume_total is not None and volume_total < 0:
        raise HTTPException(status_code=400, detail="Le volume total théorique ne peut pas être négatif.")
    fiche.courbe_beton_volume_total = volume_total
    fiche.courbe_beton_hauteur_initiale = hauteur_initiale
    fiche.courbe_beton_hauteur_finale = 0


def _build_courbe_beton_payload(fiche: Fiche) -> dict:
    realised = _deserialize_courbe_points(getattr(fiche, "courbe_beton_realisee", None))
    tube = _deserialize_courbe_points(getattr(fiche, "courbe_beton_tube", None))
    theoretical = []
    if fiche.courbe_beton_volume_total is not None and fiche.courbe_beton_hauteur_initiale is not None:
        theoretical = [
            {"volume": 0, "hauteur": float(fiche.courbe_beton_hauteur_initiale)},
            {"volume": float(fiche.courbe_beton_volume_total), "hauteur": 0.0},
        ]
    return {"realisee": realised, "theorique": theoretical, "tube": tube}


def _invalid_fields_for_fiche_error(error_message: str | None) -> list[str]:
    normalized_message = (error_message or "").lower()
    if error_message == FICHE_STRATIGRAFIA_DEPTH_ERROR:
        return ["profondita_totale", "strato_a_last"]
    if "profondità totale" in normalized_message or "profondita totale" in normalized_message:
        return ["profondita_totale"]
    if "stratigrafia" in normalized_message or "strato" in normalized_message:
        return ["stratigrafia"]
    return []


def _validate_fiche_stratigrafia(
    profondita_totale: float | None,
    strato_da: list[float] | None,
    strato_a: list[float] | None,
) -> None:
    strato_da = strato_da or []
    strato_a = strato_a or []
    max_len = max(len(strato_da), len(strato_a), 0)
    layers: list[tuple[float, float]] = []

    for index in range(max_len):
        da_val = strato_da[index] if index < len(strato_da) else None
        a_val = strato_a[index] if index < len(strato_a) else None
        if da_val is None or a_val is None:
            continue
        if da_val >= a_val:
            raise HTTPException(
                status_code=400,
                detail="Ogni valore Da (m) deve essere minore del relativo A (m).",
            )
        layers.append((da_val, a_val))

    if not layers:
        return

    previous_a = layers[0][1]
    for da_val, a_val in layers[1:]:
        if abs(da_val - previous_a) > 0.000001:
            raise HTTPException(
                status_code=400,
                detail="Gli strati di stratigrafia devono essere continui.",
            )
        previous_a = a_val

    if profondita_totale is None or abs(profondita_totale - layers[-1][1]) > 0.01:
        raise HTTPException(status_code=400, detail=FICHE_STRATIGRAFIA_DEPTH_ERROR)


def _validate_metri_cubi_gettati(metri_cubi_gettati: float | None) -> None:
    if metri_cubi_gettati is None:
        raise HTTPException(
            status_code=400,
            detail="Il campo Metri cubi gettati è obbligatorio.",
        )
    if metri_cubi_gettati < 0:
        raise HTTPException(
            status_code=400,
            detail="Il campo Metri cubi gettati non può essere negativo.",
        )


def _validate_quota_testa_getto_not_above_tn(
    quota_testa_getto: float | None,
    *,
    quota_tn: float | None,
) -> None:
    if quota_testa_getto is None or quota_tn is None:
        return
    if quota_testa_getto > quota_tn:
        raise HTTPException(
            status_code=400,
            detail="La quota testa getto non può essere superiore alla quota TN.",
        )


def _get_complete_stratigrafia_layers(
    strato_da: list[float | None] | None,
    strato_a: list[float | None] | None,
    strato_materiale: list[str] | None = None,
) -> list[tuple[float, float, str]]:
    strato_da = strato_da or []
    strato_a = strato_a or []
    strato_materiale = strato_materiale or []
    max_len = max(len(strato_da), len(strato_a), len(strato_materiale), 0)
    layers: list[tuple[float, float, str]] = []

    for index in range(max_len):
        da_val = strato_da[index] if index < len(strato_da) else None
        a_val = strato_a[index] if index < len(strato_a) else None
        material = strato_materiale[index] if index < len(strato_materiale) else ""
        if da_val is None or a_val is None:
            continue
        if da_val >= a_val:
            raise HTTPException(
                status_code=400,
                detail="Ogni valore Da (m) deve essere minore del relativo A (m).",
            )
        layers.append((float(da_val), float(a_val), material or ""))

    return layers


def _normalize_stratigrafia_materials(
    strato_materiale: list[str] | None,
    strato_materiale_altro: list[str] | None = None,
) -> list[str]:
    materials = list(strato_materiale or [])
    other_descriptions = list(strato_materiale_altro or [])
    for index, material in enumerate(materials):
        if (material or "").strip().lower() != "altro":
            continue
        description = (other_descriptions[index] if index < len(other_descriptions) else "").strip()
        if not description:
            raise HTTPException(
                status_code=400,
                detail="Décrire le sol rencontré est obligatoire pour le terrain Autre.",
            )
        materials[index] = f"Autre: {description}"
    return materials


def _validate_stratigrafia_matches_depth(
    profondita_totale: float | None,
    strato_da: list[float | None] | None,
    strato_a: list[float | None] | None,
    strato_materiale: list[str] | None = None,
) -> None:
    if profondita_totale is None:
        return

    layers = _get_complete_stratigrafia_layers(
        strato_da=strato_da,
        strato_a=strato_a,
        strato_materiale=strato_materiale,
    )
    if not layers:
        return

    valid_last_a = layers[-1][1]
    if abs(float(profondita_totale) - valid_last_a) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=FICHE_STRATIGRAFIA_DEPTH_ERROR,
        )


def _build_fiche_form_data(
    cantiere_id: int | str | None = None,
    numero_pannello: int | str | None = None,
    macchinario_id: int | str | None = None,
    capocantiere_id: int | str | None = None,
    coupe_id: int | str | None = None,
    scavo_da_tn: bool | str | None = True,
    quota_partenza: float | str | None = None,
    quota_testa_getto: float | str | None = None,
    data_scavo: date | None = None,
    data_getto: date | None = None,
    metri_cubi_gettati: float | None = None,
    operatore: str | None = None,
    descrizione: str | None = None,
    ore_lavorate: float | str | None = None,
    note: str | None = None,
    tipologia_scavo: str | None = None,
    stratigrafia: str | None = None,
    materiale: str | None = None,
    profondita_totale: float | None = None,
    diametro_palo: float | None = None,
    diametro_palo_cm: float | None = None,
    larghezza_pannello: float | None = None,
    altezza_pannello: float | None = None,
    quota_ngf_testa: float | str | None = None,
    quota_ngf_fondo: float | str | None = None,
    quota_ngf_note: str | None = None,
    courbe_beton_active: bool | str | None = False,
    courbe_beton_realisee: list[dict[str, float]] | None = None,
    courbe_beton_tube: list[dict[str, float]] | None = None,
    courbe_beton_volume_total: float | str | None = None,
    courbe_beton_hauteur_initiale: float | str | None = None,
    courbe_beton_hauteur_finale: float | str | None = None,
    sonic_previsto: bool | str | None = False,
    sonic_realizzato: bool | str | None = None,
    inclinometre_previsto: bool | str | None = False,
    inclinometre_realizzato: bool | str | None = None,
    strato_da: list[float] | None = None,
    strato_a: list[float] | None = None,
    strato_materiale: list[str] | None = None,
    strato_materiale_altro: list[str] | None = None,
    invalid_fields: list[str] | None = None,
) -> dict:
    def _fmt(value):
        return "" if value is None else str(value)

    strato_da = strato_da or []
    strato_a = strato_a or []
    strato_materiale = strato_materiale or []
    strato_materiale_altro = strato_materiale_altro or []
    courbe_beton_realisee = courbe_beton_realisee or []
    courbe_beton_tube = courbe_beton_tube or []

    max_len = max(len(strato_da), len(strato_a), len(strato_materiale), 1)
    strati = []
    for i in range(max_len):
        material_value = _fmt(strato_materiale[i]) if i < len(strato_materiale) else ""
        other_value = _fmt(strato_materiale_altro[i]) if i < len(strato_materiale_altro) else ""
        if material_value.lower().startswith("autre:"):
            other_value = material_value.split(":", 1)[1].strip()
            material_value = "altro"
        strati.append(
            {
                "da": _fmt(strato_da[i]) if i < len(strato_da) else "",
                "a": _fmt(strato_a[i]) if i < len(strato_a) else "",
                "materiale": material_value,
                "materiale_altro": other_value,
            }
        )

    cm_value = diametro_palo_cm
    if cm_value is None and diametro_palo is not None:
        cm_value = round(diametro_palo * 100, 1)

    return {
        "cantiere_id": _fmt(cantiere_id),
        "numero_pannello": _fmt(numero_pannello),
        "macchinario_id": _fmt(macchinario_id),
        "capocantiere_id": _fmt(capocantiere_id),
        "coupe_id": _fmt(coupe_id),
        "scavo_da_tn": "1" if scavo_da_tn in (True, "1", "true", "on", "si", "SI") else "0",
        "quota_partenza": _fmt(quota_partenza),
        "quota_testa_getto": _fmt(quota_testa_getto),
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
        "quota_ngf_testa": _fmt(quota_ngf_testa),
        "quota_ngf_fondo": _fmt(quota_ngf_fondo),
        "quota_ngf_note": quota_ngf_note or "",
        "courbe_beton_active": "1" if courbe_beton_active in (True, "1", "true", "on", "yes", "oui", "si") else "0",
        "courbe_beton_realisee": courbe_beton_realisee or [{"volume": "", "hauteur": ""}],
        "courbe_beton_tube": courbe_beton_tube or [{"volume": "", "hauteur": ""}],
        "courbe_beton_volume_total": _fmt(courbe_beton_volume_total),
        "courbe_beton_hauteur_initiale": _fmt(courbe_beton_hauteur_initiale),
        "courbe_beton_hauteur_finale": "0",
        "sonic_previsto": "1" if _parse_bool_choice(sonic_previsto) else "0",
        "sonic_realizzato": "" if _parse_bool_choice(sonic_realizzato) is None else ("1" if _parse_bool_choice(sonic_realizzato) else "0"),
        "inclinometre_previsto": "1" if _parse_bool_choice(inclinometre_previsto) else "0",
        "inclinometre_realizzato": "" if _parse_bool_choice(inclinometre_realizzato) is None else ("1" if _parse_bool_choice(inclinometre_realizzato) else "0"),
        "strati": strati,
        "invalid_fields": invalid_fields or [],
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


def _render_fiche_create_form(
    request: Request,
    current_user: User,
    *,
    template_name: str,
    collections_loader,
    status_code: int = 200,
    form_data: dict | None = None,
    error_message: str | None = None,
    extra_context: dict | None = None,
):
    sites, machines = collections_loader()
    db = SessionLocal()
    try:
        site_ids = [site.id for site in sites]
        coupes = (
            db.query(SiteCoupe)
            .options(joinedload(SiteCoupe.assignments))
            .filter(SiteCoupe.site_id.in_(site_ids))
            .order_by(SiteCoupe.site_id.asc(), SiteCoupe.nome.asc())
            .all()
            if site_ids else []
        )
        capocantieri = (
            db.query(User)
            .filter(User.is_active.is_(True), User.role.in_([RoleEnum.admin, RoleEnum.manager]))
            .order_by(User.full_name.asc(), User.email.asc())
            .all()
        )
        equipment_configs = (
            db.query(SiteSpecialEquipmentConfig)
            .filter(SiteSpecialEquipmentConfig.site_id.in_(site_ids))
            .order_by(
                SiteSpecialEquipmentConfig.site_id.asc(),
                SiteSpecialEquipmentConfig.tipologia_scavo.asc(),
                SiteSpecialEquipmentConfig.numero_elemento.asc(),
            )
            .all()
            if site_ids else []
        )
    finally:
        db.close()
    context = {
        "cantieri": sites,
        "macchinari": machines,
        "capocantieri": capocantieri,
        "coupes": coupes,
        "equipment_configs": _serialize_site_special_equipment_configs(equipment_configs),
        "form_data": form_data or _build_fiche_form_data(),
        "error_message": error_message,
    }
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(
        request,
        template_name,
        build_template_context(request, current_user, **context),
        status_code=status_code,
    )


def _build_fiche_error_form_data(
    *,
    cantiere_id: int | str | None,
    numero_pannello: int | str | None,
    macchinario_id: int | str | None,
    capocantiere_id: int | str | None = None,
    coupe_id: int | str | None = None,
    scavo_da_tn: bool | str | None = True,
    quota_partenza: float | str | None = None,
    quota_testa_getto: float | str | None = None,
    data_scavo: date | None = None,
    data_getto: date | None = None,
    metri_cubi_gettati: str | float | None = None,
    operatore: str | None = None,
    descrizione: str | None = None,
    ore_lavorate: str | float | None = None,
    note: str | None = None,
    tipologia_scavo: str | None = None,
    materiale: str | None = None,
    profondita_totale: str | float | None = None,
    diametro_palo_cm: str | float | None = None,
    larghezza_pannello: str | float | None = None,
    altezza_pannello: str | float | None = None,
    quota_ngf_testa: str | float | None = None,
    quota_ngf_fondo: str | float | None = None,
    quota_ngf_note: str | None = None,
    courbe_beton_active: bool | str | None = False,
    courbe_realisee_volume: list[str | float | None] | None = None,
    courbe_realisee_hauteur: list[str | float | None] | None = None,
    courbe_tube_volume: list[str | float | None] | None = None,
    courbe_tube_hauteur: list[str | float | None] | None = None,
    courbe_beton_volume_total: float | str | None = None,
    courbe_beton_hauteur_initiale: float | str | None = None,
    courbe_beton_hauteur_finale: float | str | None = None,
    sonic_previsto: bool | str | None = False,
    sonic_realizzato: bool | str | None = None,
    inclinometre_previsto: bool | str | None = False,
    inclinometre_realizzato: bool | str | None = None,
    strato_da: list[str | float | None] | None = None,
    strato_a: list[str | float | None] | None = None,
    strato_materiale: list[str] | None = None,
    strato_materiale_altro: list[str] | None = None,
    invalid_fields: list[str] | None = None,
) -> dict:
    return _build_fiche_form_data(
        cantiere_id=cantiere_id,
        numero_pannello=numero_pannello,
        macchinario_id=macchinario_id,
        capocantiere_id=capocantiere_id,
        coupe_id=coupe_id,
        scavo_da_tn=scavo_da_tn,
        quota_partenza=quota_partenza,
        quota_testa_getto=quota_testa_getto,
        data_scavo=data_scavo,
        data_getto=data_getto,
        metri_cubi_gettati=metri_cubi_gettati,
        operatore=operatore,
        descrizione=descrizione,
        ore_lavorate=ore_lavorate,
        note=note,
        tipologia_scavo=tipologia_scavo,
        materiale=materiale,
        profondita_totale=profondita_totale,
        diametro_palo_cm=diametro_palo_cm,
        larghezza_pannello=larghezza_pannello,
        altezza_pannello=altezza_pannello,
        quota_ngf_testa=quota_ngf_testa,
        quota_ngf_fondo=quota_ngf_fondo,
        quota_ngf_note=quota_ngf_note,
        courbe_beton_active=courbe_beton_active,
        courbe_beton_realisee=[{"volume": v or "", "hauteur": h or ""} for v, h in zip(courbe_realisee_volume or [], courbe_realisee_hauteur or [])] or [{"volume": "", "hauteur": ""}],
        courbe_beton_tube=[{"volume": v or "", "hauteur": h or ""} for v, h in zip(courbe_tube_volume or [], courbe_tube_hauteur or [])] or [{"volume": "", "hauteur": ""}],
        courbe_beton_volume_total=courbe_beton_volume_total,
        courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
        courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
        sonic_previsto=sonic_previsto,
        sonic_realizzato=sonic_realizzato,
        inclinometre_previsto=inclinometre_previsto,
        inclinometre_realizzato=inclinometre_realizzato,
        invalid_fields=invalid_fields,
        strato_da=strato_da,
        strato_a=strato_a,
        strato_materiale=strato_materiale,
        strato_materiale_altro=strato_materiale_altro,
    )


def _parse_optional_machine_id(macchinario_id: str | int | None) -> int | None:
    if macchinario_id in (None, ""):
        return None
    try:
        return int(macchinario_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Macchinario non valido")


def _parse_optional_user_id(user_id: str | int | None, field_label: str) -> int | None:
    if user_id in (None, ""):
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_label} non valido")


def _validate_capocantiere(db: Session, capocantiere_id: int | None) -> User | None:
    if capocantiere_id is None:
        return None
    user = db.query(User).filter(User.id == capocantiere_id, User.is_active.is_(True)).first()
    if not user or user.role not in {RoleEnum.admin, RoleEnum.manager}:
        raise HTTPException(status_code=400, detail="Capocantiere non valido")
    return user



def _parse_bool_choice(value: str | bool | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes", "oui", "si", "sì"}:
        return True
    if normalized in {"0", "false", "no", "non"}:
        return False
    return None


def _equipment_mode_from_flags(sonic: bool | None, inclino: bool | None) -> str:
    if sonic and inclino:
        return "sonic_inclinometre"
    if sonic:
        return "sonic"
    if inclino:
        return "inclinometre"
    return "aucun"


def _equipment_flags_from_mode(mode: str | None) -> tuple[bool, bool]:
    normalized = (mode or "aucun").strip().lower()
    return (normalized in {"sonic", "sonic_inclinometre"}, normalized in {"inclinometre", "sonic_inclinometre"})


def _get_site_special_equipment_config(
    db: Session,
    *,
    site_id: int,
    tipologia_scavo: str | None,
    numero_elemento: int | None,
) -> SiteSpecialEquipmentConfig | None:
    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    if not normalized_tipologia or numero_elemento is None:
        return None
    return (
        db.query(SiteSpecialEquipmentConfig)
        .filter(SiteSpecialEquipmentConfig.site_id == site_id)
        .filter(SiteSpecialEquipmentConfig.tipologia_scavo == normalized_tipologia)
        .filter(SiteSpecialEquipmentConfig.numero_elemento == numero_elemento)
        .first()
    )


def _build_site_special_equipment_rows(site: Site) -> list[dict[str, object]]:
    configs = {
        (config.tipologia_scavo, config.numero_elemento): config
        for config in (site.special_equipment_configs or [])
    }
    total_paratie = int(
        site.numero_totale_paratie
        if site.numero_totale_paratie is not None
        else (site.totale_paratie_da_scavare if site.totale_paratie_da_scavare is not None else (site.paratie_total_panels or 0))
    )
    total_pali = int(site.numero_totale_pali or 0)
    rows: list[dict[str, object]] = []
    for tipologia, total in (("paratia", total_paratie), ("palo", total_pali)):
        for numero in range(1, max(total, 0) + 1):
            config = configs.get((tipologia, numero))
            rows.append(
                {
                    "tipologia_scavo": tipologia,
                    "numero_elemento": numero,
                    "mode": _equipment_mode_from_flags(
                        bool(config.sonic_previsto) if config else False,
                        bool(config.inclinometre_previsto) if config else False,
                    ),
                }
            )
    return rows


def _serialize_site_special_equipment_configs(configs: list[SiteSpecialEquipmentConfig]) -> list[dict[str, object]]:
    return [
        {
            "site_id": config.site_id,
            "tipologia_scavo": config.tipologia_scavo,
            "numero_elemento": config.numero_elemento,
            "sonic_previsto": bool(config.sonic_previsto),
            "inclinometre_previsto": bool(config.inclinometre_previsto),
        }
        for config in configs
    ]


def _sync_site_special_equipment_from_form(
    db: Session,
    site: Site,
    *,
    equipment_tipologia: list[str] | None,
    equipment_numero: list[str] | None,
    equipment_mode: list[str] | None,
) -> None:
    existing = {
        (config.tipologia_scavo, config.numero_elemento): config
        for config in (site.special_equipment_configs or [])
    }
    row_count = max(len(equipment_tipologia or []), len(equipment_numero or []), len(equipment_mode or []), 0)

    def value(values: list[str] | None, index: int) -> str:
        return (values[index] if values and index < len(values) else "") or ""

    for index in range(row_count):
        tipologia = _normalize_fiche_tipologia(value(equipment_tipologia, index))
        if not tipologia:
            continue
        try:
            numero = int(value(equipment_numero, index))
        except (TypeError, ValueError):
            continue
        if numero <= 0:
            continue
        sonic_previsto, inclinometre_previsto = _equipment_flags_from_mode(value(equipment_mode, index))
        key = (tipologia, numero)
        config = existing.get(key)
        if not (sonic_previsto or inclinometre_previsto):
            if config:
                db.delete(config)
            continue
        if config is None:
            config = SiteSpecialEquipmentConfig(site_id=site.id, tipologia_scavo=tipologia, numero_elemento=numero)
            db.add(config)
        config.sonic_previsto = sonic_previsto
        config.inclinometre_previsto = inclinometre_previsto

    db.flush()
    current_configs = {
        (config.tipologia_scavo, config.numero_elemento): config
        for config in db.query(SiteSpecialEquipmentConfig)
        .filter(SiteSpecialEquipmentConfig.site_id == site.id)
        .all()
    }
    for fiche in site.fiches or []:
        config = current_configs.get((fiche.tipologia_scavo, fiche.numero_pannello))
        if config:
            fiche.sonic_previsto = bool(config.sonic_previsto)
            fiche.inclinometre_previsto = bool(config.inclinometre_previsto)
            if not fiche.sonic_previsto:
                fiche.sonic_realizzato = None
            if not fiche.inclinometre_previsto:
                fiche.inclinometre_realizzato = None
        else:
            fiche.sonic_previsto = False
            fiche.inclinometre_previsto = False
            fiche.sonic_realizzato = None
            fiche.inclinometre_realizzato = None

def _find_site_coupe_for_fiche(
    db: Session,
    *,
    site_id: int,
    coupe_id: str | int | None,
    tipologia_scavo: str | None,
    numero_elemento: int | None,
) -> SiteCoupe | None:
    parsed_coupe_id = _parse_optional_machine_id(coupe_id)
    if parsed_coupe_id is not None:
        coupe = (
            db.query(SiteCoupe)
            .filter(SiteCoupe.id == parsed_coupe_id, SiteCoupe.site_id == site_id)
            .first()
        )
        if not coupe:
            raise HTTPException(status_code=400, detail="Coupe di progetto non valida")
        normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
        if normalized_tipologia and numero_elemento is not None:
            is_assigned = (
                db.query(SiteCoupeAssignment.id)
                .filter(SiteCoupeAssignment.coupe_id == coupe.id)
                .filter(SiteCoupeAssignment.site_id == site_id)
                .filter(SiteCoupeAssignment.tipologia_scavo == normalized_tipologia)
                .filter(SiteCoupeAssignment.numero_elemento == numero_elemento)
                .first()
                is not None
            )
            if not is_assigned:
                raise HTTPException(
                    status_code=400,
                    detail="Ce numéro n’appartient pas à la coupe sélectionnée",
                )
        return coupe

    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    if not normalized_tipologia or numero_elemento is None:
        return None

    assignment = (
        db.query(SiteCoupeAssignment)
        .join(SiteCoupe, SiteCoupe.id == SiteCoupeAssignment.coupe_id)
        .filter(SiteCoupeAssignment.site_id == site_id)
        .filter(SiteCoupeAssignment.tipologia_scavo == normalized_tipologia)
        .filter(SiteCoupeAssignment.numero_elemento == numero_elemento)
        .first()
    )
    return assignment.coupe if assignment else None


def _apply_coupe_defaults_to_fiche_values(
    coupe: SiteCoupe | None,
    *,
    scavo_da_tn: bool | str | None,
    quota_tn_value: float | None,
    quota_testa_getto_value: float | None,
    quota_ngf_testa_value: float | None,
    quota_ngf_fondo_value: float | None,
    profondita_value: float | None,
    diametro_value_cm: float | None,
    larghezza_value: float | None,
    altezza_value: float | None,
) -> dict[str, float | bool | None]:
    scavo_da_tn_value = scavo_da_tn in (True, "1", "true", "on", "si", "SI")
    quota_partenza_value = None
    if coupe:
        scavo_da_tn_value = coupe.scavo_da_tn if scavo_da_tn is None else scavo_da_tn_value
        quota_tn_value = quota_tn_value if quota_tn_value is not None else coupe.quota_tn
        if scavo_da_tn_value:
            quota_partenza_value = coupe.quota_tn
        else:
            quota_partenza_value = coupe.quota_partenza_scavo if coupe.quota_partenza_scavo is not None else coupe.quota_testa
        quota_testa_getto_value = quota_testa_getto_value if quota_testa_getto_value is not None else coupe.quota_testa_getto_prevista
        quota_ngf_testa_value = quota_ngf_testa_value if quota_ngf_testa_value is not None else coupe.quota_testa
        profondita_value = profondita_value if profondita_value is not None else coupe.profondita_teorica
        larghezza_value = larghezza_value if larghezza_value is not None else coupe.larghezza
        diametro_value_cm = diametro_value_cm if diametro_value_cm is not None else (coupe.diametro * 100 if coupe.diametro is not None else None)
        altezza_value = altezza_value if altezza_value is not None else coupe.spessore

    _validate_quota_testa_getto_not_above_tn(
        quota_testa_getto_value,
        quota_tn=coupe.quota_tn if coupe and coupe.quota_tn is not None else quota_ngf_testa_value,
    )
    if quota_ngf_fondo_value is None and quota_ngf_testa_value is not None and profondita_value is not None:
        quota_ngf_fondo_value = quota_ngf_testa_value - profondita_value

    return {
        "scavo_da_tn_value": scavo_da_tn_value,
        "quota_tn_value": quota_tn_value,
        "quota_partenza_value": quota_partenza_value,
        "quota_testa_getto_value": quota_testa_getto_value,
        "quota_ngf_testa_value": quota_ngf_testa_value,
        "quota_ngf_fondo_value": quota_ngf_fondo_value,
        "profondita_value": profondita_value,
        "diametro_value_cm": diametro_value_cm,
        "larghezza_value": larghezza_value,
        "altezza_value": altezza_value,
    }


def _validate_required_fiche_stratigrafia(
    profondita_totale: float | None,
    strato_da: list[float | None] | None,
    strato_a: list[float | None] | None,
    strato_materiale: list[str] | None = None,
) -> list[tuple[float, float, str]]:
    if profondita_totale is None:
        raise HTTPException(
            status_code=400,
            detail="Il campo profondità totale scavata è obbligatorio.",
        )

    strato_da = strato_da or []
    strato_a = strato_a or []
    strato_materiale = strato_materiale or []
    max_len = max(len(strato_da), len(strato_a), len(strato_materiale), 0)
    has_any_stratigrafia_value = False

    for index in range(max_len):
        da_val = strato_da[index] if index < len(strato_da) else None
        a_val = strato_a[index] if index < len(strato_a) else None
        material = strato_materiale[index] if index < len(strato_materiale) else ""
        if da_val is not None or a_val is not None or (material or "").strip():
            has_any_stratigrafia_value = True
        if (da_val is None) != (a_val is None):
            raise HTTPException(
                status_code=400,
                detail="Ogni strato di stratigrafia deve avere Da (m) e A (m).",
            )

    layers = _get_complete_stratigrafia_layers(
        strato_da=strato_da,
        strato_a=strato_a,
        strato_materiale=strato_materiale,
    )
    if not layers or not has_any_stratigrafia_value:
        raise HTTPException(
            status_code=400,
            detail="Inserire almeno uno strato di stratigrafia.",
        )

    _validate_fiche_stratigrafia(
        profondita_totale=profondita_totale,
        strato_da=[layer[0] for layer in layers],
        strato_a=[layer[1] for layer in layers],
    )
    return layers


def _create_validated_fiche(
    db: Session,
    *,
    current_user: User,
    cantiere_id: int,
    numero_pannello: str | int | None,
    macchinario_id: str | int | None,
    capocantiere_id: str | int | None = None,
    data_scavo: date = None,
    data_getto: date | None,
    metri_cubi_gettati: str | float | None,
    operatore: str,
    descrizione: str | None,
    ore_lavorate: str | float | None,
    note: str | None,
    tipologia_scavo: str | None,
    materiale: str | None,
    profondita_totale: str | float | None,
    diametro_palo_cm: str | float | None,
    larghezza_pannello: str | float | None,
    altezza_pannello: str | float | None,
    quota_ngf_testa: str | float | None = None,
    quota_ngf_fondo: str | float | None = None,
    quota_ngf_note: str | None = None,
    coupe_id: str | int | None = None,
    scavo_da_tn: bool | str | None = True,
    quota_testa_getto: str | float | None = None,
    sonic_realizzato: str | bool | None = None,
    inclinometre_realizzato: str | bool | None = None,
    strato_da: list[str | float | None] | None = None,
    strato_a: list[str | float | None] | None = None,
    strato_materiale: list[str] | None = None,
    strato_materiale_altro: list[str] | None = None,
    courbe_beton_active: str | bool | None = False,
    courbe_realisee_volume: list[str | float | None] | None = None,
    courbe_realisee_hauteur: list[str | float | None] | None = None,
    courbe_tube_volume: list[str | float | None] | None = None,
    courbe_tube_hauteur: list[str | float | None] | None = None,
    courbe_beton_volume_total: str | float | None = None,
    courbe_beton_hauteur_initiale: str | float | None = None,
    courbe_beton_hauteur_finale: str | float | None = None,
    restrict_to_capo_sites: bool = False,
) -> Fiche:
    metri_cubi_value = _parse_decimal_comma_float(
        metri_cubi_gettati, "Metri cubi gettati"
    )
    profondita_value = _parse_decimal_comma_float(
        profondita_totale, "profondità totale"
    )
    diametro_value_cm = _parse_decimal_comma_float(diametro_palo_cm, "diametro palo")
    larghezza_value = _parse_decimal_comma_float(
        larghezza_pannello, "larghezza pannello"
    )
    altezza_value = _parse_decimal_comma_float(altezza_pannello, "altezza pannello")
    quota_ngf_testa_value = _parse_decimal_comma_float(quota_ngf_testa, "quota NGF testa")
    quota_ngf_fondo_value = _parse_decimal_comma_float(quota_ngf_fondo, "quota NGF fondo")
    parsed_strato_da = _parse_decimal_comma_float_list(strato_da, "Da (m)")
    parsed_strato_a = _parse_decimal_comma_float_list(strato_a, "A (m)")
    normalized_strato_materiale = _normalize_stratigrafia_materials(strato_materiale, strato_materiale_altro)
    parsed_machine_id = _parse_optional_machine_id(macchinario_id)
    parsed_capocantiere_id = _parse_optional_user_id(capocantiere_id, "Capocantiere")
    parsed_numero_pannello = _parse_required_positive_int(
        numero_pannello,
        "Inserire numero paratia / palo",
        "Il numero paratia / palo deve essere maggiore di 0",
    )
    ore_scavate = _parse_optional_non_negative_float(ore_lavorate, "Ore scavate")

    if not (operatore or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Il campo Operatore / squadra è obbligatorio.",
        )

    _validate_metri_cubi_gettati(metri_cubi_value)

    site = db.query(Site).filter(Site.id == cantiere_id).first()
    if not site:
        raise HTTPException(status_code=400, detail="Cantiere non trovato")
    if restrict_to_capo_sites:
        allowed_site_ids = {s.id for s in _get_capo_assigned_sites(db, current_user)}
        if allowed_site_ids and site.id not in allowed_site_ids:
            raise HTTPException(status_code=403, detail="Cantiere non valido")

    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    if normalized_tipologia == "palo":
        larghezza_value = None
        altezza_value = None
    elif normalized_tipologia == "paratia":
        diametro_value_cm = None

    coupe = _find_site_coupe_for_fiche(
        db,
        site_id=site.id,
        coupe_id=coupe_id,
        tipologia_scavo=normalized_tipologia,
        numero_elemento=parsed_numero_pannello,
    )
    coupe_values = _apply_coupe_defaults_to_fiche_values(
        coupe,
        scavo_da_tn=scavo_da_tn,
        quota_tn_value=None,
        quota_testa_getto_value=_parse_decimal_comma_float(quota_testa_getto, "quota testa getto"),
        quota_ngf_testa_value=quota_ngf_testa_value,
        quota_ngf_fondo_value=quota_ngf_fondo_value,
        profondita_value=profondita_value,
        diametro_value_cm=diametro_value_cm,
        larghezza_value=larghezza_value,
        altezza_value=altezza_value,
    )
    scavo_da_tn_value = bool(coupe_values["scavo_da_tn_value"])
    quota_tn_value = coupe_values["quota_tn_value"]
    quota_partenza_value = coupe_values["quota_partenza_value"]
    quota_testa_getto_value = coupe_values["quota_testa_getto_value"]
    quota_ngf_testa_value = coupe_values["quota_ngf_testa_value"]
    quota_ngf_fondo_value = coupe_values["quota_ngf_fondo_value"]
    profondita_value = coupe_values["profondita_value"]
    diametro_value_cm = coupe_values["diametro_value_cm"]
    larghezza_value = coupe_values["larghezza_value"]
    altezza_value = coupe_values["altezza_value"]
    if normalized_tipologia == "palo":
        larghezza_value = None
        altezza_value = None
    elif normalized_tipologia == "paratia":
        diametro_value_cm = None
    if quota_ngf_testa_value is not None and profondita_value is not None and quota_ngf_fondo_value is None:
        quota_ngf_fondo_value = quota_ngf_testa_value - profondita_value

    _validate_fiche_geometria(
        tipologia_scavo=normalized_tipologia,
        diametro_palo_cm=diametro_value_cm,
        larghezza_pannello=larghezza_value,
        altezza_pannello=altezza_value,
        profondita_totale=profondita_value,
    )
    layers = _validate_required_fiche_stratigrafia(
        profondita_totale=profondita_value,
        strato_da=parsed_strato_da,
        strato_a=parsed_strato_a,
        strato_materiale=normalized_strato_materiale,
    )

    _ensure_unique_numero_pannello(
        db, cantiere_id, normalized_tipologia, parsed_numero_pannello
    )

    equipment_config = _get_site_special_equipment_config(
        db,
        site_id=site.id,
        tipologia_scavo=normalized_tipologia,
        numero_elemento=parsed_numero_pannello,
    )
    sonic_previsto = bool(equipment_config.sonic_previsto) if equipment_config else False
    inclinometre_previsto = bool(equipment_config.inclinometre_previsto) if equipment_config else False
    sonic_realizzato_value = _parse_bool_choice(sonic_realizzato)
    inclinometre_realizzato_value = _parse_bool_choice(inclinometre_realizzato)
    if sonic_previsto and sonic_realizzato_value is None:
        raise HTTPException(status_code=400, detail="Sonic réalisé ? è obbligatorio.")
    if inclinometre_previsto and inclinometre_realizzato_value is None:
        raise HTTPException(status_code=400, detail="Inclinomètre réalisé ? è obbligatorio.")
    if not sonic_previsto:
        sonic_realizzato_value = None
    if not inclinometre_previsto:
        inclinometre_realizzato_value = None

    if parsed_machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == parsed_machine_id).first()
        if not machine:
            raise HTTPException(status_code=400, detail="Macchinario non trovato")
    _validate_capocantiere(db, parsed_capocantiere_id)

    diametro_value_m = diametro_value_cm / 100 if diametro_value_cm is not None else None
    fiche = Fiche(
        date=data_scavo,
        numero_pannello=parsed_numero_pannello,
        site_id=cantiere_id,
        coupe_id=coupe.id if coupe else None,
        machine_id=parsed_machine_id,
        capocantiere_id=parsed_capocantiere_id,
        fiche_type=FicheTypeEnum.produzione,
        description=descrizione or "",
        operator=operatore.strip(),
        hours=ore_scavate,
        notes=note or None,
        tipologia_scavo=normalized_tipologia,
        materiale=(materiale or (coupe.type_beton if coupe else None) or None),
        profondita_totale=profondita_value,
        diametro_palo=diametro_value_m,
        larghezza_pannello=larghezza_value,
        altezza_pannello=altezza_value,
        data_getto=data_getto,
        metri_cubi_gettati=metri_cubi_value,
        quota_ngf_testa=quota_ngf_testa_value,
        quota_ngf_note=(quota_ngf_note or "").strip() or None,
        quota_tn=quota_tn_value,
        responsable_pdf=None,
        type_beton=(coupe.type_beton if coupe and coupe.type_beton else (materiale or None)),
        type_coulage=(coupe.type_coulage if coupe and coupe.type_coulage else "Gravitaire"),
        terreno_teorico=(coupe.terreno_teorico if coupe and coupe.terreno_teorico else None),
        scavo_da_tn=scavo_da_tn_value,
        quota_partenza=quota_partenza_value,
        quota_testa_getto=quota_testa_getto_value,
        quota_ngf_fondo=quota_ngf_fondo_value,
        sonic_previsto=sonic_previsto,
        sonic_realizzato=sonic_realizzato_value,
        inclinometre_previsto=inclinometre_previsto,
        inclinometre_realizzato=inclinometre_realizzato_value,
        created_by_id=current_user.id,
    )
    if current_user.role in {RoleEnum.admin, RoleEnum.manager}:
        _apply_courbe_beton_fields(
            fiche,
            courbe_beton_active=courbe_beton_active,
            courbe_realisee_volume=courbe_realisee_volume,
            courbe_realisee_hauteur=courbe_realisee_hauteur,
            courbe_tube_volume=courbe_tube_volume,
            courbe_tube_hauteur=courbe_tube_hauteur,
            courbe_beton_volume_total=courbe_beton_volume_total,
            courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
            courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
        )

    db.add(fiche)
    db.flush()

    for da_val, a_val, mat in layers:
        db.add(
            FicheStratigrafia(
                fiche_id=fiche.id,
                da_profondita=da_val,
                a_profondita=a_val,
                materiale=mat,
            )
        )

    _sync_site_fiche_progress(db, site)
    fiche_notifications = notify_new_fiche(db, fiche, current_user)
    logger.info(
        "notification created for fiche id %s: %s recipient(s)",
        fiche.id,
        len(fiche_notifications),
    )
    db.commit()
    db.refresh(fiche)
    return fiche


def _update_validated_fiche(
    db: Session,
    *,
    fiche: Fiche,
    current_user: User,
    cantiere_id: int,
    numero_pannello: str | int | None,
    macchinario_id: str | int | None,
    capocantiere_id: str | int | None = None,
    data_scavo: date = None,
    data_getto: date | None,
    metri_cubi_gettati: str | float | None,
    operatore: str,
    descrizione: str | None,
    ore_lavorate: str | float | None,
    note: str | None,
    tipologia_scavo: str | None,
    materiale: str | None,
    profondita_totale: str | float | None,
    diametro_palo_cm: str | float | None,
    larghezza_pannello: str | float | None,
    altezza_pannello: str | float | None,
    quota_ngf_testa: str | float | None,
    quota_ngf_fondo: str | float | None,
    quota_ngf_note: str | None,
    coupe_id: str | int | None = None,
    scavo_da_tn: bool | str | None = True,
    quota_testa_getto: str | float | None = None,
    sonic_realizzato: str | bool | None = None,
    inclinometre_realizzato: str | bool | None = None,
    strato_da: list[str | float | None] | None = None,
    strato_a: list[str | float | None] | None = None,
    strato_materiale: list[str] | None = None,
    strato_materiale_altro: list[str] | None = None,
    courbe_beton_active: str | bool | None = False,
    courbe_realisee_volume: list[str | float | None] | None = None,
    courbe_realisee_hauteur: list[str | float | None] | None = None,
    courbe_tube_volume: list[str | float | None] | None = None,
    courbe_tube_hauteur: list[str | float | None] | None = None,
    courbe_beton_volume_total: str | float | None = None,
    courbe_beton_hauteur_initiale: str | float | None = None,
    courbe_beton_hauteur_finale: str | float | None = None,
) -> Fiche:
    metri_cubi_value = _parse_decimal_comma_float(
        metri_cubi_gettati, "Metri cubi gettati"
    )
    profondita_value = _parse_decimal_comma_float(
        profondita_totale, "profondità totale"
    )
    diametro_value_cm = _parse_decimal_comma_float(diametro_palo_cm, "diametro palo")
    larghezza_value = _parse_decimal_comma_float(
        larghezza_pannello, "larghezza pannello"
    )
    altezza_value = _parse_decimal_comma_float(altezza_pannello, "altezza pannello")
    quota_ngf_testa_value = _parse_decimal_comma_float(quota_ngf_testa, "quota NGF testa")
    quota_ngf_fondo_value = _parse_decimal_comma_float(quota_ngf_fondo, "quota NGF fondo")
    parsed_strato_da = _parse_decimal_comma_float_list(strato_da, "Da (m)")
    parsed_strato_a = _parse_decimal_comma_float_list(strato_a, "A (m)")
    normalized_strato_materiale = _normalize_stratigrafia_materials(strato_materiale, strato_materiale_altro)
    parsed_machine_id = _parse_optional_machine_id(macchinario_id)
    parsed_capocantiere_id = _parse_optional_user_id(capocantiere_id, "Capocantiere")
    parsed_numero_pannello = _parse_required_positive_int(
        numero_pannello,
        "Inserire numero paratia / palo",
        "Il numero paratia / palo deve essere maggiore di 0",
    )
    ore_scavate = _parse_optional_non_negative_float(ore_lavorate, "Ore scavate")

    if not (operatore or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Il campo Operatore / squadra è obbligatorio.",
        )

    _validate_metri_cubi_gettati(metri_cubi_value)

    site = db.query(Site).filter(Site.id == cantiere_id).first()
    if not site:
        raise HTTPException(status_code=400, detail="Cantiere non trovato")

    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    _ensure_unique_numero_pannello(
        db,
        cantiere_id,
        normalized_tipologia,
        parsed_numero_pannello,
        exclude_fiche_id=fiche.id,
    )

    coupe = _find_site_coupe_for_fiche(
        db,
        site_id=site.id,
        coupe_id=coupe_id,
        tipologia_scavo=normalized_tipologia,
        numero_elemento=parsed_numero_pannello,
    )
    coupe_values = _apply_coupe_defaults_to_fiche_values(
        coupe,
        scavo_da_tn=scavo_da_tn,
        quota_tn_value=fiche.quota_tn,
        quota_testa_getto_value=_parse_decimal_comma_float(quota_testa_getto, "quota testa getto"),
        quota_ngf_testa_value=quota_ngf_testa_value,
        quota_ngf_fondo_value=quota_ngf_fondo_value,
        profondita_value=profondita_value,
        diametro_value_cm=diametro_value_cm,
        larghezza_value=larghezza_value,
        altezza_value=altezza_value,
    )
    scavo_da_tn_value = bool(coupe_values["scavo_da_tn_value"])
    quota_tn_value = coupe_values["quota_tn_value"]
    quota_partenza_value = coupe_values["quota_partenza_value"]
    quota_testa_getto_value = coupe_values["quota_testa_getto_value"]
    quota_ngf_testa_value = coupe_values["quota_ngf_testa_value"]
    quota_ngf_fondo_value = coupe_values["quota_ngf_fondo_value"]
    profondita_value = coupe_values["profondita_value"]
    diametro_value_cm = coupe_values["diametro_value_cm"]
    larghezza_value = coupe_values["larghezza_value"]
    altezza_value = coupe_values["altezza_value"]
    if normalized_tipologia == "palo":
        larghezza_value = None
        altezza_value = None
    elif normalized_tipologia == "paratia":
        diametro_value_cm = None
    if quota_ngf_testa_value is not None and profondita_value is not None and quota_ngf_fondo_value is None:
        quota_ngf_fondo_value = quota_ngf_testa_value - profondita_value

    _validate_fiche_geometria(
        tipologia_scavo=normalized_tipologia,
        diametro_palo_cm=diametro_value_cm,
        larghezza_pannello=larghezza_value,
        altezza_pannello=altezza_value,
        profondita_totale=profondita_value,
    )
    layers = _validate_required_fiche_stratigrafia(
        profondita_totale=profondita_value,
        strato_da=parsed_strato_da,
        strato_a=parsed_strato_a,
        strato_materiale=normalized_strato_materiale,
    )

    equipment_config = _get_site_special_equipment_config(
        db,
        site_id=site.id,
        tipologia_scavo=normalized_tipologia,
        numero_elemento=parsed_numero_pannello,
    )
    sonic_previsto = bool(equipment_config.sonic_previsto) if equipment_config else False
    inclinometre_previsto = bool(equipment_config.inclinometre_previsto) if equipment_config else False
    sonic_realizzato_value = _parse_bool_choice(sonic_realizzato)
    inclinometre_realizzato_value = _parse_bool_choice(inclinometre_realizzato)
    if sonic_previsto and sonic_realizzato_value is None:
        raise HTTPException(status_code=400, detail="Sonic réalisé ? è obbligatorio.")
    if inclinometre_previsto and inclinometre_realizzato_value is None:
        raise HTTPException(status_code=400, detail="Inclinomètre réalisé ? è obbligatorio.")
    if not sonic_previsto:
        sonic_realizzato_value = None
    if not inclinometre_previsto:
        inclinometre_realizzato_value = None

    if parsed_machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == parsed_machine_id).first()
        if not machine:
            raise HTTPException(status_code=400, detail="Macchinario non trovato")
    _validate_capocantiere(db, parsed_capocantiere_id)

    previous_site_id = fiche.site_id
    diametro_value_m = diametro_value_cm / 100 if diametro_value_cm is not None else None
    fiche.date = data_scavo
    fiche.numero_pannello = parsed_numero_pannello
    fiche.site_id = cantiere_id
    fiche.coupe_id = coupe.id if coupe else None
    fiche.machine_id = parsed_machine_id
    fiche.capocantiere_id = parsed_capocantiere_id
    fiche.fiche_type = FicheTypeEnum.produzione
    fiche.description = descrizione or ""
    fiche.operator = operatore.strip()
    fiche.hours = ore_scavate
    fiche.notes = note or None
    fiche.tipologia_scavo = normalized_tipologia
    fiche.materiale = materiale or (coupe.type_beton if coupe else None) or None
    fiche.profondita_totale = profondita_value
    fiche.diametro_palo = diametro_value_m
    fiche.larghezza_pannello = larghezza_value
    fiche.altezza_pannello = altezza_value
    fiche.data_getto = data_getto
    fiche.metri_cubi_gettati = metri_cubi_value
    fiche.quota_ngf_testa = quota_ngf_testa_value
    fiche.quota_ngf_fondo = quota_ngf_fondo_value
    fiche.quota_ngf_note = (quota_ngf_note or "").strip() or None
    fiche.quota_tn = quota_tn_value
    if coupe:
        fiche.type_beton = coupe.type_beton or fiche.materiale
        fiche.type_coulage = coupe.type_coulage or "Gravitaire"
        fiche.terreno_teorico = coupe.terreno_teorico
    elif not fiche.type_coulage:
        fiche.type_coulage = "Gravitaire"
    fiche.scavo_da_tn = scavo_da_tn_value
    fiche.quota_partenza = quota_partenza_value
    fiche.quota_testa_getto = quota_testa_getto_value
    fiche.sonic_previsto = sonic_previsto
    fiche.sonic_realizzato = sonic_realizzato_value
    fiche.inclinometre_previsto = inclinometre_previsto
    fiche.inclinometre_realizzato = inclinometre_realizzato_value
    if current_user.role in {RoleEnum.admin, RoleEnum.manager}:
        _apply_courbe_beton_fields(
            fiche,
            courbe_beton_active=courbe_beton_active,
            courbe_realisee_volume=courbe_realisee_volume,
            courbe_realisee_hauteur=courbe_realisee_hauteur,
            courbe_tube_volume=courbe_tube_volume,
            courbe_tube_hauteur=courbe_tube_hauteur,
            courbe_beton_volume_total=courbe_beton_volume_total,
            courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
            courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
        )

    db.query(FicheStratigrafia).filter(FicheStratigrafia.fiche_id == fiche.id).delete()
    db.flush()
    for da_val, a_val, mat in layers:
        db.add(
            FicheStratigrafia(
                fiche_id=fiche.id,
                da_profondita=da_val,
                a_profondita=a_val,
                materiale=mat,
            )
        )

    _sync_site_fiche_progress(db, site)
    if previous_site_id != site.id:
        previous_site = db.query(Site).filter(Site.id == previous_site_id).first()
        if previous_site:
            _sync_site_fiche_progress(db, previous_site)
    db.commit()
    db.refresh(fiche)
    return fiche


def _calculate_fiche_volume_teorico(fiche: Fiche) -> float | None:
    if fiche.profondita_totale is None:
        return None
    tipologia = (fiche.tipologia_scavo or "").strip().lower()
    if tipologia == "paratia":
        if fiche.larghezza_pannello is None or fiche.altezza_pannello is None:
            return None
        return fiche.larghezza_pannello * fiche.altezza_pannello * fiche.profondita_totale
    if tipologia == "palo":
        if fiche.diametro_palo is None:
            return None
        radius = fiche.diametro_palo / 2
        return pi * (radius ** 2) * fiche.profondita_totale
    return None


def _build_fiche_form_data_from_model(fiche: Fiche) -> dict:
    stratigrafie = sorted(fiche.stratigrafie or [], key=lambda layer: layer.da_profondita)
    return _build_fiche_form_data(
        cantiere_id=fiche.site_id,
        numero_pannello=fiche.numero_pannello,
        macchinario_id=fiche.machine_id,
        capocantiere_id=fiche.capocantiere_id,
        coupe_id=fiche.coupe_id,
        scavo_da_tn=fiche.scavo_da_tn,
        quota_partenza=fiche.quota_partenza,
        quota_testa_getto=fiche.quota_testa_getto,
        data_scavo=fiche.date,
        data_getto=fiche.data_getto,
        metri_cubi_gettati=fiche.metri_cubi_gettati,
        operatore=fiche.operator,
        descrizione=fiche.description,
        ore_lavorate=fiche.hours,
        note=fiche.notes,
        tipologia_scavo=fiche.tipologia_scavo,
        stratigrafia=fiche.stratigrafia,
        materiale=fiche.materiale,
        profondita_totale=fiche.profondita_totale,
        diametro_palo=fiche.diametro_palo,
        larghezza_pannello=fiche.larghezza_pannello,
        altezza_pannello=fiche.altezza_pannello,
        quota_ngf_testa=fiche.quota_ngf_testa,
        quota_ngf_fondo=fiche.quota_ngf_fondo,
        quota_ngf_note=fiche.quota_ngf_note,
        courbe_beton_active=fiche.courbe_beton_active,
        courbe_beton_realisee=_deserialize_courbe_points(fiche.courbe_beton_realisee),
        courbe_beton_tube=_deserialize_courbe_points(fiche.courbe_beton_tube),
        courbe_beton_volume_total=fiche.courbe_beton_volume_total,
        courbe_beton_hauteur_initiale=fiche.courbe_beton_hauteur_initiale,
        courbe_beton_hauteur_finale=fiche.courbe_beton_hauteur_finale,
        sonic_previsto=fiche.sonic_previsto,
        sonic_realizzato=fiche.sonic_realizzato,
        inclinometre_previsto=fiche.inclinometre_previsto,
        inclinometre_realizzato=fiche.inclinometre_realizzato,
        strato_da=[layer.da_profondita for layer in stratigrafie],
        strato_a=[layer.a_profondita for layer in stratigrafie],
        strato_materiale=[layer.materiale for layer in stratigrafie],
    )


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
            .filter(func.lower(func.trim(Depot.name)).notin_(["montauroux", "st. jeannet", "st jeannet", "sommariva", "cantieri"]))
            .order_by(Depot.name.asc())
            .all()
        )
        depots_map_data = _build_depots_map_data(
            depots_with_coords,
            detail_url_template=str(
                request.url_for("manager_depositi_detail", depot_id="__DEPOT_ID__")
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
                joinedload(Report.workers).load_only(
                    ReportWorker.id,
                    ReportWorker.report_id,
                    ReportWorker.hours_worked,
                ),
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
        reports_for_hours = (
            db.query(Report)
            .options(
                joinedload(Report.site).load_only(Site.id, Site.name),
                joinedload(Report.workers).load_only(
                    ReportWorker.id,
                    ReportWorker.report_id,
                    ReportWorker.hours_worked,
                ),
            )
            .filter(Report.date >= start_date)
            .all()
        )
        hours_by_site: dict[str, float] = {}
        for report in reports_for_hours:
            site_name = (
                report.site.name if report.site else report.site_name_or_code
            ) or "Senza nome"
            hours_by_site[site_name] = hours_by_site.get(
                site_name, 0.0
            ) + report_total_hours(report)
        hours_per_site_30_days = [
            {"site_name": site_name, "hours": hours}
            for site_name, hours in sorted(
                hours_by_site.items(), key=lambda item: item[1], reverse=True
            )
        ]
        perf_logger.debug(
            "manager_dashboard hours_per_site rows=%s duration_ms=%.2f",
            len(hours_per_site_30_days),
            (time.monotonic() - query_started) * 1000,
        )

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

    return _render_fiche_create_form(
        request,
        current_user,
        template_name="capo/fiches_form.html",
        collections_loader=_load_manager_form_collections,
        extra_context={
            "is_edit": False,
            "fiche_form_area_label": {
                "fr": "Gestion des fiches",
                "it": "Gestione fiches",
            },
            "fiche_form_subtitle": {
                "fr": "Renseignez les informations pour enregistrer une nouvelle fiche avec le modèle unique.",
                "it": "Compila le informazioni per registrare una nuova fiche con il modello unico.",
            },
            "fiche_cancel_url": "/manager/fiches",
            "show_ngf_fields": True,
            "show_project_coupe_fields": True,
            "show_capocantiere_field": True,
            "show_courbe_beton_fields": False,
        },
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
    numero_pannello: str | None = Form(None),
    macchinario_id: str | None = Form(None),
    capocantiere_id: str | None = Form(None),
    coupe_id: str | None = Form(None),
    scavo_da_tn: str | None = Form("1"),
    quota_testa_getto: str | None = Form(None),
    sonic_realizzato: str | None = Form(None),
    inclinometre_realizzato: str | None = Form(None),
    data_scavo: date = Form(...),
    data_getto: date | None = Form(None),
    metri_cubi_gettati: str | None = Form(None),
    operatore: str = Form(...),
    descrizione: str = Form(""),
    ore_lavorate: str | None = Form(None),
    note: str | None = Form(None),
    tipologia_scavo: str | None = Form(None),
    materiale: str | None = Form(None),
    profondita_totale: str | None = Form(None),
    diametro_palo_cm: str | None = Form(None),
    larghezza_pannello: str | None = Form(None),
    altezza_pannello: str | None = Form(None),
    quota_ngf_testa: str | None = Form(None),
    quota_ngf_fondo: str | None = Form(None),
    quota_ngf_note: str | None = Form(None),
    strato_da: List[str] = Form(default_factory=list),
    strato_a: List[str] = Form(default_factory=list),
    strato_materiale: List[str] = Form(default_factory=list),
    strato_materiale_altro: List[str] = Form(default_factory=list),
    courbe_beton_active: str | None = Form(None),
    courbe_realisee_volume: List[str] = Form(default_factory=list),
    courbe_realisee_hauteur: List[str] = Form(default_factory=list),
    courbe_tube_volume: List[str] = Form(default_factory=list),
    courbe_tube_hauteur: List[str] = Form(default_factory=list),
    courbe_beton_volume_total: str | None = Form(None),
    courbe_beton_hauteur_initiale: str | None = Form(None),
    courbe_beton_hauteur_finale: str | None = Form(None),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    try:
        db = SessionLocal()
        try:
            _create_validated_fiche(
                db,
                current_user=current_user,
                cantiere_id=cantiere_id,
                numero_pannello=numero_pannello,
                macchinario_id=macchinario_id,
                capocantiere_id=capocantiere_id,
                coupe_id=coupe_id,
                scavo_da_tn=scavo_da_tn,
                quota_testa_getto=quota_testa_getto,
                data_scavo=data_scavo,
                data_getto=data_getto,
                metri_cubi_gettati=metri_cubi_gettati,
                operatore=operatore,
                descrizione=descrizione,
                ore_lavorate=ore_lavorate,
                note=note,
                tipologia_scavo=tipologia_scavo,
                materiale=materiale,
                profondita_totale=profondita_totale,
                diametro_palo_cm=diametro_palo_cm,
                larghezza_pannello=larghezza_pannello,
                altezza_pannello=altezza_pannello,
                quota_ngf_testa=quota_ngf_testa,
                quota_ngf_fondo=quota_ngf_fondo,
                quota_ngf_note=quota_ngf_note,
                sonic_realizzato=sonic_realizzato,
                inclinometre_realizzato=inclinometre_realizzato,
                strato_da=strato_da,
                strato_a=strato_a,
                strato_materiale=strato_materiale,
                strato_materiale_altro=strato_materiale_altro,
                courbe_beton_active=courbe_beton_active,
                courbe_realisee_volume=courbe_realisee_volume,
                courbe_realisee_hauteur=courbe_realisee_hauteur,
                courbe_tube_volume=courbe_tube_volume,
                courbe_tube_hauteur=courbe_tube_hauteur,
                courbe_beton_volume_total=courbe_beton_volume_total,
                courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
                courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
            )
        finally:
            db.close()
    except HTTPException as exc:
        form_data = _build_fiche_error_form_data(
            cantiere_id=cantiere_id,
            numero_pannello=numero_pannello,
            macchinario_id=macchinario_id,
            capocantiere_id=capocantiere_id,
            coupe_id=coupe_id,
            scavo_da_tn=scavo_da_tn,
            quota_testa_getto=quota_testa_getto,
            sonic_realizzato=sonic_realizzato,
            inclinometre_realizzato=inclinometre_realizzato,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo_cm=diametro_palo_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            quota_ngf_testa=quota_ngf_testa,
            quota_ngf_fondo=quota_ngf_fondo,
            quota_ngf_note=quota_ngf_note,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
            strato_materiale_altro=strato_materiale_altro,
            courbe_beton_active=courbe_beton_active,
            courbe_realisee_volume=courbe_realisee_volume,
            courbe_realisee_hauteur=courbe_realisee_hauteur,
            courbe_tube_volume=courbe_tube_volume,
            courbe_tube_hauteur=courbe_tube_hauteur,
            courbe_beton_volume_total=courbe_beton_volume_total,
            courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
            courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
            invalid_fields=_invalid_fields_for_fiche_error(exc.detail),
        )
        return _render_fiche_create_form(
            request,
            current_user,
            template_name="capo/fiches_form.html",
            collections_loader=_load_manager_form_collections,
            status_code=exc.status_code or 400,
            form_data=form_data,
            error_message=exc.detail,
            extra_context={
                "is_edit": False,
                "fiche_form_area_label": {
                    "fr": "Gestion des fiches",
                    "it": "Gestione fiches",
                },
                "fiche_form_subtitle": {
                    "fr": "Renseignez les informations pour enregistrer une nouvelle fiche avec le modèle unique.",
                    "it": "Compila le informazioni per registrare una nuova fiche con il modello unico.",
                },
                "fiche_cancel_url": "/manager/fiches",
                "show_ngf_fields": True,
                "show_project_coupe_fields": True,
                "show_capocantiere_field": True,
                "show_courbe_beton_fields": False,
            },
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
            form_create_personale_profile=None,
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
    create_personale_profile = (form.get("create_personale_profile") or "").strip().lower() in {"1", "true", "on", "yes"}

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
                form_create_personale_profile=create_personale_profile,
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
        personale_profile = ensure_user_personale_profile(
            db,
            new_user,
            roles=parsed_roles,
            create_personale_profile=create_personale_profile,
        )
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
                "personale_id": personale_profile.id if personale_profile else None,
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
        has_personale_profile = (
            db.query(Personale)
            .filter(Personale.user_id == user_to_edit.id)
            .first()
            is not None
        )
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
            form_create_personale_profile=has_personale_profile,
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
    create_personale_profile = (form.get("create_personale_profile") or "").strip().lower() in {"1", "true", "on", "yes"}
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
                form_create_personale_profile=create_personale_profile,
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
        personale_profile = ensure_user_personale_profile(
            db,
            user_to_edit,
            roles=parsed_roles,
            create_personale_profile=create_personale_profile,
        )

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
                "personale_id": personale_profile.id if personale_profile else None,
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
                joinedload(Site.coupes).joinedload(SiteCoupe.assignments),
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
        site_project_configured_map = {
            site.id: _site_project_configuration_complete(site) for site in sites_list
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
            site_project_configured_map=site_project_configured_map,
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


def _parse_optional_non_negative_float(
    value: str | int | float | None, field_label: str
) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed_value = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Il campo {field_label} non è valido.",
        )
    if parsed_value < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Il campo {field_label} non può essere negativo.",
        )
    return parsed_value


def _parse_optional_non_negative_int(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Il totale paratie da scavare non è valido.",
        )
    if parsed_value < 0:
        raise HTTPException(
            status_code=400,
            detail="Il totale paratie da scavare non può essere negativo.",
        )
    return parsed_value


def _parse_required_positive_int(
    value: str | int | None,
    empty_message: str,
    invalid_message: str,
) -> int:
    if value in (None, ""):
        raise HTTPException(status_code=400, detail=empty_message)
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=invalid_message)
    if parsed_value <= 0:
        raise HTTPException(status_code=400, detail=invalid_message)
    return parsed_value


def _normalize_fiche_tipologia(tipologia_scavo: str | None) -> str:
    tipologia = (tipologia_scavo or "").strip().lower()
    if tipologia not in {"paratia", "palo"}:
        raise HTTPException(
            status_code=400,
            detail="Selezionare una tipologia di scavo valida: paratia o palo.",
        )
    return tipologia


def _ensure_unique_numero_pannello(
    db: Session,
    site_id: int,
    tipologia_scavo: str,
    numero_pannello: int,
    *,
    exclude_fiche_id: int | None = None,
) -> None:
    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    query = db.query(Fiche.id).filter(
        Fiche.site_id == site_id,
        func.lower(Fiche.tipologia_scavo) == normalized_tipologia,
        Fiche.numero_pannello == numero_pannello,
    )
    if exclude_fiche_id is not None:
        query = query.filter(Fiche.id != exclude_fiche_id)
    duplicate_exists = query.first() is not None
    if duplicate_exists:
        label = "Paratia" if normalized_tipologia == "paratia" else "Palo"
        raise HTTPException(
            status_code=400,
            detail=f"{label} {numero_pannello} già registrato per questo cantiere",
        )


def _site_paratie_total(site: Site) -> int:
    return int(
        site.numero_totale_paratie
        if getattr(site, "numero_totale_paratie", None) is not None
        else (
            site.totale_paratie_da_scavare
            if site.totale_paratie_da_scavare is not None
            else (site.paratie_total_panels or 0)
        )
    )


def _site_pali_total(site: Site) -> int:
    return int(getattr(site, "numero_totale_pali", None) or 0)


def _fiche_schema_kind(fiche: Fiche) -> str:
    """Return the normalized excavation kind used by progress grids.

    Progress for paratie and pali must stay strictly separated: only the
    explicit ``tipologia_scavo`` value decides which grid a fiche completes.
    """

    tipologia = (fiche.tipologia_scavo or "").strip().lower()
    if tipologia in {"paratia", "palo"}:
        return tipologia
    return ""


def _build_site_fiche_grid_schema(
    total_elements: int, fiches: list[Fiche], element_kind: str
) -> list[dict]:
    """Build a green/grey fiche grid for one element type only."""

    if total_elements <= 0:
        return []

    fiches_by_number: dict[int, Fiche] = {}
    filtered_fiches = [
        fiche for fiche in fiches if _fiche_schema_kind(fiche) == element_kind
    ]
    for fiche in sorted(
        filtered_fiches, key=lambda item: (item.numero_pannello, item.id)
    ):
        element_number = int(fiche.numero_pannello or 0)
        if element_number < 1 or element_number > total_elements:
            continue
        fiches_by_number.setdefault(element_number, fiche)

    elements: list[dict] = []
    for element_number in range(1, total_elements + 1):
        fiche = fiches_by_number.get(element_number)
        created_by = getattr(fiche, "created_by", None) if fiche else None
        elements.append(
            {
                "number": element_number,
                "status": "completed" if fiche else "missing",
                "is_completed": fiche is not None,
                "fiche_id": fiche.id if fiche else None,
                "fiche_date": fiche.date if fiche else None,
                "caposquadra": (
                    (created_by.full_name or created_by.email)
                    if created_by is not None
                    else None
                ),
                "metri_cubi": fiche.metri_cubi_gettati if fiche else None,
                "ore_scavate": fiche.hours if fiche else None,
                "notes": fiche.notes if fiche else None,
                "planimetry": {
                    "x": None,
                    "y": None,
                    "width": None,
                    "height": None,
                },
            }
        )
    return elements


def _build_site_panel_schema(site: Site, fiches: list[Fiche]) -> list[dict]:
    """Build the paratie/pannelli grid model decoupled from rendering."""

    return _build_site_fiche_grid_schema(_site_paratie_total(site), fiches, "paratia")


def _build_site_pali_schema(site: Site, fiches: list[Fiche]) -> list[dict]:
    """Build the pali grid model decoupled from rendering."""

    return _build_site_fiche_grid_schema(_site_pali_total(site), fiches, "palo")


def _load_progress_grid_label_map(
    db: Session, site_id: int, tipologia: str, total_elements: int
) -> dict[int, str]:
    if total_elements <= 0:
        return {}
    rows = (
        db.query(SiteProgressGridName)
        .filter(
            SiteProgressGridName.site_id == site_id,
            func.lower(SiteProgressGridName.tipologia_scavo) == tipologia.lower(),
            SiteProgressGridName.numero_elemento >= 1,
            SiteProgressGridName.numero_elemento <= total_elements,
        )
        .order_by(SiteProgressGridName.numero_elemento.asc())
        .all()
    )
    return {int(row.numero_elemento): row.nome_personalizzato for row in rows}


def _progress_grid_display_name(
    element_number: int, default_label: str, custom_labels: dict[int, str] | None = None
) -> str:
    custom_label = (custom_labels or {}).get(element_number)
    if custom_label:
        return custom_label
    return str(element_number)


def _progress_grid_full_name(element_number: int, default_label: str) -> str:
    return f"{default_label} {element_number}"


def _save_progress_grid_label_map(
    db: Session, site_id: int, tipologia: str, total_elements: int, submitted_labels: dict[int, str]
) -> None:
    normalized_tipologia = _normalize_fiche_tipologia(tipologia)
    existing_rows = (
        db.query(SiteProgressGridName)
        .filter(
            SiteProgressGridName.site_id == site_id,
            func.lower(SiteProgressGridName.tipologia_scavo) == normalized_tipologia,
        )
        .all()
    )
    rows_by_number = {int(row.numero_elemento): row for row in existing_rows}
    for element_number in range(1, total_elements + 1):
        submitted_label = (submitted_labels.get(element_number) or "").strip()
        row = rows_by_number.get(element_number)
        if submitted_label:
            if row is None:
                db.add(
                    SiteProgressGridName(
                        site_id=site_id,
                        tipologia_scavo=normalized_tipologia,
                        numero_elemento=element_number,
                        nome_personalizzato=submitted_label,
                    )
                )
            else:
                row.nome_personalizzato = submitted_label
        elif row is not None:
            db.delete(row)


def _build_site_fiches_map(
    db: Session, site_id: int, tipologia: str, total_elements: int
) -> dict[int, Fiche]:
    """Return fiches keyed by numero_pannello for one excavation type only."""

    if total_elements <= 0:
        return {}

    fiches = (
        db.query(Fiche)
        .options(joinedload(Fiche.created_by))
        .filter(
            Fiche.site_id == site_id,
            func.lower(Fiche.tipologia_scavo) == tipologia.lower(),
            Fiche.numero_pannello >= 1,
            Fiche.numero_pannello <= total_elements,
        )
        .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
        .all()
    )
    fiches_map: dict[int, Fiche] = {}
    for fiche in fiches:
        fiches_map.setdefault(int(fiche.numero_pannello), fiche)
    return fiches_map


def _progress_map_summary(done: int, total: int) -> dict[str, int]:
    return {"done": done, "total": total, "percent": _progress_percent(done, total)}


def _build_avanzamento_grid_items(
    fiches_map: dict[int, Fiche],
    total_elements: int,
    label: str,
    custom_labels: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """Build the dedicated progress-grid view model with fiche preview data."""

    items: list[dict[str, object]] = []
    if total_elements <= 0:
        return items

    for element_number in range(1, total_elements + 1):
        fiche = fiches_map.get(element_number)
        display_name = _progress_grid_display_name(element_number, label, custom_labels)
        full_name = _progress_grid_full_name(element_number, label)
        if not fiche:
            items.append(
                {
                    "number": element_number,
                    "label": label,
                    "display_name": display_name,
                    "full_name": full_name,
                    "custom_label": (custom_labels or {}).get(element_number, ""),
                    "is_completed": False,
                    "status_label": "mancante",
                    "tooltip": f"{full_name}\nstato: mancante",
                    "preview": {
                        "title": full_name,
                        "missing": True,
                        "message": "Fiche non ancora creata",
                    },
                }
            )
            continue

        volume_teorico = _calculate_fiche_volume_teorico(fiche)
        volume_gettato = fiche.metri_cubi_gettati
        differenza_volume = (
            volume_gettato - volume_teorico
            if volume_gettato is not None and volume_teorico is not None
            else None
        )
        created_by = getattr(fiche, "created_by", None)
        operatore = (
            fiche.operator
            or ((created_by.full_name or created_by.email) if created_by else None)
            or "—"
        )
        items.append(
            {
                "number": element_number,
                "label": label,
                "display_name": display_name,
                "full_name": full_name,
                "custom_label": (custom_labels or {}).get(element_number, ""),
                "is_completed": True,
                "status_label": "completata",
                "tooltip": (
                    f"{full_name}\nstato: completata\ndata fiche: "
                    f"{fiche.date.strftime('%d/%m/%Y') if fiche.date else '—'}"
                ),
                "fiche_id": fiche.id,
                "preview": {
                    "title": full_name,
                    "missing": False,
                    "number": element_number,
                    "date": fiche.date.strftime("%d/%m/%Y") if fiche.date else "—",
                    "operator": operatore,
                    "volume_gettato": _format_progress_value(volume_gettato),
                    "volume_teorico": _format_progress_value(volume_teorico),
                    "differenza_volume": _format_progress_value(differenza_volume),
                    "profondita": _format_progress_value(fiche.profondita_totale),
                },
            }
        )
    return items


def _update_progress_summary_for_fiche_grids(
    progress_summary: dict[str, dict[str, object]],
    site: Site,
    fiches: list[Fiche],
    lang: str,
) -> None:
    paratie_total = _site_paratie_total(site)
    pali_total = _site_pali_total(site)
    paratie_done = len(
        {
            int(fiche.numero_pannello)
            for fiche in fiches
            if _fiche_schema_kind(fiche) == "paratia"
            and fiche.numero_pannello
            and 1 <= int(fiche.numero_pannello) <= paratie_total
        }
    )
    pali_done = len(
        {
            int(fiche.numero_pannello)
            for fiche in fiches
            if _fiche_schema_kind(fiche) == "palo"
            and fiche.numero_pannello
            and 1 <= int(fiche.numero_pannello) <= pali_total
        }
    )
    progress_summary["paratie"].update(
        {
            "total": paratie_total,
            "done": paratie_done,
            "percent": _progress_percent(paratie_done, paratie_total),
            "subtitle": f"{paratie_done} / {paratie_total} "
            f"{'pannelli' if lang == 'it' else 'panneaux'}",
        }
    )
    progress_summary["paratie"]["status"] = _progress_status(
        progress_summary["paratie"]["percent"], lang
    )
    progress_summary["pali"] = {
        "label": "Pali" if lang == "it" else "Pieux",
        "total": pali_total,
        "done": pali_done,
        "percent": _progress_percent(pali_done, pali_total),
        "unit": "pali" if lang == "it" else "pieux",
        "subtitle": f"{pali_done} / {pali_total} "
        f"{'pali' if lang == 'it' else 'pieux'}",
    }
    progress_summary["pali"]["status"] = _progress_status(
        progress_summary["pali"]["percent"], lang
    )


def _sync_site_fiche_progress(db: Session, site: Site) -> None:
    site_fiches = db.query(Fiche).filter(Fiche.site_id == site.id).all()
    paratie_total = _site_paratie_total(site)
    paratie_scavate = len(
        {
            int(fiche.numero_pannello)
            for fiche in site_fiches
            if _fiche_schema_kind(fiche) == "paratia"
            and fiche.numero_pannello
            and 1 <= int(fiche.numero_pannello) <= paratie_total
        }
    )
    site.paratie_done_panels = int(paratie_scavate)
    if site.totale_paratie_da_scavare is not None:
        site.paratie_total_panels = site.totale_paratie_da_scavare
    if getattr(site, "numero_totale_paratie", None) is None:
        site.numero_totale_paratie = site.totale_paratie_da_scavare
    paratie_total = _site_paratie_total(site)
    site.progress = _progress_percent(paratie_scavate, paratie_total)


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
    paratie_total = _site_paratie_total(site)
    paratie_done = int(site.paratie_done_panels or 0)
    pali_total = _site_pali_total(site)
    pali_done = 0
    installazione_cantiere_pct = _clamp_progress_percent(site.installazione_cantiere_pct)
    rabotage_pct = _clamp_progress_percent(site.rabotage_pct)
    pozzi_pompaggio_pct = _clamp_progress_percent(site.pozzi_pompaggio_pct)

    strut_levels = list(site.strut_levels or [])
    strut_total = sum(level.total_struts_level or 0 for level in strut_levels)
    strut_done = sum(level.done_struts_level or 0 for level in strut_levels)

    labels = {
        "cordoli": "Cordoli guida" if lang == "it" else "Guides (cordons)",
        "paratie": "Scavo + paratie" if lang == "it" else "Excavation + parois",
        "pali": "Pali" if lang == "it" else "Pieux",
        "puntoni": "Posa puntoni" if lang == "it" else "Pose des butons",
        "installazione_cantiere": "Installazione cantiere" if lang == "it" else "Installation chantier",
        "rabotage": "Rabotage" if lang == "it" else "Rabotage",
        "pozzi_pompaggio": "Pozzi pompaggio" if lang == "it" else "Puits de pompage",
    }
    units = {
        "cordoli": "m",
        "paratie": "pannelli" if lang == "it" else "panneaux",
        "pali": "pali" if lang == "it" else "pieux",
        "puntoni": "puntoni" if lang == "it" else "butons",
        "installazione_cantiere": "%",
        "rabotage": "%",
        "pozzi_pompaggio": "%",
    }

    cordoli_done_display = _format_progress_value(cordoli_done)
    cordoli_total_display = _format_progress_value(cordoli_total)
    paratie_done_display = _format_progress_value(paratie_done)
    paratie_total_display = _format_progress_value(paratie_total)
    pali_done_display = _format_progress_value(pali_done)
    pali_total_display = _format_progress_value(pali_total)
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
        "pali": {
            "label": labels["pali"],
            "total": pali_total,
            "done": pali_done,
            "percent": _progress_percent(pali_done, pali_total),
            "unit": units["pali"],
            "subtitle": f"{pali_done_display} / {pali_total_display} {units['pali']}",
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
        joinedload(Site.coupes).joinedload(SiteCoupe.assignments),
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
    totale_paratie_da_scavare: int | None = Form(None),
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

        submitted_total = (
            totale_paratie_da_scavare
            if totale_paratie_da_scavare is not None
            else paratie_total_panels
        )
        total_value = max(int(submitted_total or 0), 0)
        site.totale_paratie_da_scavare = total_value
        site.numero_totale_paratie = total_value
        site.paratie_total_panels = total_value
        _sync_site_fiche_progress(db, site)
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
        site = db.query(Site).options(joinedload(Site.strut_levels), joinedload(Site.coupes).joinedload(SiteCoupe.assignments), joinedload(Site.special_equipment_configs)).filter(Site.id == site_id).first()
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



def _optional_float_from_form(value: str | None) -> float | None:
    return _parse_decimal_comma_float(value, "valore coupe")


def _parse_coupe_element_numbers(raw_value: str) -> set[int]:
    numbers: set[int] = set()
    for token in re.split(r"[,;\s]+", (raw_value or "").strip()):
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start <= 0 or end <= 0 or end < start:
                raise HTTPException(status_code=400, detail="Associazione paratie/pali non valida.")
            numbers.update(range(start, end + 1))
            continue
        if not token.isdigit() or int(token) <= 0:
            raise HTTPException(status_code=400, detail="Associazione paratie/pali non valida.")
        numbers.add(int(token))
    return numbers


def _sync_site_coupes_from_form(
    db: Session,
    site: Site,
    *,
    coupe_id: list[str] | None,
    coupe_nome: list[str] | None,
    coupe_descrizione_zona: list[str] | None,
    coupe_quota_tn: list[str] | None,
    coupe_quota_testa: list[str] | None,
    coupe_quota_fondo_teorica: list[str] | None,
    coupe_base_paroi_mecanique: list[str] | None,
    coupe_profondita_teorica: list[str] | None,
    coupe_scavo_da_tn: list[str] | None,
    coupe_quota_partenza_scavo: list[str] | None,
    coupe_quota_testa_getto_prevista: list[str] | None,
    coupe_type_beton: list[str] | None,
    coupe_type_coulage: list[str] | None,
    coupe_spessore: list[str] | None,
    coupe_larghezza: list[str] | None,
    coupe_diametro: list[str] | None,
    coupe_terreno_teorico: list[str] | None,
    coupe_note: list[str] | None,
    coupe_paratie: list[str] | None,
    coupe_pali: list[str] | None,
    delete_coupe_id: list[str] | None = None,
) -> None:
    requested_delete_ids = {str(value).strip() for value in (delete_coupe_id or []) if str(value).strip()}
    coupe_ids_with_fiches = {str(fiche.coupe_id) for fiche in (site.fiches or []) if fiche.coupe_id is not None}
    blocked_delete_ids = requested_delete_ids & coupe_ids_with_fiches
    if blocked_delete_ids:
        raise HTTPException(status_code=400, detail="Non puoi eliminare una coupe già associata a fiches salvate.")
    delete_ids = requested_delete_ids - blocked_delete_ids
    existing = {str(coupe.id): coupe for coupe in (site.coupes or [])}
    row_count = max(
        len(coupe_id or []), len(coupe_nome or []), len(coupe_descrizione_zona or []),
        len(coupe_quota_tn or []), len(coupe_quota_testa or []), len(coupe_quota_fondo_teorica or []),
        len(coupe_base_paroi_mecanique or []), len(coupe_profondita_teorica or []), len(coupe_scavo_da_tn or []), len(coupe_quota_partenza_scavo or []),
        len(coupe_quota_testa_getto_prevista or []), len(coupe_type_beton or []), len(coupe_type_coulage or []),
        len(coupe_spessore or []), len(coupe_larghezza or []),
        len(coupe_diametro or []), len(coupe_terreno_teorico or []), len(coupe_note or []),
        len(coupe_paratie or []), len(coupe_pali or []), 0
    )
    seen: set[int] = set()
    assignment_payload: list[tuple[SiteCoupe, str, int]] = []

    def value(values: list[str] | None, index: int) -> str:
        return (values[index] if values and index < len(values) else "") or ""

    for index in range(row_count):
        name = value(coupe_nome, index).strip()
        has_any_value = any(
            value(values, index).strip()
            for values in (
                coupe_descrizione_zona, coupe_quota_tn, coupe_quota_testa, coupe_quota_fondo_teorica,
                coupe_base_paroi_mecanique, coupe_profondita_teorica, coupe_quota_partenza_scavo, coupe_quota_testa_getto_prevista,
                coupe_type_beton, coupe_type_coulage, coupe_spessore, coupe_larghezza, coupe_diametro, coupe_terreno_teorico, coupe_note,
                coupe_paratie, coupe_pali,
            )
        )
        row_id = value(coupe_id, index).strip()
        if row_id in delete_ids:
            continue
        if not name and not has_any_value:
            continue
        if not name:
            name = f"Coupe {index + 1}"
        coupe = existing.get(row_id) if row_id else None
        if coupe is None:
            coupe = SiteCoupe(site_id=site.id, nome=name)
            db.add(coupe)
        coupe.nome = name
        coupe.descrizione_zona = value(coupe_descrizione_zona, index).strip() or None
        coupe.quota_tn = _optional_float_from_form(value(coupe_quota_tn, index))
        coupe.quota_testa = _optional_float_from_form(value(coupe_quota_testa, index))
        coupe.quota_fondo_teorica = _optional_float_from_form(value(coupe_quota_fondo_teorica, index))
        coupe.base_paroi_mecanique = _optional_float_from_form(value(coupe_base_paroi_mecanique, index))
        coupe.profondita_teorica = _optional_float_from_form(value(coupe_profondita_teorica, index))
        if (
            coupe.quota_fondo_teorica is None
            and coupe.quota_testa is not None
            and coupe.profondita_teorica is not None
        ):
            coupe.quota_fondo_teorica = round(coupe.quota_testa - coupe.profondita_teorica, 2)
        coupe.scavo_da_tn = value(coupe_scavo_da_tn, index) != "0"
        coupe.quota_partenza_scavo = _optional_float_from_form(value(coupe_quota_partenza_scavo, index))
        coupe.quota_testa_getto_prevista = _optional_float_from_form(value(coupe_quota_testa_getto_prevista, index))
        _validate_quota_testa_getto_not_above_tn(coupe.quota_testa_getto_prevista, quota_tn=coupe.quota_tn)
        coupe.type_beton = value(coupe_type_beton, index).strip() or None
        coupe.type_coulage = value(coupe_type_coulage, index).strip() or "Gravitaire"
        coupe.spessore = _optional_float_from_form(value(coupe_spessore, index))
        coupe.larghezza = _optional_float_from_form(value(coupe_larghezza, index))
        coupe.diametro = _optional_float_from_form(value(coupe_diametro, index))
        coupe.terreno_teorico = value(coupe_terreno_teorico, index).strip() or None
        coupe.note = value(coupe_note, index).strip() or None
        db.flush()
        seen.add(coupe.id)
        for numero in _parse_coupe_element_numbers(value(coupe_paratie, index)):
            assignment_payload.append((coupe, "paratia", numero))
        for numero in _parse_coupe_element_numbers(value(coupe_pali, index)):
            assignment_payload.append((coupe, "palo", numero))

    db.query(SiteCoupeAssignment).filter(SiteCoupeAssignment.site_id == site.id).delete(synchronize_session=False)
    used_assignments: set[tuple[str, int]] = set()
    for coupe, tipologia, numero in assignment_payload:
        key = (tipologia, numero)
        if key in used_assignments:
            raise HTTPException(status_code=400, detail="Una paratia/palo non può essere associata a più coupe.")
        used_assignments.add(key)
        db.add(SiteCoupeAssignment(site_id=site.id, coupe_id=coupe.id, tipologia_scavo=tipologia, numero_elemento=numero))

    for coupe in list(site.coupes or []):
        should_delete = coupe.id not in seen or str(coupe.id) in delete_ids
        if should_delete and not any(fiche.coupe_id == coupe.id for fiche in site.fiches or []):
            db.delete(coupe)


def _site_coupe_configuration_complete(coupe: SiteCoupe) -> bool:
    """Return True when a coupe has the minimum data needed by fiche creation."""
    has_main_quotes = (
        bool(coupe.nome)
        and coupe.quota_tn is not None
        and coupe.quota_testa is not None
        and coupe.quota_fondo_teorica is not None
        and coupe.profondita_teorica is not None
        and coupe.quota_testa_getto_prevista is not None
    )
    has_geometry = (
        coupe.spessore is not None
        or coupe.larghezza is not None
        or coupe.diametro is not None
    )
    has_assignment = bool(coupe.assignments)
    return bool(has_main_quotes and has_geometry and has_assignment)


def _site_project_configuration_complete(site: Site) -> bool:
    """Return True when the site has at least one materially complete project coupe."""
    return any(_site_coupe_configuration_complete(coupe) for coupe in site.coupes or [])


def _format_coupe_assignments(coupe: SiteCoupe, tipologia: str) -> str:
    numbers = sorted(
        assignment.numero_elemento
        for assignment in (coupe.assignments or [])
        if assignment.tipologia_scavo == tipologia
    )
    if not numbers:
        return ""

    ranges: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)

def _load_real_depots_for_forms(db: Session):
    default_names = ["montauroux", "st. jeannet", "st jeannet", "sommariva", "cantieri"]
    return (
        db.query(Depot)
        .filter(Depot.is_active.is_(True))
        .filter(func.lower(func.trim(Depot.name)).notin_(default_names))
        .order_by(Depot.name.asc())
        .all()
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
        depositi_disponibili = _load_real_depots_for_forms(db)
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
            depositi_disponibili=depositi_disponibili,
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
    totale_paratie_da_scavare: str | None = Form(None),
    numero_totale_pali: str | None = Form(None),
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
    total_paratie_value = _parse_optional_non_negative_int(totale_paratie_da_scavare)
    total_pali_value = _parse_optional_non_negative_int(numero_totale_pali)
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
            depositi_disponibili = _load_real_depots_for_forms(db)
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
                    depositi_disponibili=depositi_disponibili,
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
                        "totale_paratie_da_scavare": totale_paratie_da_scavare or "",
                        "numero_totale_pali": numero_totale_pali or "",
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
            totale_paratie_da_scavare=total_paratie_value,
            numero_totale_paratie=total_paratie_value,
            numero_totale_pali=total_pali_value,
            paratie_total_panels=total_paratie_value,
            paratie_done_panels=0,
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

@app.get(
    "/manager/cantieri/{site_id}/configurazione-progetto",
    response_class=HTMLResponse,
    name="manager_site_project_config_get",
)
def manager_site_project_config_get(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "sites.update"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = (
            db.query(Site)
            .options(joinedload(Site.coupes).joinedload(SiteCoupe.assignments), joinedload(Site.special_equipment_configs))
            .filter(Site.id == site_id)
            .first()
        )
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        return templates.TemplateResponse(
            request,
            "manager/site_project_configuration.html",
            build_template_context(
                request,
                current_user,
                site=site,
                is_project_configured=_site_project_configuration_complete(site),
                format_coupe_assignments=_format_coupe_assignments,
                is_coupe_configured=_site_coupe_configuration_complete,
                equipment_rows=_build_site_special_equipment_rows(site),
            ),
        )
    finally:
        db.close()


@app.post(
    "/manager/cantieri/{site_id}/configurazione-progetto",
    response_class=HTMLResponse,
    name="manager_site_project_config_post",
)
def manager_site_project_config_post(
    request: Request,
    site_id: int,
    coupe_id: List[str] = Form(default_factory=list),
    coupe_nome: List[str] = Form(default_factory=list),
    coupe_descrizione_zona: List[str] = Form(default_factory=list),
    coupe_quota_tn: List[str] = Form(default_factory=list),
    coupe_quota_testa: List[str] = Form(default_factory=list),
    coupe_quota_fondo_teorica: List[str] = Form(default_factory=list),
    coupe_base_paroi_mecanique: List[str] = Form(default_factory=list),
    coupe_profondita_teorica: List[str] = Form(default_factory=list),
    coupe_scavo_da_tn: List[str] = Form(default_factory=list),
    coupe_quota_partenza_scavo: List[str] = Form(default_factory=list),
    coupe_quota_testa_getto_prevista: List[str] = Form(default_factory=list),
    coupe_type_beton: List[str] = Form(default_factory=list),
    coupe_type_coulage: List[str] = Form(default_factory=list),
    coupe_spessore: List[str] = Form(default_factory=list),
    coupe_larghezza: List[str] = Form(default_factory=list),
    coupe_diametro: List[str] = Form(default_factory=list),
    coupe_terreno_teorico: List[str] = Form(default_factory=list),
    coupe_note: List[str] = Form(default_factory=list),
    coupe_paratie: List[str] = Form(default_factory=list),
    coupe_pali: List[str] = Form(default_factory=list),
    delete_coupe_id: List[str] = Form(default_factory=list),
    equipment_tipologia: List[str] = Form(default_factory=list),
    equipment_numero: List[str] = Form(default_factory=list),
    equipment_mode: List[str] = Form(default_factory=list),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "sites.update"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = (
            db.query(Site)
            .options(joinedload(Site.coupes).joinedload(SiteCoupe.assignments), joinedload(Site.special_equipment_configs), joinedload(Site.fiches))
            .filter(Site.id == site_id)
            .first()
        )
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        try:
            _sync_site_coupes_from_form(
                db,
                site,
                coupe_id=coupe_id,
                coupe_nome=coupe_nome,
                coupe_descrizione_zona=coupe_descrizione_zona,
                coupe_quota_tn=coupe_quota_tn,
                coupe_quota_testa=coupe_quota_testa,
                coupe_quota_fondo_teorica=coupe_quota_fondo_teorica,
                coupe_base_paroi_mecanique=coupe_base_paroi_mecanique,
                coupe_profondita_teorica=coupe_profondita_teorica,
                coupe_scavo_da_tn=coupe_scavo_da_tn,
                coupe_quota_partenza_scavo=coupe_quota_partenza_scavo,
                coupe_quota_testa_getto_prevista=coupe_quota_testa_getto_prevista,
                coupe_type_beton=coupe_type_beton,
                coupe_type_coulage=coupe_type_coulage,
                coupe_spessore=coupe_spessore,
                coupe_larghezza=coupe_larghezza,
                coupe_diametro=coupe_diametro,
                coupe_terreno_teorico=coupe_terreno_teorico,
                coupe_note=coupe_note,
                coupe_paratie=coupe_paratie,
                coupe_pali=coupe_pali,
                delete_coupe_id=delete_coupe_id,
            )
            _sync_site_special_equipment_from_form(
                db,
                site,
                equipment_tipologia=equipment_tipologia,
                equipment_numero=equipment_numero,
                equipment_mode=equipment_mode,
            )
            _sync_site_fiche_progress(db, site)
            log_audit_event(
                db,
                current_user,
                "SITE_PROJECT_CONFIGURATION_UPDATED",
                "site",
                site.id,
                {"name": site.name, "coupe_count": len(site.coupes or [])},
            )
            db.commit()
        except HTTPException as exc:
            db.rollback()
            site = (
                db.query(Site)
                .options(joinedload(Site.coupes).joinedload(SiteCoupe.assignments), joinedload(Site.special_equipment_configs))
                .filter(Site.id == site_id)
                .first()
            )
            return templates.TemplateResponse(
                request,
                "manager/site_project_configuration.html",
                build_template_context(
                    request,
                    current_user,
                    site=site,
                    is_project_configured=_site_project_configuration_complete(site) if site else False,
                    format_coupe_assignments=_format_coupe_assignments,
                    is_coupe_configured=_site_coupe_configuration_complete,
                    equipment_rows=_build_site_special_equipment_rows(site) if site else [],
                    error_message=exc.detail,
                ),
                status_code=exc.status_code or 400,
            )
    finally:
        db.close()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/configurazione-progetto?saved=1",
        status_code=303,
    )


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
        site_fiches = (
            db.query(Fiche)
            .options(joinedload(Fiche.created_by), joinedload(Fiche.coupe))
            .filter(Fiche.site_id == site.id)
            .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
            .all()
        )
        panel_schema = _build_site_panel_schema(site, site_fiches)
        pali_schema = _build_site_pali_schema(site, site_fiches)
        numero_totale_paratie = _site_paratie_total(site)
        numero_totale_pali = _site_pali_total(site)
        paratie_fiches_map = _build_site_fiches_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_fiches_map = _build_site_fiches_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_grid_labels = _load_progress_grid_label_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_grid_labels = _load_progress_grid_label_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_progress_map = _progress_map_summary(
            len(paratie_fiches_map), numero_totale_paratie
        )
        pali_progress_map = _progress_map_summary(
            len(pali_fiches_map), numero_totale_pali
        )
        pali_fatti = len(pali_fiches_map)
        pali_percent = pali_progress_map["percent"]
        pali_map = pali_fiches_map
        _update_progress_summary_for_fiche_grids(
            progress_summary, site, site_fiches, lang
        )
        production_stats = compute_site_production(site, site_fiches)
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
            panel_schema=panel_schema,
            pali_schema=pali_schema,
            numero_totale_paratie=numero_totale_paratie,
            numero_totale_pali=numero_totale_pali,
            paratie_fiches_map=paratie_fiches_map,
            pali_fiches_map=pali_fiches_map,
            paratie_grid_labels=paratie_grid_labels,
            pali_grid_labels=pali_grid_labels,
            paratie_progress_map=paratie_progress_map,
            pali_progress_map=pali_progress_map,
            pali_fatti=pali_fatti,
            pali_percent=pali_percent,
            pali_map=pali_map,
            can_open_fiche_details=has_perm(current_user, "manager.access"),
            site_tasks=site_tasks,
            open_tasks=open_tasks,
            completed_tasks=completed_tasks,
            task_filter=task_filter,
            site_task_status_values=SITE_TASK_STATUSES,
            site_task_priority_values=SITE_TASK_PRIORITIES,
            manager_users=manager_users,
            production_stats=production_stats,
        ),
    )


@app.get(
    "/cantieri/{site_id}/avanzamento-griglie",
    response_class=HTMLResponse,
    name="site_progress_grids",
)
@app.get(
    "/manager/cantieri/{site_id}/avanzamento-griglie",
    response_class=HTMLResponse,
    name="manager_site_progress_grids",
)
@app.get(
    "/admin/cantieri/{site_id}/avanzamento-griglie",
    response_class=HTMLResponse,
    name="admin_site_progress_grids",
)
def manager_site_progress_grids(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    lang = request.cookies.get("lang", "it")
    db = SessionLocal()
    try:
        site = _get_site_for_detail(db, site_id, current_user)
        site_fiches = (
            db.query(Fiche)
            .options(joinedload(Fiche.created_by))
            .filter(Fiche.site_id == site.id)
            .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
            .all()
        )
        numero_totale_paratie = _site_paratie_total(site)
        numero_totale_pali = _site_pali_total(site)
        paratie_fiches_map = _build_site_fiches_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_fiches_map = _build_site_fiches_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_grid_labels = _load_progress_grid_label_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_grid_labels = _load_progress_grid_label_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_progress_map = _progress_map_summary(
            len(paratie_fiches_map), numero_totale_paratie
        )
        pali_progress_map = _progress_map_summary(
            len(pali_fiches_map), numero_totale_pali
        )
        progress_summary, _, _ = _build_site_progress(site, lang)
        _update_progress_summary_for_fiche_grids(
            progress_summary, site, site_fiches, lang
        )
        paratie_grid = _build_avanzamento_grid_items(
            paratie_fiches_map, numero_totale_paratie, "Paratia", paratie_grid_labels
        )
        pali_grid = _build_avanzamento_grid_items(
            pali_fiches_map, numero_totale_pali, "Palo", pali_grid_labels
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/avanzamento_griglie.html",
        build_template_context(
            request,
            current_user,
            site=site,
            progress_summary=progress_summary,
            numero_totale_paratie=numero_totale_paratie,
            numero_totale_pali=numero_totale_pali,
            paratie_progress_map=paratie_progress_map,
            pali_progress_map=pali_progress_map,
            paratie_grid_labels=paratie_grid_labels,
            pali_grid_labels=pali_grid_labels,
            paratie_grid=paratie_grid,
            pali_grid=pali_grid,
        ),
    )


@app.post(
    "/manager/cantieri/{site_id}/avanzamento-griglie",
    name="manager_site_progress_grids_update",
)
@app.post(
    "/admin/cantieri/{site_id}/avanzamento-griglie",
    name="admin_site_progress_grids_update",
)
async def manager_site_progress_grids_update(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    form = await request.form()

    def collect_labels(prefix: str, total_elements: int) -> dict[int, str]:
        labels: dict[int, str] = {}
        for element_number in range(1, total_elements + 1):
            labels[element_number] = str(form.get(f"{prefix}_{element_number}") or "")
        return labels

    db = SessionLocal()
    try:
        site = _get_site_for_detail(db, site_id, current_user)
        numero_totale_paratie = _site_paratie_total(site)
        numero_totale_pali = _site_pali_total(site)
        _save_progress_grid_label_map(
            db,
            site.id,
            "paratia",
            numero_totale_paratie,
            collect_labels("paratia_label", numero_totale_paratie),
        )
        _save_progress_grid_label_map(
            db,
            site.id,
            "palo",
            numero_totale_pali,
            collect_labels("palo_label", numero_totale_pali),
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(
        url=str(request.url_for("manager_site_progress_grids", site_id=site_id)),
        status_code=303,
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
        notify_new_site_task(db, task, current_user)
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
        notify_new_site_task(db, task, current_user)

        assigned_to_label = None
        if task.assigned_to_id:
            assigned_user = db.query(User).filter(User.id == task.assigned_to_id).first()
            assigned_to_label = _format_user_label(assigned_user)
        created_by_label = _format_user_label(current_user)
        site_name = db.query(Site.name).filter(Site.id == task.site_id).scalar()

        task_payload = {
            "id": task.id,
            "site_id": task.site_id,
            "title": task.title,
            "description": task.description or "",
            "status_value": task.status.value if task.status else SiteTaskStatusEnum.da_fare.value,
            "priority_value": task.priority.value if task.priority else SiteTaskPriorityEnum.media.value,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "assigned_to_id": task.assigned_to_id,
            "assigned_to_label": assigned_to_label,
            "created_by_label": created_by_label,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "completed_at_display": task.completed_at.strftime("%d/%m/%Y %H:%M") if task.completed_at else "—",
            "completed_by_label": None,
            "site_name": site_name,
        }

        open_count = _get_open_count_for_site(db, task.site_id)
        db.commit()

        return JSONResponse(
            {
                "success": True,
                "message": "Nota operativa creata con successo",
                "task": task_payload,
                "open_count": open_count,
            }
        )
    except HTTPException as exc:
        db.rollback()
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": str(exc.detail) if exc.detail else "Errore durante la creazione della nota",
            },
        )
    except Exception:
        db.rollback()
        logger.exception("Errore inatteso durante la creazione della nota operativa da modal")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "Errore inatteso durante la creazione della nota operativa",
            },
        )
    finally:
        db.close()


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
        task.completed_at = datetime.utcnow()
        task.completed_by_id = current_user.id
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

        completer_rows = (
            db.query(SiteTask.completed_by_id)
            .filter(
                SiteTask.site_id.in_(site_ids),
                _site_task_completed_clause(),
                SiteTask.completed_by_id.isnot(None),
            )
            .distinct()
            .all()
        )
        completer_ids = {row[0] for row in completer_rows if row[0]}
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
            .options(joinedload(Site.strut_levels), joinedload(Site.coupes).joinedload(SiteCoupe.assignments), joinedload(Site.special_equipment_configs))
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
        site_fiches = (
            db.query(Fiche)
            .options(joinedload(Fiche.created_by))
            .filter(Fiche.site_id == site.id)
            .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
            .all()
        )
        numero_totale_paratie = _site_paratie_total(site)
        numero_totale_pali = _site_pali_total(site)
        paratie_fiches_map = _build_site_fiches_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_fiches_map = _build_site_fiches_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_progress_map = _progress_map_summary(
            len(paratie_fiches_map), numero_totale_paratie
        )
        pali_progress_map = _progress_map_summary(
            len(pali_fiches_map), numero_totale_pali
        )
        pali_fatti = len(pali_fiches_map)
        pali_percent = pali_progress_map["percent"]
        pali_map = pali_fiches_map
        _update_progress_summary_for_fiche_grids(
            progress_summary, site, site_fiches, lang
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
            numero_totale_paratie=numero_totale_paratie,
            numero_totale_pali=numero_totale_pali,
            paratie_fiches_map=paratie_fiches_map,
            pali_fiches_map=pali_fiches_map,
            paratie_progress_map=paratie_progress_map,
            pali_progress_map=pali_progress_map,
            pali_fatti=pali_fatti,
            pali_percent=pali_percent,
            pali_map=pali_map,
            can_open_fiche_details=has_perm(current_user, "manager.access"),
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
    totale_paratie_da_scavare: str | None = Form(None),
    numero_totale_pali: str | None = Form(None),
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
    total_paratie_value = _parse_optional_non_negative_int(totale_paratie_da_scavare)
    total_pali_value = _parse_optional_non_negative_int(numero_totale_pali)
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
        site.totale_paratie_da_scavare = total_paratie_value
        site.numero_totale_paratie = total_paratie_value
        site.numero_totale_pali = total_pali_value
        site.paratie_total_panels = total_paratie_value
        _sync_site_fiche_progress(db, site)

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
        lang = request.cookies.get("lang", "it")
        progress_summary, _, _ = _build_site_progress(site, lang)
        site_fiches = (
            db.query(Fiche)
            .options(joinedload(Fiche.created_by), joinedload(Fiche.coupe))
            .filter(Fiche.site_id == site.id)
            .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
            .all()
        )
        panel_schema = _build_site_panel_schema(site, site_fiches)
        pali_schema = _build_site_pali_schema(site, site_fiches)
        numero_totale_paratie = _site_paratie_total(site)
        numero_totale_pali = _site_pali_total(site)
        paratie_fiches_map = _build_site_fiches_map(
            db, site.id, "paratia", numero_totale_paratie
        )
        pali_fiches_map = _build_site_fiches_map(
            db, site.id, "palo", numero_totale_pali
        )
        paratie_progress_map = _progress_map_summary(
            len(paratie_fiches_map), numero_totale_paratie
        )
        pali_progress_map = _progress_map_summary(
            len(pali_fiches_map), numero_totale_pali
        )
        pali_fatti = len(pali_fiches_map)
        pali_percent = pali_progress_map["percent"]
        pali_map = pali_fiches_map
        _update_progress_summary_for_fiche_grids(
            progress_summary, site, site_fiches, lang
        )
        production_stats = compute_site_production(site, site_fiches)
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
            progress_summary=progress_summary,
            panel_schema=panel_schema,
            pali_schema=pali_schema,
            numero_totale_paratie=numero_totale_paratie,
            numero_totale_pali=numero_totale_pali,
            paratie_fiches_map=paratie_fiches_map,
            pali_fiches_map=pali_fiches_map,
            paratie_progress_map=paratie_progress_map,
            pali_progress_map=pali_progress_map,
            pali_fatti=pali_fatti,
            pali_percent=pali_percent,
            pali_map=pali_map,
            can_open_fiche_details=False,
            site_tasks=site_tasks,
            open_tasks=open_tasks,
            completed_tasks=completed_tasks,
            can_add_tasks=has_perm(current_user, "manager.access"),
            production_stats=production_stats,
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
    start_of_next_week = start_of_week + timedelta(days=7)

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
            db.query(func.coalesce(func.sum(ReportWorker.hours_worked), 0.0))
            .join(Report, ReportWorker.report_id == Report.id)
            .join(Personale, ReportWorker.personale_id == Personale.id)
            .filter(Report.created_by_id == current_user.id)
            .filter(Report.date >= start_of_week)
            .filter(Report.date < start_of_next_week)
            .filter(Personale.user_id == current_user.id)
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


@app.get("/capo/rapportini", response_class=HTMLResponse)
def capo_rapportini_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    page, per_page = _normalize_pagination(page, per_page)

    db = SessionLocal()
    try:
        query = (
            db.query(Report)
            .options(
                joinedload(Report.site),
                joinedload(Report.workers).joinedload(ReportWorker.worker),
            )
            .filter(Report.created_by_id == current_user.id)
        )
        total_reports = query.count()
        total_pages = max(1, ceil(total_reports / per_page))
        if page > total_pages:
            page = total_pages

        reports_page = (
            query.order_by(Report.date.desc(), Report.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capo_lista_rapportini.html",
        build_template_context(
            request,
            current_user,
            user_role="capo",
            reports=reports_page,
            page=page,
            total_pages=total_pages,
            total_reports=total_reports,
        ),
    )


@app.get("/capo/rapportini/nuovo", response_class=HTMLResponse)
def pagina_nuovo_rapportino_capo(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Pagina per creare un nuovo rapportino giornaliero (caposquadra).
    Il JS della pagina chiamerà l'API POST /reports usando la sessione autenticata
    (cookie access_token) e, in fallback, eventuale Bearer token disponibile.
    """
    db = SessionLocal()
    try:
        cantieri = _get_capo_assigned_sites(db, current_user)
        cantieri_data = [
            {
                "id": cantiere.id,
                "name": cantiere.name,
            }
            for cantiere in cantieri
        ]

        caposquadra_personale = reports.ensure_capo_personale(db, current_user)
        caposquadra_personale_id = caposquadra_personale.id
        db.commit()

        operai_attivi = (
            db.query(Personale)
            .filter(Personale.attivo.is_(True))
            .filter(Personale.id != caposquadra_personale_id)
            .order_by(Personale.cognome, Personale.nome)
            .all()
        )
        operai_attivi_data = [
            {
                "id": operaio.id,
                "label": f"{operaio.cognome} {operaio.nome}".strip(),
            }
            for operaio in operai_attivi
        ]
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "capo_nuovo_rapportino.html",
        build_template_context(
            request,
            current_user,
            cantieri=cantieri_data,
            operai_attivi=operai_attivi_data,
            caposquadra_personale={"id": caposquadra_personale_id},
            caposquadra_label=(current_user.full_name or current_user.email),
        ),
    )




@app.post("/capo/rapportini/nuovo")
def pagina_nuovo_rapportino_capo_post(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
    data: date = Form(...),
    cantiere_id: int = Form(...),
    ore_totali: float = Form(...),
    numero_operai: int = Form(...),
    macchinari: str | None = Form(None),
    attivita: str | None = Form(None),
    note: str | None = Form(None),
    worker_personale_id: List[int] = Form(default_factory=list),
    worker_hours: List[float] = Form(default_factory=list),
    worker_role_label: List[str] = Form(default_factory=list),
    worker_note: List[str] = Form(default_factory=list),
    caposquadra_hours: float = Form(8.0),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == cantiere_id, Site.caposquadra_id == current_user.id, Site.is_active.is_(True)).first()
        if not site:
            raise HTTPException(status_code=422, detail="Cantiere non valido")

        if numero_operai < 1:
            raise HTTPException(status_code=422, detail="Il totale personale deve essere almeno 1")
        if len(worker_personale_id) != numero_operai - 1:
            raise HTTPException(
                status_code=422,
                detail="Il totale personale deve corrispondere a caposquadra + operai selezionati",
            )
        if len(set(worker_personale_id)) != len(worker_personale_id):
            raise HTTPException(status_code=422, detail="Non puoi selezionare la stessa persona due volte")

        caposquadra_personale = reports.ensure_capo_personale(db, current_user)
        if caposquadra_personale.id in worker_personale_id:
            raise HTTPException(status_code=422, detail="Il caposquadra è già incluso nel totale personale")

        workers = [
            ReportWorker(
                personale_id=caposquadra_personale.id,
                site_id=site.id,
                attendance_date=data,
                role_label="Caposquadra (tu)",
                hours_worked=caposquadra_hours,
                day_type="WORK",
            )
        ]
        for idx, personale_id in enumerate(worker_personale_id):
            workers.append(
                ReportWorker(
                    personale_id=personale_id,
                    site_id=site.id,
                    attendance_date=data,
                    role_label=(worker_role_label[idx] if idx < len(worker_role_label) and worker_role_label[idx] else None),
                    note=(worker_note[idx] if idx < len(worker_note) and worker_note[idx] else None),
                    hours_worked=(worker_hours[idx] if idx < len(worker_hours) else reports.DEFAULT_REPORT_WORKER_HOURS),
                    day_type="WORK",
                )
            )
        report = Report(
            date=data,
            site_id=site.id,
            site_name_or_code=site.name,
            total_hours=ore_totali,
            workers_count=numero_operai,
            machines_used=(macchinari or None),
            activities=(attivita or None),
            notes=(note or None),
            created_by_id=current_user.id,
            workers=workers,
        )
        db.add(report)
        db.flush()
        notify_new_report(db, report, current_user)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=CAPO_REPORT_CREATED_REDIRECT_URL, status_code=303)


@app.get("/capo/fiches/nuova", response_class=HTMLResponse)
def capo_fiche_nuova_get(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    return _render_fiche_create_form(
        request,
        current_user,
        template_name="capo/fiches_form.html",
        collections_loader=lambda: _load_capo_form_collections(current_user),
        extra_context={"show_ngf_fields": False, "show_project_coupe_fields": True},
    )


@app.post("/capo/fiches/nuova")
async def capo_fiche_nuova_post(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
    cantiere_id: int = Form(...),
    numero_pannello: str | None = Form(None),
    macchinario_id: str | None = Form(None),
    coupe_id: str | None = Form(None),
    scavo_da_tn: str | None = Form("1"),
    quota_testa_getto: str | None = Form(None),
    sonic_realizzato: str | None = Form(None),
    inclinometre_realizzato: str | None = Form(None),
    data_scavo: date = Form(...),
    data_getto: date | None = Form(None),
    metri_cubi_gettati: str | None = Form(None),
    operatore: str = Form(...),
    descrizione: str = Form(""),
    ore_lavorate: str | None = Form(None),
    note: str | None = Form(None),
    tipologia_scavo: str | None = Form(None),
    materiale: str | None = Form(None),
    profondita_totale: str | None = Form(None),
    diametro_palo_cm: str | None = Form(None),
    larghezza_pannello: str | None = Form(None),
    altezza_pannello: str | None = Form(None),
    strato_da: List[str] = Form(default_factory=list),
    strato_a: List[str] = Form(default_factory=list),
    strato_materiale: List[str] = Form(default_factory=list),
    strato_materiale_altro: List[str] = Form(default_factory=list),
):
    if current_user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    try:
        db = SessionLocal()
        try:
            _create_validated_fiche(
                db,
                current_user=current_user,
                cantiere_id=cantiere_id,
                numero_pannello=numero_pannello,
                macchinario_id=macchinario_id,
                coupe_id=coupe_id,
                scavo_da_tn=scavo_da_tn,
                quota_testa_getto=None,
                data_scavo=data_scavo,
                data_getto=data_getto,
                metri_cubi_gettati=metri_cubi_gettati,
                operatore=operatore,
                descrizione=descrizione,
                ore_lavorate=ore_lavorate,
                note=note,
                tipologia_scavo=tipologia_scavo,
                materiale=materiale,
                profondita_totale=profondita_totale,
                diametro_palo_cm=diametro_palo_cm,
                larghezza_pannello=larghezza_pannello,
                altezza_pannello=altezza_pannello,
                sonic_realizzato=sonic_realizzato,
                inclinometre_realizzato=inclinometre_realizzato,
                strato_da=strato_da,
                strato_a=strato_a,
                strato_materiale=strato_materiale,
                strato_materiale_altro=strato_materiale_altro,
                restrict_to_capo_sites=True,
            )
        finally:
            db.close()
    except HTTPException as exc:
        form_data = _build_fiche_error_form_data(
            cantiere_id=cantiere_id,
            numero_pannello=numero_pannello,
            macchinario_id=macchinario_id,
            coupe_id=coupe_id,
            scavo_da_tn=scavo_da_tn,
            quota_testa_getto=quota_testa_getto,
            sonic_realizzato=sonic_realizzato,
            inclinometre_realizzato=inclinometre_realizzato,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo_cm=diametro_palo_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
            strato_materiale_altro=strato_materiale_altro,
            invalid_fields=_invalid_fields_for_fiche_error(exc.detail),
        )
        return _render_fiche_create_form(
            request,
            current_user,
            template_name="capo/fiches_form.html",
            collections_loader=lambda: _load_capo_form_collections(current_user),
            status_code=exc.status_code or 400,
            form_data=form_data,
            error_message=exc.detail,
            extra_context={"show_ngf_fields": False, "show_project_coupe_fields": True},
        )

    return RedirectResponse(url="/capo/dashboard", status_code=303)


FICHE_TECHNICAL_FR_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("Quota testa getto", "Cote tête béton"),
    ("Quota testa", "Cote tête"),
    ("Quota fondo", "Cote fond"),
    ("Paratia", "Paroi moulée"),
    ("Pannello", "Paroi"),
    ("Palo", "Pieu"),
    ("Incontrato", "Rencontré"),
    ("Teorico", "Théorique"),
    ("Riporto", "Remblai"),
    ("Sabbia", "Sable"),
    ("Argilla", "Argile"),
    ("Ghiaia", "Gravier"),
    ("Limo", "Limon"),
    ("Altro", "Autre"),
)


def _translate_fiche_technical_text(value: object | None) -> str:
    """Return French chantier terminology for fiche technical/PDF labels."""
    import re

    text = "" if value is None else str(value)
    for source, target in FICHE_TECHNICAL_FR_TRANSLATIONS:
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    return re.sub(r"(?<!\()\bTN\b(?!\))", "Terrain naturel (TN)", text)


def _fiche_element_label_fr(tipologia_scavo: str | None, *, panel_term: bool = False) -> str:
    normalized = (tipologia_scavo or "").strip().lower()
    if normalized == "palo":
        return "Pieu"
    if normalized == "paratia":
        return "Paroi" if panel_term else "Paroi moulée"
    return "Élément"


def _materiale_stratigrafia_texture_class(materiale: str | None) -> str:
    label = (materiale or "").lower()
    if "riporto" in label or "remblai" in label:
        return "soil-layer--riporto"
    if "ghia" in label or "gravier" in label or "gravel" in label:
        return "soil-layer--ghiaia"
    if "argill" in label or "argile" in label or "clay" in label:
        return "soil-layer--argilla"
    if "rocc" in label or "roche" in label or "rock" in label:
        return "soil-layer--roccia"
    if "sabb" in label or "sable" in label or "sand" in label:
        return "soil-layer--sabbia"
    if "lim" in label or "silt" in label:
        return "soil-layer--limo"
    return "soil-layer--generico"


def _build_stratigrafia_visual_layers(fiche: Fiche) -> list[dict]:
    visual_layers: list[dict] = []
    structured_layers = sorted(
        list(fiche.stratigrafie or []), key=lambda layer: layer.da_profondita
    )
    if structured_layers:
        total_depth = float(
            fiche.profondita_totale or structured_layers[-1].a_profondita or 0
        )
        for layer in structured_layers:
            da_val = float(layer.da_profondita or 0)
            a_val = float(layer.a_profondita or 0)
            thickness = max(a_val - da_val, 0)
            visual_layers.append(
                {
                    "da": da_val,
                    "a": a_val,
                    "materiale": layer.materiale,
                    "height_percent": round((thickness / total_depth) * 100, 2)
                    if total_depth > 0
                    else 0,
                    "texture_class": _materiale_stratigrafia_texture_class(
                        layer.materiale
                    ),
                }
            )
        return visual_layers

    progressive_depth = 0.0
    fallback_layers = sorted(
        list(fiche.layers or []), key=lambda layer: layer.layer_index
    )
    total_depth = float(fiche.profondita_totale or 0) or sum(
        float(layer.thickness_m or 0) for layer in fallback_layers
    )
    for layer in fallback_layers:
        thickness = float(layer.thickness_m or 0)
        da_val = progressive_depth
        progressive_depth += thickness
        visual_layers.append(
            {
                "da": da_val,
                "a": progressive_depth,
                "materiale": layer.material,
                "height_percent": round((thickness / total_depth) * 100, 2)
                if total_depth > 0
                else 0,
                "texture_class": _materiale_stratigrafia_texture_class(layer.material),
            }
        )
    return visual_layers


def _parse_theoretical_soil_layers(text: str | None, fallback_depth: float | None = None) -> list[dict]:
    import re

    layers: list[dict] = []
    for line in (text or "").splitlines():
        match = re.search(
            r"([0-9]+(?:[\.,][0-9]+)?)\s*[-–]\s*([0-9]+(?:[\.,][0-9]+)?)\s*m?\s*:?\s*(.*)",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        da_val = float(match.group(1).replace(",", "."))
        a_val = float(match.group(2).replace(",", "."))
        if a_val <= da_val:
            continue
        layers.append(
            {
                "da": da_val,
                "a": a_val,
                "materiale": (match.group(3) or "Terreno").strip() or "Terreno",
            }
        )
    total_depth = float(fallback_depth or 0) or (max((layer["a"] for layer in layers), default=0))
    for layer in layers:
        thickness = max(layer["a"] - layer["da"], 0)
        layer["height_percent"] = round((thickness / total_depth) * 100, 2) if total_depth > 0 else 0
        layer["texture_class"] = _materiale_stratigrafia_texture_class(layer["materiale"])
    return layers


def _build_fiche_site_progress_card(site: Site, fiches_count: int) -> dict:
    total = int(
        site.totale_paratie_da_scavare
        if site.totale_paratie_da_scavare is not None
        else (site.paratie_total_panels or 0)
    )
    percent = _progress_percent(fiches_count, total) if total > 0 else 0
    is_completed = total > 0 and fiches_count >= total
    return {
        "site": site,
        "created": int(fiches_count),
        "total": total,
        "percent": percent,
        "is_completed": is_completed,
    }


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
    selected_site: Site | None = None

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

        fiche_counts = dict(
            db.query(Fiche.site_id, func.count(Fiche.id))
            .group_by(Fiche.site_id)
            .all()
        )
        sites = db.query(Site).order_by(Site.name.asc()).all()
        site_progress = [
            _build_fiche_site_progress_card(site, fiche_counts.get(site.id, 0))
            for site in sites
        ]
        active_site_progress = [
            card for card in site_progress if not card["is_completed"]
        ]
        completed_site_progress = [
            card for card in site_progress if card["is_completed"]
        ]

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
            selected_site = db.query(Site).filter(Site.id == parsed_site_id).first()
            query = query.filter(Fiche.site_id == parsed_site_id)
        if parsed_fiche_type:
            query = query.filter(Fiche.fiche_type == parsed_fiche_type)

        fiches_list = query.order_by(Fiche.date.desc(), Fiche.id.desc()).all()
        paratie_fiches_list = [
            fiche for fiche in fiches_list if _fiche_schema_kind(fiche) == "paratia"
        ]
        pali_fiches_list = [
            fiche for fiche in fiches_list if _fiche_schema_kind(fiche) == "palo"
        ]
    finally:
        db.close()

    return templates.TemplateResponse(
        request,
        "manager/fiches_list.html",
        build_template_context(
            request,
            current_user,
            fiches=fiches_list,
            paratie_fiches=paratie_fiches_list,
            pali_fiches=pali_fiches_list,
            total_fiches=len(fiches_list),
            active_site_progress=active_site_progress,
            completed_site_progress=completed_site_progress,
            selected_site=selected_site,
            selected_site_id=parsed_site_id,
            filters={
                "from_date": from_date or "",
                "to_date": to_date or "",
                "fiche_type": fiche_type or "",
            },
        ),
    )


@app.get(
    "/manager/fiches/{fiche_id}/modifica",
    response_class=HTMLResponse,
    name="manager_fiches_edit_form",
)
def manager_fiche_edit_form(
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
            .options(joinedload(Fiche.stratigrafie))
            .filter(Fiche.id == fiche_id)
            .first()
        )
        if not fiche:
            return RedirectResponse(
                url=request.url_for("manager_fiches_list"), status_code=303
            )
        form_data = _build_fiche_form_data_from_model(fiche)
    finally:
        db.close()

    return _render_fiche_create_form(
        request,
        current_user,
        template_name="capo/fiches_form.html",
        collections_loader=_load_manager_form_collections,
        form_data=form_data,
        extra_context={
            "is_edit": True,
            "fiche_form_area_label": {
                "fr": "Gestion des fiches",
                "it": "Gestione fiches",
            },
            "fiche_form_subtitle": {
                "fr": "Modifiez les informations de la fiche sélectionnée.",
                "it": "Modifica le informazioni della fiche selezionata.",
            },
            "fiche_cancel_url": str(request.url_for("manager_fiches_detail", fiche_id=fiche_id)),
            "show_ngf_fields": True,
            "show_project_coupe_fields": True,
            "show_capocantiere_field": True,
            "show_courbe_beton_fields": False,
        },
    )


@app.post(
    "/manager/fiches/{fiche_id}/modifica",
    response_class=HTMLResponse,
    name="manager_fiches_update",
)
async def manager_fiche_update(
    request: Request,
    fiche_id: int,
    current_user: User = Depends(get_current_active_user_html),
    cantiere_id: int = Form(...),
    numero_pannello: str | None = Form(None),
    macchinario_id: str | None = Form(None),
    capocantiere_id: str | None = Form(None),
    coupe_id: str | None = Form(None),
    scavo_da_tn: str | None = Form("1"),
    quota_testa_getto: str | None = Form(None),
    sonic_realizzato: str | None = Form(None),
    inclinometre_realizzato: str | None = Form(None),
    data_scavo: date = Form(...),
    data_getto: date | None = Form(None),
    metri_cubi_gettati: str | None = Form(None),
    operatore: str = Form(...),
    descrizione: str = Form(""),
    ore_lavorate: str | None = Form(None),
    note: str | None = Form(None),
    tipologia_scavo: str | None = Form(None),
    materiale: str | None = Form(None),
    profondita_totale: str | None = Form(None),
    diametro_palo_cm: str | None = Form(None),
    larghezza_pannello: str | None = Form(None),
    altezza_pannello: str | None = Form(None),
    quota_ngf_testa: str | None = Form(None),
    quota_ngf_fondo: str | None = Form(None),
    quota_ngf_note: str | None = Form(None),
    strato_da: List[str] = Form(default_factory=list),
    strato_a: List[str] = Form(default_factory=list),
    strato_materiale: List[str] = Form(default_factory=list),
    strato_materiale_altro: List[str] = Form(default_factory=list),
    courbe_beton_active: str | None = Form(None),
    courbe_realisee_volume: List[str] = Form(default_factory=list),
    courbe_realisee_hauteur: List[str] = Form(default_factory=list),
    courbe_tube_volume: List[str] = Form(default_factory=list),
    courbe_tube_hauteur: List[str] = Form(default_factory=list),
    courbe_beton_volume_total: str | None = Form(None),
    courbe_beton_hauteur_initiale: str | None = Form(None),
    courbe_beton_hauteur_finale: str | None = Form(None),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    try:
        db = SessionLocal()
        try:
            fiche = db.query(Fiche).filter(Fiche.id == fiche_id).first()
            if not fiche:
                return RedirectResponse(
                    url=request.url_for("manager_fiches_list"), status_code=303
                )
            _update_validated_fiche(
                db,
                fiche=fiche,
                current_user=current_user,
                cantiere_id=cantiere_id,
                numero_pannello=numero_pannello,
                macchinario_id=macchinario_id,
                capocantiere_id=capocantiere_id,
                coupe_id=coupe_id,
                scavo_da_tn=scavo_da_tn,
                quota_testa_getto=quota_testa_getto,
                data_scavo=data_scavo,
                data_getto=data_getto,
                metri_cubi_gettati=metri_cubi_gettati,
                operatore=operatore,
                descrizione=descrizione,
                ore_lavorate=ore_lavorate,
                note=note,
                tipologia_scavo=tipologia_scavo,
                materiale=materiale,
                profondita_totale=profondita_totale,
                diametro_palo_cm=diametro_palo_cm,
                larghezza_pannello=larghezza_pannello,
                altezza_pannello=altezza_pannello,
                quota_ngf_testa=quota_ngf_testa,
                quota_ngf_fondo=quota_ngf_fondo,
                quota_ngf_note=quota_ngf_note,
                sonic_realizzato=sonic_realizzato,
                inclinometre_realizzato=inclinometre_realizzato,
                strato_da=strato_da,
                strato_a=strato_a,
                strato_materiale=strato_materiale,
                strato_materiale_altro=strato_materiale_altro,
                courbe_beton_active=courbe_beton_active,
                courbe_realisee_volume=courbe_realisee_volume,
                courbe_realisee_hauteur=courbe_realisee_hauteur,
                courbe_tube_volume=courbe_tube_volume,
                courbe_tube_hauteur=courbe_tube_hauteur,
                courbe_beton_volume_total=courbe_beton_volume_total,
                courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
                courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
            )
        finally:
            db.close()
    except HTTPException as exc:
        form_data = _build_fiche_error_form_data(
            cantiere_id=cantiere_id,
            numero_pannello=numero_pannello,
            macchinario_id=macchinario_id,
            capocantiere_id=capocantiere_id,
            coupe_id=coupe_id,
            scavo_da_tn=scavo_da_tn,
            quota_testa_getto=quota_testa_getto,
            sonic_realizzato=sonic_realizzato,
            inclinometre_realizzato=inclinometre_realizzato,
            data_scavo=data_scavo,
            data_getto=data_getto,
            metri_cubi_gettati=metri_cubi_gettati,
            operatore=operatore,
            descrizione=descrizione,
            ore_lavorate=ore_lavorate,
            note=note,
            tipologia_scavo=tipologia_scavo,
            materiale=materiale,
            profondita_totale=profondita_totale,
            diametro_palo_cm=diametro_palo_cm,
            larghezza_pannello=larghezza_pannello,
            altezza_pannello=altezza_pannello,
            quota_ngf_testa=quota_ngf_testa,
            quota_ngf_fondo=quota_ngf_fondo,
            quota_ngf_note=quota_ngf_note,
            strato_da=strato_da,
            strato_a=strato_a,
            strato_materiale=strato_materiale,
            strato_materiale_altro=strato_materiale_altro,
            courbe_beton_active=courbe_beton_active,
            courbe_realisee_volume=courbe_realisee_volume,
            courbe_realisee_hauteur=courbe_realisee_hauteur,
            courbe_tube_volume=courbe_tube_volume,
            courbe_tube_hauteur=courbe_tube_hauteur,
            courbe_beton_volume_total=courbe_beton_volume_total,
            courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
            courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
            invalid_fields=_invalid_fields_for_fiche_error(exc.detail),
        )
        return _render_fiche_create_form(
            request,
            current_user,
            template_name="capo/fiches_form.html",
            collections_loader=_load_manager_form_collections,
            status_code=exc.status_code or 400,
            form_data=form_data,
            error_message=exc.detail,
            extra_context={
                "is_edit": True,
                "fiche_form_area_label": {
                    "fr": "Gestion des fiches",
                    "it": "Gestione fiches",
                },
                "fiche_form_subtitle": {
                    "fr": "Modifiez les informations de la fiche sélectionnée.",
                    "it": "Modifica le informazioni della fiche selezionata.",
                },
                "fiche_cancel_url": str(request.url_for("manager_fiches_detail", fiche_id=fiche_id)),
                "show_ngf_fields": True,
                "show_project_coupe_fields": True,
                "show_capocantiere_field": True,
                "show_courbe_beton_fields": False,
            },
        )

    return RedirectResponse(
        url=request.url_for("manager_fiches_detail", fiche_id=fiche_id), status_code=303
    )


@app.post(
    "/manager/fiches/{fiche_id}/dati-pdf",
    response_class=HTMLResponse,
    name="manager_fiches_update_pdf_data",
)
def manager_fiche_update_pdf_data(
    request: Request,
    fiche_id: int,
    current_user: User = Depends(get_current_active_user_html),
    responsable_pdf: str | None = Form(None),
    quota_tn: str | None = Form(None),
    quota_testa_getto: str | None = Form(None),
    larghezza_pannello: str | None = Form(None),
    altezza_pannello: str | None = Form(None),
    profondita_totale: str | None = Form(None),
    type_beton: str | None = Form(None),
    type_coulage: str | None = Form("Gravitaire"),
    terreno_teorico: str | None = Form(None),
    sonic_realizzato: str | None = Form(None),
    inclinometre_realizzato: str | None = Form(None),
    courbe_beton_active: str | None = Form(None),
    courbe_realisee_volume: List[str] = Form(default_factory=list),
    courbe_realisee_hauteur: List[str] = Form(default_factory=list),
    courbe_tube_volume: List[str] = Form(default_factory=list),
    courbe_tube_hauteur: List[str] = Form(default_factory=list),
    courbe_beton_volume_total: str | None = Form(None),
    courbe_beton_hauteur_initiale: str | None = Form(None),
    courbe_beton_hauteur_finale: str | None = Form(None),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()
    try:
        fiche = db.query(Fiche).filter(Fiche.id == fiche_id).first()
        if not fiche:
            return RedirectResponse(url=request.url_for("manager_fiches_list"), status_code=303)

        fiche.responsable_pdf = (responsable_pdf or "").strip() or None
        fiche.quota_tn = _parse_decimal_comma_float(quota_tn, "TN")
        fiche.quota_testa_getto = _parse_decimal_comma_float(quota_testa_getto, "quota testa getto")
        fiche.larghezza_pannello = _parse_decimal_comma_float(larghezza_pannello, "larghezza")
        fiche.altezza_pannello = _parse_decimal_comma_float(altezza_pannello, "spessore")
        fiche.profondita_totale = _parse_decimal_comma_float(profondita_totale, "profondità scavata")
        fiche.type_beton = (type_beton or "").strip() or None
        fiche.materiale = fiche.type_beton or fiche.materiale
        fiche.type_coulage = (type_coulage or "").strip() or "Gravitaire"
        fiche.terreno_teorico = (terreno_teorico or "").strip() or None
        _apply_courbe_beton_fields(
            fiche,
            courbe_beton_active=courbe_beton_active,
            courbe_realisee_volume=courbe_realisee_volume,
            courbe_realisee_hauteur=courbe_realisee_hauteur,
            courbe_tube_volume=courbe_tube_volume,
            courbe_tube_hauteur=courbe_tube_hauteur,
            courbe_beton_volume_total=courbe_beton_volume_total,
            courbe_beton_hauteur_initiale=courbe_beton_hauteur_initiale,
            courbe_beton_hauteur_finale=courbe_beton_hauteur_finale,
        )
        if fiche.sonic_previsto:
            sonic_value = _parse_bool_choice(sonic_realizzato)
            if sonic_value is None:
                raise HTTPException(status_code=400, detail="Sonic réalisé ? è obbligatorio.")
            fiche.sonic_realizzato = sonic_value
        else:
            fiche.sonic_realizzato = None
        if fiche.inclinometre_previsto:
            inclino_value = _parse_bool_choice(inclinometre_realizzato)
            if inclino_value is None:
                raise HTTPException(status_code=400, detail="Inclinomètre réalisé ? è obbligatorio.")
            fiche.inclinometre_realizzato = inclino_value
        else:
            fiche.inclinometre_realizzato = None
        _validate_quota_testa_getto_not_above_tn(fiche.quota_testa_getto, quota_tn=fiche.quota_tn)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url=request.url_for("manager_fiches_detail", fiche_id=fiche_id), status_code=303)


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
                joinedload(Fiche.coupe),
                joinedload(Fiche.machine),
                joinedload(Fiche.created_by),
                joinedload(Fiche.capocantiere),
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
            volume_teorico=_calculate_fiche_volume_teorico(fiche),
            stratigrafia_visual_layers=_build_stratigrafia_visual_layers(fiche),
            theoretical_soil_layers=_parse_theoretical_soil_layers(
                fiche.terreno_teorico or (fiche.coupe.terreno_teorico if fiche.coupe else None),
                fiche.profondita_totale,
            ),
            technical_fr=_translate_fiche_technical_text,
            fiche_element_label_fr=_fiche_element_label_fr,
            courbe_beton_payload=_build_courbe_beton_payload(fiche),
        ),
    )


# -------------------------------------------------
# PDF EXPORT — FICHE
# -------------------------------------------------

def _pdf_project_dir() -> str:
    import os
    return os.path.dirname(os.path.abspath(__file__))


def _pdf_logo_file_src() -> str:
    import os
    return "file://" + os.path.join(_pdf_project_dir(), "static", "img", "logo.png")


def _load_style_css() -> str:
    import os
    css_path = os.path.join(_pdf_project_dir(), "static", "css", "style.css")
    with open(css_path) as f:
        return f.read()


def _inline_style_css(html: str, css_text: str) -> str:
    import re
    return re.sub(
        r'<link\s+rel="stylesheet"\s+href="[^"]*style\.css[^"]*"\s*/?>',
        f"<style>{css_text}</style>",
        html,
    )


def _extract_technical_sheet(html: str) -> str:
    """Estrae solo l'<article id='technical-sheet-export'> dalla pagina completa.

    Evita di dare a WeasyPrint l'intera pagina (base.html, navbar, font e link
    esterni) che rallenta/blocca la generazione del PDF.
    """
    marker = 'id="technical-sheet-export"'
    idx = html.find(marker)
    if idx == -1:
        return html
    start = html.rfind("<article", 0, idx)
    end = html.find("</article>", idx)
    if start == -1 or end == -1:
        return html
    return html[start:end + len("</article>")]


def _wrap_sheet_document(article_html: str, css_text: str) -> str:
    """Costruisce un documento HTML minimale con solo il rapport + CSS inline."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{css_text}</style>"
        "<style>html,body{background:#fff !important;background-image:none !important;margin:0;padding:0;}</style>"
        f"</head><body>{article_html}</body></html>"
    )


def _load_fiche_for_pdf(db, fiche_id: int):
    return (
        db.query(Fiche)
        .options(
            joinedload(Fiche.site),
            joinedload(Fiche.coupe),
            joinedload(Fiche.machine),
            joinedload(Fiche.created_by),
            joinedload(Fiche.capocantiere),
            joinedload(Fiche.stratigrafie),
            joinedload(Fiche.layers),
        )
        .filter(Fiche.id == fiche_id)
        .first()
    )


def _render_fiche_article(request: Request, current_user: User, fiche: Fiche) -> str:
    """Renderizza SOLO l'articolo del rapport d'exécution di una fiche."""
    ctx = build_template_context(
        request,
        current_user,
        fiche=fiche,
        volume_teorico=_calculate_fiche_volume_teorico(fiche),
        stratigrafia_visual_layers=_build_stratigrafia_visual_layers(fiche),
        theoretical_soil_layers=_parse_theoretical_soil_layers(
            fiche.terreno_teorico or (fiche.coupe.terreno_teorico if fiche.coupe else None),
            fiche.profondita_totale,
        ),
        technical_fr=_translate_fiche_technical_text,
        fiche_element_label_fr=_fiche_element_label_fr,
        courbe_beton_payload=_build_courbe_beton_payload(fiche),
        pdf_mode=True,
        pdf_logo_src=_pdf_logo_file_src(),
    )
    full_html = templates.get_template("manager/fiches/fiche_detail.html").render(ctx)
    return _extract_technical_sheet(full_html)


def _render_fiche_pdf_html(request: Request, current_user: User, fiche: Fiche, css_text: str) -> str:
    """Documento HTML completo con una sola fiche (per il PDF singolo)."""
    return _wrap_sheet_document(_render_fiche_article(request, current_user, fiche), css_text)


@app.get(
    "/manager/fiches/{fiche_id}/pdf",
    name="manager_fiche_pdf",
)
def manager_fiche_pdf(
    request: Request,
    fiche_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()
    try:
        fiche = _load_fiche_for_pdf(db, fiche_id)
        if not fiche:
            raise HTTPException(status_code=404, detail="Fiche non trovata")

        css_text = _load_style_css()
        html = _render_fiche_pdf_html(request, current_user, fiche, css_text)

        from weasyprint import HTML as WeasyHTML
        pdf_bytes = WeasyHTML(string=html, base_url=_pdf_project_dir()).write_pdf()

        tipo = fiche.tipologia_scavo or "fiche"
        num = fiche.numero_pannello or 0
        date_str = fiche.date.strftime("%Y%m%d") if fiche.date else "nodate"
        site_code = (fiche.site.code or "site") if fiche.site else "site"
        filename = f"{site_code}_{tipo}_{num}_{date_str}.pdf"
    finally:
        db.close()

    from starlette.responses import Response as RawResponse
    return RawResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0",
        },
    )


@app.get(
    "/manager/cantieri/{site_id}/fiches-pdf/{tipo}",
    name="manager_site_fiches_pdf",
)
def manager_site_fiches_pdf(
    request: Request,
    site_id: int,
    tipo: str,
    current_user: User = Depends(get_current_active_user_html),
):
    """PDF unico di consegna cliente: copertina + tutte le fiches paratie o pali del cantiere."""
    if not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    if tipo not in ("paratie", "pali"):
        raise HTTPException(status_code=404, detail="Type non valide")
    is_palo = tipo == "pali"
    tipologia = "palo" if is_palo else "paratia"

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Chantier non trouvé")

        fiches = (
            db.query(Fiche)
            .options(
                joinedload(Fiche.site),
                joinedload(Fiche.coupe),
                joinedload(Fiche.machine),
                joinedload(Fiche.created_by),
                joinedload(Fiche.capocantiere),
                joinedload(Fiche.stratigrafie),
                joinedload(Fiche.layers),
            )
            .filter(Fiche.site_id == site_id, Fiche.tipologia_scavo == tipologia)
            .order_by(Fiche.numero_pannello.asc(), Fiche.id.asc())
            .all()
        )
        if not fiches:
            label = "pieux" if is_palo else "panneaux"
            raise HTTPException(status_code=404, detail=f"Aucune fiche {label} pour ce chantier")

        css_text = _load_style_css()

        # Descriptif des terrains: primo modello geologico teorico disponibile
        descriptif = next(
            (f.coupe.terreno_teorico for f in fiches if f.coupe and f.coupe.terreno_teorico),
            None,
        ) or next((f.terreno_teorico for f in fiches if f.terreno_teorico), None)

        cover_ctx = build_template_context(
            request,
            current_user,
            site=site,
            is_palo=is_palo,
            affaire=site.code,
            indice=0,
            mission="SUIVI DE MISSION G3",
            descriptif_terrains=descriptif,
            fiches_count=len(fiches),
            logo_src=_pdf_logo_file_src(),
            revision_date="",
            redaction="",
            controle="",
        )
        cover_inner = templates.get_template("manager/fiches/_pdf_cover.html").render(cover_ctx)

        try:
            # Un unico documento HTML: copertina + ogni fiche su pagina propria.
            # Ogni fiche è renderizzata identica al PDF singolo.
            parts = [cover_inner]
            for fiche in fiches:
                article = _render_fiche_article(request, current_user, fiche)
                parts.append(
                    f'<div style="page-break-before: always;">{article}</div>'
                )
            big_html = _wrap_sheet_document("".join(parts), css_text)

            from weasyprint import HTML as WeasyHTML
            base_url = _pdf_project_dir()
            pdf_bytes = WeasyHTML(string=big_html, base_url=base_url).write_pdf()
        except Exception as exc:  # noqa: BLE001 — surface PDF errors to the operator
            import traceback
            logger.exception("Errore generazione PDF unico fiches (site_id=%s, tipo=%s)", site_id, tipo)
            from starlette.responses import PlainTextResponse
            return PlainTextResponse(
                "Errore durante la generazione del PDF:\n\n" + traceback.format_exc(),
                status_code=500,
            )

        site_code = site.code or "chantier"
        filename = f"{site_code}_{tipo}_fiches.pdf"
    finally:
        db.close()

    from starlette.responses import Response as RawResponse
    return RawResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0",
        },
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
