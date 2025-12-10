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
    allow_origins=["*"],
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
    Homepage con selezione lingua, login e dashboard (manager/caposquadra).
    Usa il template 'home.html' e passa la lingua letta dal cookie.
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
# PAGINE FRONTEND — MANAGER & CAPOSQUADRA
# -------------------------------------------------

@app.get("/manager/dashboard", response_class=HTMLResponse)
def manager_dashboard(request: Request):
    """
    Dashboard manager con accesso a cantieri, fiches, rapportini e macchinari.
    """
    return templates.TemplateResponse(
        "manager/home_manager.html",
        {
            "request": request,
            "user_role": "manager",
        },
    )


@app.get("/capo/dashboard", response_class=HTMLResponse)
def capo_dashboard(request: Request):
    """
    Dashboard caposquadra con funzioni limitate ai cantieri assegnati.
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
    Pagina per creare un nuovo rapportino giornaliero (caposquadra).
    """
    return templates.TemplateResponse(
        "capo_nuovo_rapportino.html",
        {
            "request": request,
        },
    )


# -------------------------------------------------
# INCLUDE DEI ROUTER API
# -------------------------------------------------

app.include_router(auth_router)
app.include_router(users.router)
app.include_router(sites.router)
app.include_router(machines.router)
app.include_router(reports.router)
app.include_router(fiches.router)
