from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
)
from models import User, RoleEnum, Report
from routers import users, sites, machines, reports, fiches


# -------------------------------------------------
# CREAZIONE TABELLE + ADMIN INIZIALE
# -------------------------------------------------

# Crea tutte le tabelle definite in models.py
Base.metadata.create_all(bind=engine)


def create_initial_admin():
    """
    Crea l'utente admin iniziale se non esiste.
    Admin:
        email:  lenta.federico@gmail.com
        pass:   Fulvio72
        ruolo:  admin
        lingua: it
    """
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.role == RoleEnum.admin).first()
        if not admin:
            user = User(
                email="lenta.federico@gmail.com",
                full_name="Federico Lenta",
                role=RoleEnum.admin,
                language="it",
                hashed_password=hash_password("Fulvio72"),
            )
            db.add(user)
            db.commit()
            print("Admin iniziale creato.")
        else:
            print("Admin già presente, nessuna creazione.")
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
    current_user: User = Depends(get_current_active_user),
):
    """
    Dashboard manager con accesso a cantieri, fiches, rapportini e macchinari.
    """
    return templates.TemplateResponse(
        "manager/home_manager.html",
        {
            "request": request,
            "user": current_user,
            "user_role": "manager",
        },
    )


@app.get("/capo/dashboard", response_class=HTMLResponse)
def capo_dashboard(
    request: Request,
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
):
    """
    Pagina manager: lista dei rapportini salvati nel database.
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
        "manager/rapportini.html",
        {
            "request": request,
            "user": current_user,
            "reports": reports_list,
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
