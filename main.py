from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from database import Base, engine, SessionLocal
from auth import router as auth_router, hash_password
from models import User, RoleEnum
from routers import users, sites, machines, reports, fiches

# -------------------------------------------------
# CREAZIONE TABELLE + ADMIN INIZIALE
# -------------------------------------------------

Base.metadata.create_all(bind=engine)

def create_initial_admin():
    """
    Crea l’utente admin iniziale se non esiste.
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
# CONFIGURAZIONE FASTAPI
# -------------------------------------------------

app = FastAPI(
    title="Lenta France Gestionale",
    description="Gestionale cantieri, macchinari, fiches e rapportini.",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# -------------------------------------------------
# LINGUA (COOKIE)
# -------------------------------------------------

def get_lang_from_request(request: Request) -> str:
    lang = request.cookies.get("lang")
    if lang in ("it", "fr"):
        return lang
    return "it"

# -------------------------------------------------
# HOMEPAGE (usa home.html)
# -------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
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
    if lang not in ("it", "fr"):
        lang = "it"

    response = RedirectResponse(url="/")
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response

# -------------------------------------------------
# PAGINA LOGIN (FRONTEND)
# -------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """
    Pagina di login: inserisci email e password,
    la pagina farà una chiamata a /auth/login.
    """
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
        },
    )

# -------------------------------------------------
# PAGINE FRONTEND — MANAGER
# -------------------------------------------------

@app.get("/manager/dashboard", response_class=HTMLResponse)
def manager_dashboard(request: Request):
    """
    Dashboard manager: accesso completo.
    """
    return templates.TemplateResponse(
        "manager/home_manager.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/cantieri", response_class=HTMLResponse)
def manager_cantieri_lista(request: Request):
    """
    Lista cantieri (vista manager).
    """
    return templates.TemplateResponse(
        "manager/cantieri_lista.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/cantieri/nuovo", response_class=HTMLResponse)
def manager_cantieri_nuovo(request: Request):
    """
    Creazione nuovo cantiere (manager).
    """
    return templates.TemplateResponse(
        "manager/cantieri_nuovo.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/fiches", response_class=HTMLResponse)
def manager_fiches_lista(request: Request):
    """
    Lista fiches (manager).
    """
    return templates.TemplateResponse(
        "manager/fiches_lista.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/fiches/nuova", response_class=HTMLResponse)
def manager_fiches_nuova(request: Request):
    """
    Nuova fiche (manager).
    """
    return templates.TemplateResponse(
        "manager/fiches_nuova.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/rapportini", response_class=HTMLResponse)
def manager_rapportini_lista(request: Request):
    """
    Lista rapportini (manager).
    """
    return templates.TemplateResponse(
        "manager/rapportini_lista.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/rapportini/esporta", response_class=HTMLResponse)
def manager_rapportini_esporta(request: Request):
    """
    Pagina mock per esportazione rapportini (in futuro: PDF/Excel).
    """
    return templates.TemplateResponse(
        "manager/rapportini_esporta.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/macchinari", response_class=HTMLResponse)
def manager_macchinari_lista(request: Request):
    """
    Lista macchinari (manager).
    """
    return templates.TemplateResponse(
        "manager/macchinari_lista.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/manager/macchinari/assegna", response_class=HTMLResponse)
def manager_macchinari_assegna(request: Request):
    """
    Assegnazione macchinari ai cantieri (manager).
    """
    return templates.TemplateResponse(
        "manager/macchinari_assegna.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )

# -------------------------------------------------
# PAGINE FRONTEND — CAPOSQUADRA
# -------------------------------------------------

@app.get("/capo/dashboard", response_class=HTMLResponse)
def capo_dashboard(request: Request):
    """
    Dashboard caposquadra: funzioni limitate ai cantieri assegnati.
    """
    return templates.TemplateResponse(
        "capo/home_capo.html",
        {
            "request": request,
            "user_role": "capo",
        },
    )


@app.get("/capo/rapportini/nuovo", response_class=HTMLResponse)
def pagina_nuovo_rapportino_capo(request: Request):
    """
    Pagina per creare un nuovo rapportino giornaliero.
    """
    return templates.TemplateResponse(
        "capo_nuovo_rapportino.html",
        {
            "request": request,
            "user_role": "capo",
        },
    )


@app.get("/capo/rapportini", response_class=HTMLResponse)
def capo_lista_rapportini(request: Request):
    """
    Lista dei rapportini del caposquadra.
    """
    return templates.TemplateResponse(
        "capo_lista_rapportini.html",
        {
            "request": request,
            "user_role": "capo",
        },
    )


@app.get("/capo/fiches/nuova", response_class=HTMLResponse)
def capo_nuova_fiche(request: Request):
    """
    Creazione di una nuova fiche di cantiere.
    """
    return templates.TemplateResponse(
        "capo_nuova_fiche.html",
        {
            "request": request,
            "user_role": "capo",
        },
    )


@app.get("/capo/fiches", response_class=HTMLResponse)
def capo_lista_fiches(request: Request):
    """
    Lista delle fiches del caposquadra.
    """
    return templates.TemplateResponse(
        "capo_lista_fiches.html",
        {
            "request": request,
            "user_role": "capo",
        },
    )

# -------------------------------------------------
# ROUTER API
# -------------------------------------------------

app.include_router(auth_router)
app.include_router(users.router)
app.include_router(sites.router)
app.include_router(machines.router)
app.include_router(reports.router)
app.include_router(fiches.router)
