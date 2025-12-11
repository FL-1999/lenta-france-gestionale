import os
from datetime import date, datetime

from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from database import Base, engine, SessionLocal, get_db
from auth import (
    router as auth_router,
    hash_password,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_current_active_user_html,
)
from models import User, RoleEnum, Report, Site, SiteStatusEnum
from routers import users, sites, machines, reports, fiches


# -------------------------------------------------
# CREAZIONE TABELLE + ADMIN INIZIALE
# -------------------------------------------------

# Crea tutte le tabelle definite in models.py
Base.metadata.create_all(bind=engine)


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
    try:
        reports_list = (
            db.query(Report)
            .order_by(Report.date.desc(), Report.id.desc())
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/home_manager.html",
        {
            "request": request,
            "user": current_user,
            "user_role": "manager",
            "reports": reports_list,
        },
    )


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
            .order_by(
                Site.is_active.desc(),
                Site.start_date.desc(),
                Site.name,
            )
            .all()
        )
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/cantieri.html",
        {
            "request": request,
            "sites": sites_list,
            "user": current_user,
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

    return templates.TemplateResponse(
        "manager/cantiere_form.html",
        {
            "request": request,
            "user": current_user,
            "mode": "create",
            "site": None,
            "site_status_values": site_status_values,
        },
    )


@app.post("/manager/cantieri/nuovo")
def manager_cantiere_nuovo_post(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    address: str | None = Form(None),
    city: str | None = Form(None),
    country: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    status: str = Form(...),
    is_active: str | None = Form(None),
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

    start_date_parsed = parse_date(start_date)
    end_date_parsed = parse_date(end_date)

    if status not in SiteStatusEnum.__members__:
        raise HTTPException(status_code=400, detail="Stato non valido")
    status_value = SiteStatusEnum[status]

    db = SessionLocal()
    try:
        new_site = Site(
            name=name,
            code=code,
            address=address,
            city=city,
            country=country,
            start_date=start_date_parsed,
            end_date=end_date_parsed,
            status=status_value,
            is_active=is_active is not None,
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
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        site_status_values = [status.name for status in SiteStatusEnum]
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
        },
    )


@app.post("/manager/cantieri/{site_id}/modifica")
def manager_cantiere_modifica_post(
    request: Request,
    site_id: int,
    name: str = Form(...),
    code: str = Form(...),
    address: str | None = Form(None),
    city: str | None = Form(None),
    country: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    status: str = Form(...),
    is_active: str | None = Form(None),
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

    start_date_parsed = parse_date(start_date)
    end_date_parsed = parse_date(end_date)

    if status not in SiteStatusEnum.__members__:
        raise HTTPException(status_code=400, detail="Stato non valido")
    status_value = SiteStatusEnum[status]

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")

        site.name = name
        site.code = code
        site.address = address
        site.city = city
        site.country = country
        site.start_date = start_date_parsed
        site.end_date = end_date_parsed
        site.status = status_value
        site.is_active = is_active is not None

        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/manager/cantieri", status_code=303)


@app.get("/capo/dashboard", response_class=HTMLResponse)
def capo_dashboard(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Dashboard caposquadra con funzioni limitate ai cantieri assegnati.
    """
    return templates.TemplateResponse(
        "capo/home_capo.html",
        {
            "request": request,
            "user": current_user,
            "user_role": "caposquadra",
        },
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


@app.get("/manager/rapportini", response_class=HTMLResponse)
def manager_rapportini(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    site: str | None = None,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Pagina manager: lista dei rapportini salvati nel database.
    """
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()

    parsed_from_date = None
    parsed_to_date = None

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

        query = db.query(Report)

        if parsed_from_date:
            query = query.filter(Report.date >= parsed_from_date)

        if parsed_to_date:
            query = query.filter(Report.date <= parsed_to_date)

        if site:
            query = query.filter(Report.site_name_or_code.ilike(f"%{site}%"))

        reports_list = query.order_by(Report.date.desc(), Report.id.desc()).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/rapportini.html",
        {
            "request": request,
            "user": current_user,
            "reports": reports_list,
            "filter_from_date": from_date,
            "filter_to_date": to_date,
            "filter_site": site,
        },
    )


@app.get("/manager/rapportini/{report_id}", response_class=HTMLResponse)
def manager_rapportino_dettaglio(
    request: Request,
    report_id: int,
    current_user: User = Depends(get_current_active_user_html),
):
    """
    Pagina manager: dettaglio di un singolo rapportino.
    """

    if current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Rapportino non trovato")
    finally:
        db.close()

    return templates.TemplateResponse(
        "manager/rapportino_dettaglio.html",
        {
            "request": request,
            "user": current_user,
            "report": report,
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
