import os
from datetime import date, datetime, timedelta
from typing import List

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlmodel import SQLModel

from database import Base, engine, SessionLocal, get_db
from auth import (
    router as auth_router,
    hash_password,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_current_active_user_html,
)
from deps import get_site_for_user, scope_sites_query
from models import (
    User,
    RoleEnum,
    Report,
    Site,
    SiteStatusEnum,
    Machine,
    FicheTypeEnum,
    Fiche,
    FicheStratigrafia,
    Personale,
    Veicolo,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
)
from routers import users, sites, machines, reports, fiches
from routes import manager_personale, manager_veicoli, magazzino, audit
from template_context import register_manager_badges, render_template


# -------------------------------------------------
# CREAZIONE TABELLE + ADMIN INIZIALE
# -------------------------------------------------

# Crea tutte le tabelle definite in models.py
Base.metadata.create_all(bind=engine)
SQLModel.metadata.create_all(bind=engine)


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
            )
            db.add(admin)
            message = "Admin iniziale creato."

        db.commit()
        print(message)
    except Exception as exc:
        db.rollback()
        print(f"Errore nella creazione/aggiornamento dell'admin iniziale: {exc}")
    finally:
        db.close()


create_initial_admin()


# -------------------------------------------------
# APP FASTAPI
# -------------------------------------------------

app = FastAPI(
    title="Lenta France Gestionale",
    description="Gestionale cantieri, macchinari, fiches e rapportini.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # se vuoi, in futuro, restringi ai tuoi domini
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static (CSS, immagini, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates HTML (Jinja2)
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)


# -------------------------------------------------
# MULTILINGUA (COOKIE) + HOMEPAGE TEMPLATE
# -------------------------------------------------

def get_lang_from_request(request: Request) -> str:
    lang = request.cookies.get("lang")
    if lang in ("it", "fr"):
        return lang
    return "it"


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    """
    Homepage con selezione lingua, login e accesso dashboard.
    Usa il template 'home.html'.
    """
    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "lang": lang,
        },
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
    Pagina di login HTML (form).
    Il JS dentro login.html può usare /auth/login o /auth/token per ottenere il JWT.
    """
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
        },
    )


@app.post("/auth/login")
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
    - Decide dove mandare l'utente (manager vs caposquadra)
    """
    user = authenticate_user(db, email=email, password=password)
    if not user:
        # Torniamo la pagina di login con errore
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "login_error": "Email o password non corretti",
            },
            status_code=400,
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(status_code=400, detail="Utente disattivato")

    # Crea il token JWT (usa la stessa funzione di /auth/token)
    access_token = create_access_token(data={"sub": user.email})

    # Puoi salvare il token in un cookie HttpOnly (così il JS può recuperarlo)
    response = RedirectResponse(
        url="/manager/dashboard" if user.role in (RoleEnum.admin, RoleEnum.manager) else "/capo/dashboard",
        status_code=303,
    )
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=60 * 60,  # 1 ora
        path="/",
    )
    return response


# -------------------------------------------------
# PAGINE FRONTEND — MANAGER & CAPOSQUADRA
# -------------------------------------------------

