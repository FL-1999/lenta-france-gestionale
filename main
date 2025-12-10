from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine, SessionLocal
from auth import router as auth_router, hash_password
from models import User, RoleEnum
from routers import users, sites, machines, reports, fiches


# ----- crea tabelle -----
Base.metadata.create_all(bind=engine)


# ----- crea admin iniziale se non esiste -----
def create_initial_admin():
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


# ----- multilingua homepage -----

def get_lang_from_request(request: Request) -> str:
    lang = request.cookies.get("lang")
    if lang in ("it", "fr"):
        return lang
    return "it"


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    lang = get_lang_from_request(request)

    if lang == "fr":
        title = "Lenta France – Gestion de chantiers"
        description = "Plateforme de gestion pour chantiers, machines, fiches et rapports journaliers."
        btn_it = "Italien"
        btn_fr = "Français (actif)"
    else:
        title = "Lenta France – Gestionale Cantieri"
        description = "Piattaforma gestionale per cantieri, macchinari, fiches e rapportini giornalieri."
        btn_it = "Italiano (attivo)"
        btn_fr = "Francese"

    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>{title}</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: #e5e7eb;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
          }}
          .card {{
            background: #111827;
            padding: 24px 32px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.6);
            max-width: 480px;
          }}
          h1 {{ margin-bottom: 0.25rem; }}
          p {{ margin-top: 0.25rem; margin-bottom: 1.5rem; color: #9ca3af; }}
          .lang-buttons a {{
            margin-right: 8px;
            padding: 8px 14px;
            border-radius: 999px;
            text-decoration: none;
            border: 1px solid #4b5563;
            font-size: 0.9rem;
          }}
          .primary {{
            background: #2563eb;
            border-color: #2563eb;
            color: white;
          }}
          .secondary {{
            color: #e5e7eb;
          }}
          .links {{
            margin-top: 1.5rem;
            font-size: 0.9rem;
          }}
          .links a {{
            color: #93c5fd;
            text-decoration: none;
            margin-right: 12px;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>{title}</h1>
          <p>{description}</p>
          <div class="lang-buttons">
            <a class="{'primary' if lang == 'it' else 'secondary'}" href="/set-lang?lang=it">{btn_it}</a>
            <a class="{'primary' if lang == 'fr' else 'secondary'}" href="/set-lang?lang=fr">{btn_fr}</a>
          </div>
          <div class="links">
            <div>API docs: <a href="/docs">/docs</a></div>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/set-lang")
def set_lang(lang: str = "it"):
    if lang not in ("it", "fr"):
        lang = "it"
    response = RedirectResponse(url="/")
    response.set_cookie(key="lang", value=lang, max_age=60 * 60 * 24 * 365)
    return response


# ----- include routers -----

app.include_router(auth_router)
app.include_router(users.router)
app.include_router(sites.router)
app.include_router(machines.router)
app.include_router(reports.router)
app.include_router(fiches.router)