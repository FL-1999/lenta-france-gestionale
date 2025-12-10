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

# crea tutte le tabelle definite in models.py
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
            "lang": lang,  # se un giorno vuoi usarla dentro il template
        },
    )


@app.get("/set-lang")
def set_lang(lang: str = "it"):
    """
    Imposta la lingua (it / fr) nel cookie e reindirizza alla homepage.
    Anche se l'interfaccia usa localStorage, tenere il cookie non fa male
    e può tornare utile in futuro.
    """
    if lang not in ("it", "fr"):
        lang = "it"
    response = RedirectResponse(url="/")
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response


# -------------------------------------------------
# PAGINE SPECIFICHE FRONTEND (CAPOSQUADRA, ECC.)
# -------------------------------------------------

@app.get("/capo/rapportini/nuovo", response_class=HTMLResponse)
def pagina_nuovo_rapportino_capo(request: Request):
    """
    Pagina per il caposquadra per creare un nuovo rapportino giornaliero.
    Usa il template 'capo_nuovo_rapportino.html'.
    """
    return templates.TemplateResponse(
        "capo_nuovo_rapportino.html",
        {
            "request": request,
        },
    )

# (Qui in futuro puoi aggiungere altre pagine HTML, ad esempio:
#  /manager/cantieri, /capo/fiches, ecc. con altri template.)


# -------------------------------------------------
# INCLUDE DEI ROUTER API
# -------------------------------------------------

app.include_router(auth_router)
app.include_router(users.router)
app.include_router(sites.router)
app.include_router(machines.router)
app.include_router(reports.router)
app.include_router(fiches.router)