@app.get("/manager/dashboard", response_class=HTMLResponse)
def manager_dashboard(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Dashboard manager con accesso a cantieri, fiches, rapportini e macchinari.
    """
    db = SessionLocal()
    sites_map_data: list[dict[str, object]] = []
    try:
        sites_with_coords = (
            db.query(Site)
            .options(joinedload(Site.caposquadra))
            .filter(
                Site.lat.isnot(None),
                Site.lng.isnot(None),
            )
            .order_by(Site.name)
            .all()
        )
        sites_map_data = _build_sites_map_data(sites_with_coords)


        reports_list = (
            db.query(Report)
            .options(joinedload(Report.site))
            .order_by(Report.date.desc(), Report.id.desc())
            .all()
        )

        start_date = date.today() - timedelta(days=30)

        reports_last_30_days_rows = (
            db.query(Report.date.label("report_date"), func.count(Report.id).label("count"))
            .filter(Report.date >= start_date)
            .group_by(Report.date)
            .order_by(Report.date)
            .all()
        )
        reports_last_30_days = [
            {"date": row.report_date.isoformat(), "count": row.count}
            for row in reports_last_30_days_rows
        ]

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
        hours_per_site_30_days = [
            {"site_name": row.site_name or "Senza nome", "hours": float(row.hours or 0)}
            for row in hours_per_site_rows
        ]

        reports_by_status_counts = {"Aperti": 0, "Chiusi": 0}
        for report in reports_list:
            status_key = "Chiusi" if (report.total_hours or 0) > 0 else "Aperti"
            reports_by_status_counts[status_key] += 1
        reports_by_status = [
            {"status": key, "count": value}
            for key, value in reports_by_status_counts.items()
        ]
        response = render_template(
            templates,
            request,
            "manager/home_manager.html",
            {
                "user_role": "manager",
                "reports": reports_list,
                "chart_reports_last_30_days": jsonable_encoder(reports_last_30_days),
                "chart_hours_per_site_30_days": jsonable_encoder(hours_per_site_30_days),
                "chart_reports_by_status": jsonable_encoder(reports_by_status),
                "cantieri_map_data": jsonable_encoder(sites_map_data),
                "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY"),
            },
            db,
            current_user,
        )
    finally:
        db.close()
    return response


def _build_sites_map_data(sites: list[Site]) -> list[dict[str, object]]:
    sites_map_data = []
    for site in sites:
        address_parts = [part for part in [site.address, site.city, site.country] if part]
        status_value = site.status.value if site.status else None
        caposquadra_name = None
        if "caposquadra" in site.__dict__ and site.caposquadra:
            caposquadra_name = site.caposquadra.full_name or site.caposquadra.email
        sites_map_data.append(
            {
                "id": site.id,
                "name": site.name,
                "lat": site.lat,
                "lng": site.lng,
                "address": ", ".join(address_parts),
                "status": status_value,
                "is_active": site.is_active,
                "caposquadra_id": site.caposquadra_id,
                "caposquadra_name": caposquadra_name,
            }
        )
    return sites_map_data


@app.get(
    "/manager/fiches/nuova",
    response_class=HTMLResponse,
    name="manager_fiche_new_form",
)
def manager_fiche_new_form(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    sites, machines = _load_manager_form_collections()

    return templates.TemplateResponse(
        "manager/fiches_form.html",
        {
            "request": request,
            "user": current_user,
            "cantieri": sites,
            "macchinari": machines,
            "is_edit": False,
            "form_data": _build_fiche_form_data(),
            "error_message": None,
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
            "manager/fiches_form.html",
            {
                "request": request,
                "user": current_user,
                "cantieri": sites,
                "macchinari": machines,
                "is_edit": False,
                "form_data": form_data,
                "error_message": "Macchinario non valido",
            },
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
            "manager/fiches_form.html",
            {
                "request": request,
                "user": current_user,
                "cantieri": sites,
                "macchinari": machines,
                "is_edit": False,
                "form_data": form_data,
                "error_message": exc.detail,
            },
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        users_list = (
            db.query(User)
            .options(joinedload(User.assigned_sites))
            .order_by(User.role, User.email)
            .all()
        )
        user_sites_map = {
            user.id: list(user.assigned_sites or []) for user in users_list
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/users.html",
        {
            "request": request,
            "user": current_user,
            "user_role": "manager",
            "users": users_list,
            "user_sites_map": user_sites_map,
        },
    )


@app.get("/admin/permessi-magazzino", response_class=HTMLResponse)
def admin_magazzino_permissions(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        users_list = db.query(User).order_by(User.role, User.email).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        "admin/permessi_magazzino.html",
        {
            "request": request,
            "user": current_user,
            "users": users_list,
        },
    )


@app.post("/admin/permessi-magazzino/{user_id}/toggle", response_class=HTMLResponse)
def admin_magazzino_permissions_toggle(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role != RoleEnum.admin:
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    return templates.TemplateResponse(
        "manager/user_form.html",
        {
            "request": request,
            "user": current_user,
            "mode": "create",
            "user_obj": None,
            "user_id": None,
            "role_choices": list(RoleEnum),
            "language_choices": ["it", "fr"],
            "error_message": None,
            "form_email": "",
            "form_full_name": "",
            "form_role": "",
            "form_language": "",
        },
    )


@app.post("/manager/utenti/nuovo", response_class=HTMLResponse)
async def manager_new_user_post(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    form = await request.form()
    email = (form.get("email") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    password = (form.get("password") or "").strip()
    role_str = (form.get("role") or "").strip()
    language = (form.get("language") or "").strip()
    language = language or None

    def render_form(error_message: str, status_code: int = 400):
        return templates.TemplateResponse(
            "manager/user_form.html",
            {
                "request": request,
                "user": current_user,
                "mode": "create",
                "user_obj": None,
                "user_id": None,
                "role_choices": list(RoleEnum),
                "language_choices": ["it", "fr"],
                "error_message": error_message,
                "form_email": email,
                "form_full_name": full_name,
                "form_role": role_str,
                "form_language": language or "",
            },
            status_code=status_code,
        )

    if not email:
        return render_form("Email obbligatoria.")
    if not password:
        return render_form("Password obbligatoria.")
    if not role_str:
        return render_form("Ruolo obbligatorio.")

    role_enum = None
    try:
        role_enum = RoleEnum(role_str)
    except Exception:
        try:
            cleaned_role = role_str.split(".")[-1]
            role_enum = RoleEnum[cleaned_role]
        except Exception:
            return render_form("Ruolo non valido.")

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
            role=role_enum,
            language=language,
        )
        if hasattr(User, "is_active"):
            new_user.is_active = True

        db.add(new_user)
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    db = SessionLocal()
    try:
        user_to_edit = db.query(User).filter(User.id == user_id).first()
        if not user_to_edit:
            raise HTTPException(status_code=404, detail="Utente non trovato")
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/user_form.html",
        {
            "request": request,
            "user": current_user,
            "mode": "edit",
            "user_obj": user_to_edit,
            "user_id": user_to_edit.id,
            "role_choices": list(RoleEnum),
            "language_choices": ["it", "fr"],
            "error_message": None,
            "form_email": user_to_edit.email,
            "form_full_name": user_to_edit.full_name or "",
            "form_role": user_to_edit.role.value if user_to_edit.role else "",
            "form_language": user_to_edit.language or "",
        },
    )


@app.post("/manager/utenti/{user_id}/modifica", response_class=HTMLResponse)
async def manager_edit_user_post(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permessi insufficienti",
        )

    form = await request.form()
    email = (form.get("email") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    role_str = (form.get("role") or "").strip()
    language = (form.get("language") or "").strip() or None
    user_obj = None

    def render_form(error_message: str, status_code: int = 400):
        return templates.TemplateResponse(
            "manager/user_form.html",
            {
                "request": request,
                "user": current_user,
                "mode": "edit",
                "user_obj": user_obj,
                "user_id": user_id,
                "role_choices": list(RoleEnum),
                "language_choices": ["it", "fr"],
                "error_message": error_message,
                "form_email": email,
                "form_full_name": full_name,
                "form_role": role_str,
                "form_language": language or "",
            },
            status_code=status_code,
        )

    if not email:
        return render_form("Email obbligatoria.")
    if not role_str:
        return render_form("Ruolo obbligatorio.")

    role_enum = None
    try:
        role_enum = RoleEnum(role_str)
    except Exception:
        try:
            cleaned_role = role_str.split(".")[-1]
            role_enum = RoleEnum[cleaned_role]
        except Exception:
            return render_form("Ruolo non valido.")

    db = SessionLocal()
    try:
        user_to_edit = db.query(User).filter(User.id == user_id).first()
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

        user_to_edit.email = email
        user_to_edit.full_name = full_name or None
        user_to_edit.role = role_enum
        user_to_edit.language = language

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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
        "manager/user_reset_password.html",
        {
            "request": request,
            "user": current_user,
            "target_user": user_to_update,
            "error_message": None,
        },
    )


@app.post("/manager/utenti/{user_id}/reset-password", response_class=HTMLResponse)
async def manager_reset_password_post(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
            "manager/user_reset_password.html",
            {
                "request": request,
                "user": current_user,
                "target_user": target_user,
                "error_message": error_message,
            },
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
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        sites_list = (
            db.query(Site)
            .options(joinedload(Site.caposquadra))
            .order_by(
                Site.is_active.desc(),
                Site.start_date.desc(),
                Site.name,
            )
            .all()
        )
        site_caposquadra_map = {
            site.id: site.caposquadra for site in sites_list
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/cantieri.html",
        {
            "request": request,
            "sites": sites_list,
            "user": current_user,
            "site_caposquadra_map": site_caposquadra_map,
        },
    )


@app.get("/manager/sites/{site_id}", response_class=HTMLResponse, name="manager_site_detail")
def manager_site_detail(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = (
            db.query(Site)
            .options(joinedload(Site.caposquadra))
            .filter(Site.id == site_id)
            .first()
        )
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/site_detail.html",
        {
            "request": request,
            "user": current_user,
            "site": site,
        },
    )


@app.get("/manager/cantieri/nuovo", response_class=HTMLResponse)
def manager_cantiere_nuovo_get(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    site_status_values = [status.name for status in SiteStatusEnum]
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
        "manager/cantiere_form.html",
        {
            "request": request,
            "user": current_user,
            "mode": "create",
            "site": None,
            "site_status_values": site_status_values,
            "capisquadra": capisquadra,
            "google_maps_api_key": google_maps_api_key,
        },
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

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

    if has_address and (lat_value is None or lng_value is None):
        raise HTTPException(
            status_code=400,
            detail=(
                "Seleziona un indirizzo dai suggerimenti o clicca sulla mappa per "
                "impostare la posizione."
            ),
        )

    db = SessionLocal()
    try:
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
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/manager/cantieri", status_code=303)


@app.get("/manager/cantieri/{site_id}/modifica", response_class=HTMLResponse)
def manager_cantiere_modifica_get(
    request: Request,
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        if current_user.role == RoleEnum.caposquadra and site.caposquadra_id != current_user.id:
            raise HTTPException(status_code=403, detail="Permessi insufficienti")
        site_status_values = [status.name for status in SiteStatusEnum]
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
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/cantiere_form.html",
        {
            "request": request,
            "user": current_user,
            "mode": "edit",
            "site": site,
            "site_status_values": site_status_values,
            "scarichi_recenti": scarichi_recenti,
            "capisquadra": capisquadra,
            "google_maps_api_key": google_maps_api_key,
        },
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
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
    finally:
        db.close()

    return templates.TemplateResponse(
        "capo/site_detail.html",
        {
            "request": request,
            "user": current_user,
            "site": site,
        },
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
        assigned_sites_query = db.query(Site).filter(
            Site.is_active.is_(True),
            Site.lat.isnot(None),
            Site.lng.isnot(None),
        )
        assigned_sites_query = scope_sites_query(assigned_sites_query, current_user)
        assigned_sites_with_coords = assigned_sites_query.order_by(Site.name).all()
        assigned_sites_map_data = _build_sites_map_data(assigned_sites_with_coords)

        kpi_reports_today = (
            db.query(func.count(Report.id))
            .filter(Report.created_by_id == current_user.id)
            .filter(Report.date == today)
            .scalar()
            or 0
        )

        kpi_hours_this_week = (
            db.query(func.coalesce(func.sum(Report.total_hours), 0.0))
            .filter(Report.created_by_id == current_user.id)
            .filter(Report.date >= start_of_week)
            .scalar()
            or 0
        )

        kpi_assigned_sites = (
            db.query(func.count(Site.id))
            .filter(Site.caposquadra_id == current_user.id)
            .filter(Site.is_active.is_(True))
            .scalar()
            or 0
        )

        kpi_open_reports = (
            db.query(func.count(Report.id))
            .filter(Report.created_by_id == current_user.id)
            .filter(func.coalesce(Report.total_hours, 0) <= 0)
            .scalar()
            or 0
        )

    finally:
        db.close()

    return templates.TemplateResponse(
        "capo/home_capo.html",
        {
            "request": request,
            "user": current_user,
            "user_role": "capo",
            "kpi_reports_today": kpi_reports_today,
            "kpi_hours_this_week": kpi_hours_this_week,
            "kpi_assigned_sites": kpi_assigned_sites,
            "kpi_open_reports": kpi_open_reports,
            "cantieri_map_data": jsonable_encoder(assigned_sites_map_data),
            "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY"),
        },
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
    return templates.TemplateResponse(
        "capo_nuovo_rapportino.html",
        {
            "request": request,
            "user": current_user,
        },
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
        "capo/fiches_form.html",
        {
            "request": request,
            "user": current_user,
            "cantieri": sites,
            "macchinari": machines,
            "form_data": _build_fiche_form_data(),
            "error_message": None,
        },
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
            "capo/fiches_form.html",
            {
                "request": request,
                "user": current_user,
                "cantieri": sites,
                "macchinari": machines,
                "form_data": form_data,
                "error_message": "Macchinario non valido",
            },
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
            "capo/fiches_form.html",
            {
                "request": request,
                "user": current_user,
                "cantieri": sites,
                "macchinari": machines,
                "form_data": form_data,
                "error_message": exc.detail,
            },
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
        "manager/fiches_list.html",
        {
            "request": request,
            "user": current_user,
            "fiches": fiches_list,
            "total_fiches": len(fiches_list),
        },
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
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
        "manager/fiches/fiche_detail.html",
        {
            "request": request,
            "user": current_user,
            "fiche": fiche,
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
app.include_router(manager_personale.router)
app.include_router(manager_veicoli.router)
app.include_router(magazzino.router)
app.include_router(audit.router)
