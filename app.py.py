from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional, Dict

from fastapi import FastAPI, Depends, HTTPException, Header, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    Date,
    DateTime,
    Text,
    Enum as SAEnum,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# =========================
# CONFIGURAZIONE DI BASE
# =========================

DATABASE_URL = "sqlite:///./lenta_france_app.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Lenta France – Gestionale Cantieri")

SUPPORTED_LANGUAGES = ("it", "fr")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# ENUM / RUOLI
# =========================

class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    foreman = "foreman"   # caposquadra


class CantiereStatus(str, Enum):
    prossimo = "prossimo"
    in_corso = "in_corso"
    completato = "completato"
    sospeso = "sospeso"


class MacchinarioTipo(str, Enum):
    escavatore = "escavatore"
    pala_gommata = "pala_gommata"
    macchina_pali = "macchina_pali"
    macchina_paratie = "macchina_paratie"
    altro = "altro"


class ScavoTipo(str, Enum):
    palo = "palo"
    paratia = "paratia"
    micropalo = "micropalo"
    diaframma = "diaframma"
    jet_grouting = "jet_grouting"
    altro = "altro"


# =========================
# MODELLI DB (SQLAlchemy)
# =========================

class UtenteDB(Base):
    __tablename__ = "utenti"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)  # in produzione va hashata
    ruolo = Column(SAEnum(UserRole), nullable=False, default=UserRole.foreman)
    lingua = Column(String, default="it")
    attivo = Column(Boolean, default=True)
    creato_il = Column(DateTime, default=datetime.utcnow)

    dipendente = relationship("DipendenteDB", back_populates="utente", uselist=False)
    cantieri_foreman = relationship("CantiereDB", back_populates="foreman_utente")


class DipendenteDB(Base):
    __tablename__ = "dipendenti"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    cognome = Column(String, nullable=False)
    ruolo = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    attivo = Column(Boolean, default=True)

    utente_id = Column(Integer, ForeignKey("utenti.id"), nullable=True)

    utente = relationship("UtenteDB", back_populates="dipendente")
    rapportini_presenze = relationship(
        "RapportinoPresenzaDB", back_populates="dipendente"
    )


class CantiereDB(Base):
    __tablename__ = "cantieri"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    localita = Column(String, nullable=True)
    committente = Column(String, nullable=True)
    impresa = Column(String, nullable=True)
    tipologie_lavorazione = Column(String, nullable=True)
    data_inizio = Column(Date, nullable=True)
    data_fine = Column(Date, nullable=True)
    stato = Column(SAEnum(CantiereStatus), default=CantiereStatus.prossimo)
    completamento_percento = Column(Integer, default=0)
    note = Column(Text, nullable=True)

    # caposquadra responsabile del cantiere
    foreman_user_id = Column(Integer, ForeignKey("utenti.id"), nullable=True)

    fiches = relationship("FicheForageDB", back_populates="cantiere")
    rapportini = relationship("RapportinoDB", back_populates="cantiere")
    macchinari = relationship("MacchinarioDB", back_populates="cantiere")
    foreman_utente = relationship("UtenteDB", back_populates="cantieri_foreman")


class FicheForageDB(Base):
    __tablename__ = "fiches_forage"

    id = Column(Integer, primary_key=True, index=True)
    cantiere_id = Column(Integer, ForeignKey("cantieri.id"), nullable=False)

    nome_fiche = Column(String, nullable=False)      # es. "P21", "Palo 5"
    numero_pannello = Column(String, nullable=True)
    data_scavo = Column(Date, nullable=True)
    data_getto = Column(Date, nullable=True)

    tipo_scavo = Column(SAEnum(ScavoTipo), nullable=False)

    # valori generali
    profondita_totale_m = Column(Float, nullable=True)   # totalità scavata (m)
    dimensione_cm = Column(Float, nullable=True)
    metri_cubi_gettati = Column(Float, nullable=True)

    # specifici per tipo
    diametro_cm = Column(Float, nullable=True)           # per PALI
    profondita_paratia_m = Column(Float, nullable=True)  # per PARATIE – profondità totale (m)
    larghezza_paratia_m = Column(Float, nullable=True)   # per PARATIE – larghezza pannello (m)

    osservazioni = Column(Text, nullable=True)

    cantiere = relationship("CantiereDB", back_populates="fiches")
    strati = relationship(
        "StratigrafiaStratoDB",
        back_populates="fiche",
        cascade="all, delete-orphan",
    )


class StratigrafiaStratoDB(Base):
    __tablename__ = "stratigrafia_strati"

    id = Column(Integer, primary_key=True, index=True)
    fiche_id = Column(Integer, ForeignKey("fiches_forage.id"), nullable=False)

    da_m = Column(Float, nullable=False)
    a_m = Column(Float, nullable=False)
    descrizione = Column(Text, nullable=True)

    fiche = relationship("FicheForageDB", back_populates="strati")


class RapportinoDB(Base):
    __tablename__ = "rapportini"

    id = Column(Integer, primary_key=True, index=True)
    cantiere_id = Column(Integer, ForeignKey("cantieri.id"), nullable=False)

    data = Column(Date, nullable=False)
    meteo = Column(String, nullable=True)
    operai_presenti = Column(Integer, nullable=True)
    ore_lavorate_totali = Column(Float, nullable=True)

    descrizione_lavori = Column(Text, nullable=True)
    macchinari_utilizzati = Column(Text, nullable=True)
    materiali_utilizzati = Column(Text, nullable=True)

    creato_da_utente_id = Column(Integer, ForeignKey("utenti.id"), nullable=True)

    cantiere = relationship("CantiereDB", back_populates="rapportini")
    presenze_dipendenti = relationship(
        "RapportinoPresenzaDB", back_populates="rapportino"
    )
    creato_da_utente = relationship("UtenteDB")


class RapportinoPresenzaDB(Base):
    __tablename__ = "rapportini_presenze"

    id = Column(Integer, primary_key=True, index=True)
    rapportino_id = Column(Integer, ForeignKey("rapportini.id"), nullable=False)
    dipendente_id = Column(Integer, ForeignKey("dipendenti.id"), nullable=False)

    ore_lavorate = Column(Float, nullable=True)

    rapportino = relationship("RapportinoDB", back_populates="presenze_dipendenti")
    dipendente = relationship("DipendenteDB", back_populates="rapportini_presenze")


class MacchinarioDB(Base):
    __tablename__ = "macchinari"

    id = Column(Integer, primary_key=True, index=True)
    nome_macchinario = Column(String, nullable=False)   # es. LIEBHERR HS 833 HD
    modello = Column(String, nullable=True)
    matricola = Column(String, nullable=True)
    tipo = Column(SAEnum(MacchinarioTipo), default=MacchinarioTipo.altro)

    data_ultimo_tagliando = Column(Date, nullable=True)

    cantiere_id = Column(Integer, ForeignKey("cantieri.id"), nullable=True)
    note = Column(Text, nullable=True)

    # problemi segnalati dal caposquadra
    ha_problema = Column(Boolean, default=False)
    problema_corrente = Column(Text, nullable=True)

    cantiere = relationship("CantiereDB", back_populates="macchinari")


class NotificationDB(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read = Column(Boolean, default=False)
    tipo = Column(String, nullable=True)  # "rapportino", "fiche", "macchinario", ...

    user = relationship("UtenteDB")


# =========================
# MODELLI API (Pydantic)
# =========================

# --- UTENTI / LOGIN ---

class UtenteBase(BaseModel):
    email: EmailStr
    lingua: str = Field("it")


class Utente(UtenteBase):
    id: int
    ruolo: UserRole
    attivo: bool

    class Config:
        orm_mode = True


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class UtenteCreateAdmin(BaseModel):
    email: EmailStr
    password: str
    ruolo: UserRole = UserRole.foreman
    lingua: str = "it"
    attivo: bool = True


# --- DIPENDENTI ---

class DipendenteBase(BaseModel):
    nome: str
    cognome: str
    ruolo: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    note: Optional[str] = None
    attivo: bool = True


class DipendenteCreate(DipendenteBase):
    utente_id: Optional[int] = None


class Dipendente(DipendenteBase):
    id: int
    utente_id: Optional[int]

    class Config:
        orm_mode = True


# --- CANTIERI ---

class CantiereBase(BaseModel):
    nome: str
    localita: Optional[str] = None
    committente: Optional[str] = None
    impresa: Optional[str] = None
    tipologie_lavorazione: Optional[str] = None
    data_inizio: Optional[date] = None
    data_fine: Optional[date] = None
    stato: CantiereStatus = CantiereStatus.prossimo
    completamento_percento: int = Field(0, ge=0, le=100)
    note: Optional[str] = None
    foreman_user_id: Optional[int] = None


class CantiereCreate(CantiereBase):
    pass


class Cantiere(CantiereBase):
    id: int

    class Config:
        orm_mode = True


# --- STRATIGRAFIA ---

class StratigrafiaStratoBase(BaseModel):
    da_m: float
    a_m: float
    descrizione: Optional[str] = None


class StratigrafiaStratoCreate(StratigrafiaStratoBase):
    fiche_id: int


class StratigrafiaStrato(StratigrafiaStratoBase):
    id: int
    fiche_id: int

    class Config:
        orm_mode = True


# --- FICHES FORAGE ---

class FicheForageBase(BaseModel):
    cantiere_id: int
    nome_fiche: str
    numero_pannello: Optional[str] = None
    data_scavo: Optional[date] = None
    data_getto: Optional[date] = None
    tipo_scavo: ScavoTipo

    # generali
    profondita_totale_m: Optional[float] = None
    dimensione_cm: Optional[float] = None
    metri_cubi_gettati: Optional[float] = None

    # specifici
    diametro_cm: Optional[float] = None              # per PALI
    profondita_paratia_m: Optional[float] = None     # per PARATIE – profondità totale (m)
    larghezza_paratia_m: Optional[float] = None      # per PARATIE – larghezza pannello (m)

    osservazioni: Optional[str] = None


class FicheForageCreate(FicheForageBase):
    pass


class FicheForage(FicheForageBase):
    id: int

    class Config:
        orm_mode = True


# --- RAPPORINI ---

class RapportinoBase(BaseModel):
    cantiere_id: int
    data: date
    meteo: Optional[str] = None
    operai_presenti: Optional[int] = None
    ore_lavorate_totali: Optional[float] = None
    descrizione_lavori: Optional[str] = None
    macchinari_utilizzati: Optional[str] = None
    materiali_utilizzati: Optional[str] = None
    creato_da_utente_id: Optional[int] = None


class RapportinoCreate(RapportinoBase):
    pass


class Rapportino(RapportinoBase):
    id: int

    class Config:
        orm_mode = True


class RapportinoPresenzaBase(BaseModel):
    rapportino_id: int
    dipendente_id: int
    ore_lavorate: Optional[float] = None


class RapportinoPresenzaCreate(RapportinoPresenzaBase):
    pass


class RapportinoPresenza(RapportinoPresenzaBase):
    id: int

    class Config:
        orm_mode = True


# --- MACCHINARI ---

class MacchinarioBase(BaseModel):
    nome_macchinario: str
    modello: Optional[str] = None
    matricola: Optional[str] = None
    tipo: MacchinarioTipo = MacchinarioTipo.altro
    data_ultimo_tagliando: Optional[date] = None
    cantiere_id: Optional[int] = None
    note: Optional[str] = None


class MacchinarioCreate(MacchinarioBase):
    pass


class Macchinario(MacchinarioBase):
    id: int
    ha_problema: bool
    problema_corrente: Optional[str] = None

    class Config:
        orm_mode = True


# --- NOTIFICHE ---

class Notification(BaseModel):
    id: int
    user_id: int
    message: str
    created_at: datetime
    read: bool
    tipo: Optional[str] = None

    class Config:
        orm_mode = True


class NotificationCreate(BaseModel):
    user_id: int
    message: str
    tipo: Optional[str] = None


# =========================
# CREAZIONE TABELLE + ADMIN
# =========================

Base.metadata.create_all(bind=engine)

ADMIN_EMAIL = "lenta.federico@gmail.com"
ADMIN_PASSWORD = "Fulvio72"


def seed_admin():
    """Crea automaticamente l'admin con le credenziali fornite, se non esiste."""
    db = SessionLocal()
    try:
        existing = db.query(UtenteDB).filter(UtenteDB.email == ADMIN_EMAIL).first()
        if not existing:
            admin = UtenteDB(
                email=ADMIN_EMAIL,
                password=ADMIN_PASSWORD,
                ruolo=UserRole.admin,
                lingua="it",
                attivo=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


seed_admin()


# =========================
# AUTH MOLTO SEMPLICE
# =========================

TOKENS: Dict[str, int] = {}  # token -> user_id (solo in memoria)


def create_token_for_user(user: UtenteDB) -> str:
    token = f"token-{user.id}-{int(datetime.utcnow().timestamp())}"
    TOKENS[token] = user.id
    return token


def get_current_user(
    db: Session = Depends(get_db),
    x_token: str = Header(..., alias="X-Token"),
) -> UtenteDB:
    user_id = TOKENS.get(x_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token non valido o scaduto")
    user = db.query(UtenteDB).get(user_id)
    if not user or not user.attivo:
        raise HTTPException(status_code=401, detail="Utente non valido o disattivato")
    return user


def require_roles(*ruoli: UserRole):
    def dependency(user: UtenteDB = Depends(get_current_user)) -> UtenteDB:
        if user.ruolo not in ruoli:
            raise HTTPException(status_code=403, detail="Permessi insufficienti")
        return user

    return dependency


@app.post("/auth/login")
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = (
        db.query(UtenteDB)
        .filter(
            UtenteDB.email == str(payload.email),
            UtenteDB.password == payload.password,
            UtenteDB.attivo == True,
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    token = create_token_for_user(user)
    return {"token": token, "user": Utente.from_orm(user)}


# =========================
# MULTILINGUA – HOMEPAGE + COOKIE
# =========================

@app.get("/set-lang")
def set_language(lang: str):
    """Salva la lingua scelta in un cookie e torna alla homepage."""
    if lang not in SUPPORTED_LANGUAGES:
        return RedirectResponse(url="/")
    response = RedirectResponse(url="/")
    # cookie valido 1 anno
    response.set_cookie(
        key="lang",
        value=lang,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="Lax",
    )
    return response


@app.get("/", response_class=HTMLResponse)
def homepage(
    lang: Optional[str] = None,
    lang_cookie: Optional[str] = Cookie(None),
):
    # logica scelta lingua: query > cookie > default
    if lang in SUPPORTED_LANGUAGES:
        current_lang = lang
    elif lang_cookie in SUPPORTED_LANGUAGES:
        current_lang = lang_cookie
    else:
        current_lang = "it"

    TXT = {
        "it": {
            "title": "Lenta France – Fondazioni speciali",
            "subtitle": "Fondazioni speciali & opere nel sottosuolo",
            "headline": "Gestionale cantieri e produzione – area interna",
            "desc": (
                "Questo sito ospita il gestionale interno di Lenta France per la gestione di "
                "cantieri, fiches di scavo, rapportini giornalieri, macchinari e personale. "
                "L'accesso è riservato ad amministratori, manager e capisquadra autorizzati."
            ),
            "choose": "Seleziona la lingua preferita:",
            "pill": "Portale cantieri · Accesso riservato",
            "area": "Area riservata / API",
            "api_hint": "(per il momento l'accesso avviene tramite interfaccia tecnica API)",
            "foot_addr": "ZAC de Saint-Estève – Saint-Jeannet 06640 · France",
            "foot_rights": "Tutti i diritti riservati.",
        },
        "fr": {
            "title": "Lenta France – Fondations spéciales",
            "subtitle": "Fondations spéciales & travaux souterrains",
            "headline": "Plateforme chantiers et production – espace interne",
            "desc": (
                "Ce site héberge la plateforme interne de Lenta France pour la gestion des "
                "chantiers, des fiches forage, des rapports journaliers, des machines et du personnel. "
                "L'accès est réservé aux administrateurs, managers et chefs d'équipe autorisés."
            ),
            "choose": "Choisissez la langue préférée :",
            "pill": "Portail chantiers · Accès réservé",
            "area": "Espace réservé / API",
            "api_hint": "(pour le moment l'accès se fait via l'interface technique API)",
            "foot_addr": "ZAC de Saint-Estève – Saint-Jeannet 06640 · France",
            "foot_rights": "Tous droits réservés.",
        },
    }

    T = TXT[current_lang]
    year = datetime.utcnow().year

    html = """
    <!DOCTYPE html>
    <html lang="{lang}">
    <head>
        <meta charset="UTF-8" />
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="description" content="{title}" />
        <style>
            body {{
                margin: 0;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #0f172a;
                color: #e5e7eb;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
            }}
            .card {{
                background: rgba(15,23,42,0.96);
                border-radius: 18px;
                padding: 32px 28px;
                max-width: 720px;
                width: 100%;
                box-shadow: 0 20px 60px rgba(0,0,0,0.45);
                border: 1px solid rgba(148,163,184,0.35);
            }}
            .logo {{
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: #38bdf8;
            }}
            .subtitle {{
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.18em;
                color: #9ca3af;
                margin-top: 4px;
            }}
            h1 {{
                margin-top: 20px;
                font-size: 24px;
                color: #e5e7eb;
            }}
            p {{
                font-size: 15px;
                line-height: 1.6;
                color: #d1d5db;
            }}
            .pill {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                border-radius: 999px;
                padding: 6px 12px;
                background: rgba(15, 118, 110, 0.12);
                color: #6ee7b7;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.18em;
            }}
            .section {{
                margin-top: 20px;
            }}
            .lang-buttons {{
                display: flex;
                gap: 10px;
                margin-top: 10px;
                flex-wrap: wrap;
            }}
            .btn {{
                border-radius: 999px;
                border: 1px solid rgba(148,163,184,0.6);
                padding: 10px 18px;
                font-size: 14px;
                cursor: pointer;
                background: rgba(15,23,42,0.6);
                color: #e5e7eb;
                text-decoration: none;
                transition: all 0.15s ease-in-out;
            }}
            .btn.primary {{
                background: linear-gradient(135deg, #0ea5e9, #22c55e);
                border-color: transparent;
                color: #0f172a;
                font-weight: 600;
            }}
            .btn:hover {{
                transform: translateY(-1px);
                box-shadow: 0 10px 25px rgba(0,0,0,0.35);
                border-color: #38bdf8;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 16px;
                margin-top: 20px;
            }}
            .feature {{
                padding: 12px 12px 14px;
                border-radius: 14px;
                background: rgba(15,23,42,0.9);
                border: 1px solid rgba(55,65,81,0.9);
                font-size: 13px;
            }}
            .feature-title {{
                font-weight: 600;
                margin-bottom: 4px;
                color: #e5e7eb;
            }}
            .footer {{
                margin-top: 24px;
                font-size: 12px;
                color: #9ca3af;
                display: flex;
                justify-content: space-between;
                gap: 12px;
                flex-wrap: wrap;
            }}
            @media (max-width: 640px) {{
                .card {{
                    margin: 16px;
                    padding: 24px 18px;
                }}
                h1 {{
                    font-size: 20px;
                }}
            }}
        </style>
    </head>
    <body>
        <main class="card">
            <div class="logo">Lenta France</div>
            <div class="subtitle">{subtitle}</div>

            <div class="section">
                <span class="pill">{pill}</span>
            </div>

            <h1>{headline}</h1>
            <p>{desc}</p>

            <div class="section">
                <strong>{choose}</strong>
                <div class="lang-buttons">
                    <a class="btn" href="/set-lang?lang=it">Italiano</a>
                    <a class="btn" href="/set-lang?lang=fr">Français</a>
                </div>
            </div>

            <div class="section">
                <div class="grid">
                    <div class="feature">
                        <div class="feature-title">Cantieri / Chantiers</div>
                        <div>Monitoraggio avanzamento lavori, stato e risorse assegnate.</div>
                    </div>
                    <div class="feature">
                        <div class="feature-title">Fiches & stratigrafie</div>
                        <div>Gestione pali, paratie, profondità, diametri e stratigrafie.</div>
                    </div>
                    <div class="feature">
                        <div class="feature-title">Rapportini / Rapports</div>
                        <div>Presenze, meteo, ore lavorate e attività svolte in cantiere.</div>
                    </div>
                    <div class="feature">
                        <div class="feature-title">Macchinari / Machines</div>
                        <div>Parco mezzi, assegnazioni ai cantieri e segnalazione problemi.</div>
                    </div>
                </div>
            </div>

            <div class="section" style="margin-top: 24px;">
                <a class="btn primary" href="/docs">{area}</a>
                <span style="font-size: 12px; margin-left: 8px; color: #9ca3af;">
                    {api_hint}
                </span>
            </div>

            <div class="footer">
                <div>{foot_addr}</div>
                <div>&copy; {year} Lenta France. {foot_rights}</div>
            </div>
        </main>
    </body>
    </html>
    """.format(
        lang=current_lang,
        title=T["title"],
        subtitle=T["subtitle"],
        headline=T["headline"],
        desc=T["desc"],
        choose=T["choose"],
        pill=T["pill"],
        area=T["area"],
        api_hint=T["api_hint"],
        foot_addr=T["foot_addr"],
        foot_rights=T["foot_rights"],
        year=year,
    )
    return HTMLResponse(content=html)


# =========================
# UTENTI (gestiti dall’admin)
# =========================

@app.post("/utenti", response_model=Utente)
def create_utente_admin(
    payload: UtenteCreateAdmin,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin)),
):
    if payload.lingua not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Lingua non supportata")

    existing = db.query(UtenteDB).filter(UtenteDB.email == str(payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email già registrata")

    user = UtenteDB(
        email=str(payload.email),
        password=payload.password,
        ruolo=payload.ruolo,
        lingua=payload.lingua,
        attivo=payload.attivo,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/utenti", response_model=List[Utente])
def list_utenti(
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin)),
):
    return db.query(UtenteDB).all()


# =========================
# ENDPOINT DI SERVIZIO
# =========================

@app.get("/languages")
def list_languages():
    return {"supported_languages": SUPPORTED_LANGUAGES}


# =========================
# DIPENDENTI
# =========================

@app.post("/dipendenti", response_model=Dipendente)
def create_dipendente(
    payload: DipendenteCreate,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.utente_id:
        user = db.query(UtenteDB).filter(UtenteDB.id == payload.utente_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utente collegato non trovato")

    dip = DipendenteDB(**payload.dict())
    db.add(dip)
    db.commit()
    db.refresh(dip)
    return dip


@app.get("/dipendenti", response_model=List[Dipendente])
def list_dipendenti(
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    return db.query(DipendenteDB).all()


# =========================
# CANTIERI
# =========================

def foreman_cantiere_filter(q, user: UtenteDB):
    if user.ruolo == UserRole.foreman:
        return q.filter(CantiereDB.foreman_user_id == user.id)
    return q


@app.post("/cantieri", response_model=Cantiere)
def create_cantiere(
    payload: CantiereCreate,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.foreman_user_id:
        foreman = (
            db.query(UtenteDB)
            .filter(
                UtenteDB.id == payload.foreman_user_id,
                UtenteDB.ruolo == UserRole.foreman,
            )
            .first()
        )
        if not foreman:
            raise HTTPException(status_code=404, detail="Caposquadra non trovato")

    cant = CantiereDB(**payload.dict())
    db.add(cant)
    db.commit()
    db.refresh(cant)
    return cant


@app.get("/cantieri", response_model=List[Cantiere])
def list_cantieri(
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    q = db.query(CantiereDB)
    q = foreman_cantiere_filter(q, user)
    return q.all()


@app.get("/cantieri/{cantiere_id}", response_model=Cantiere)
def get_cantiere(
    cantiere_id: int,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    q = db.query(CantiereDB).filter(CantiereDB.id == cantiere_id)
    q = foreman_cantiere_filter(q, user)
    cant = q.first()
    if not cant:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    return cant


def ensure_user_can_access_cantiere(user: UtenteDB, cantiere: CantiereDB):
    if user.ruolo == UserRole.foreman and cantiere.foreman_user_id != user.id:
        raise HTTPException(status_code=403, detail="Accesso non consentito a questo cantiere")


# =========================
# FICHES + STRATIGRAFIA
# =========================

@app.post("/fiches", response_model=FicheForage)
def create_fiche(
    payload: FicheForageCreate,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager, UserRole.foreman)),
):
    cant = db.query(CantiereDB).filter(CantiereDB.id == payload.cantiere_id).first()
    if not cant:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    ensure_user_can_access_cantiere(user, cant)

    fiche = FicheForageDB(**payload.dict())
    db.add(fiche)
    db.commit()
    db.refresh(fiche)
    return fiche


@app.get("/fiches", response_model=List[FicheForage])
def list_fiches(
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    q = db.query(FicheForageDB).join(CantiereDB)
    if user.ruolo == UserRole.foreman:
        q = q.filter(CantiereDB.foreman_user_id == user.id)
    return q.all()


@app.post("/fiches/{fiche_id}/strati", response_model=StratigrafiaStrato)
def add_strato(
    fiche_id: int,
    payload: StratigrafiaStratoBase,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager, UserRole.foreman)),
):
    fiche = db.query(FicheForageDB).filter(FicheForageDB.id == fiche_id).first()
    if not fiche:
        raise HTTPException(status_code=404, detail="Fiche non trovata")
    ensure_user_can_access_cantiere(user, fiche.cantiere)

    strato = StratigrafiaStratoDB(
        fiche_id=fiche_id,
        da_m=payload.da_m,
        a_m=payload.a_m,
        descrizione=payload.descrizione,
    )
    db.add(strato)
    db.commit()
    db.refresh(strato)
    return strato


@app.get("/fiches/{fiche_id}/strati", response_model=List[StratigrafiaStrato])
def list_strati(
    fiche_id: int,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    fiche = (
        db.query(FicheForageDB)
        .join(CantiereDB)
        .filter(FicheForageDB.id == fiche_id)
        .first()
    )
    if not fiche:
        raise HTTPException(status_code=404, detail="Fiche non trovata")
    ensure_user_can_access_cantiere(user, fiche.cantiere)

    return (
        db.query(StratigrafiaStratoDB)
        .filter(StratigrafiaStratoDB.fiche_id == fiche_id)
        .all()
    )


# =========================
# RAPPORINI
# =========================

@app.post("/rapportini", response_model=Rapportino)
def create_rapportino(
    payload: RapportinoCreate,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager, UserRole.foreman)),
):
    cant = db.query(CantiereDB).filter(CantiereDB.id == payload.cantiere_id).first()
    if not cant:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    ensure_user_can_access_cantiere(user, cant)

    data_dict = payload.dict()
    if not data_dict.get("creato_da_utente_id"):
        data_dict["creato_da_utente_id"] = user.id

    rap = RapportinoDB(**data_dict)
    db.add(rap)
    db.commit()
    db.refresh(rap)
    return rap


@app.get("/rapportini", response_model=List[Rapportino])
def list_rapportini(
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    q = db.query(RapportinoDB).join(CantiereDB)
    if user.ruolo == UserRole.foreman:
        q = q.filter(CantiereDB.foreman_user_id == user.id)
    return q.all()


@app.post("/rapportini/presenze", response_model=RapportinoPresenza)
def add_presenza(
    payload: RapportinoPresenzaCreate,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager, UserRole.foreman)),
):
    rap = (
        db.query(RapportinoDB)
        .join(CantiereDB)
        .filter(RapportinoDB.id == payload.rapportino_id)
        .first()
    )
    if not rap:
        raise HTTPException(status_code=404, detail="Rapportino non trovato")
    ensure_user_can_access_cantiere(user, rap.cantiere)

    dip = db.query(DipendenteDB).filter(DipendenteDB.id == payload.dipendente_id).first()
    if not dip:
        raise HTTPException(status_code=404, detail="Dipendente non trovato")

    presenza = RapportinoPresenzaDB(**payload.dict())
    db.add(presenza)
    db.commit()
    db.refresh(presenza)
    return presenza


# =========================
# MACCHINARI
# =========================

@app.post("/macchinari", response_model=Macchinario)
def create_macchinario(
    payload: MacchinarioCreate,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.cantiere_id is not None:
        cant = db.query(CantiereDB).filter(CantiereDB.id == payload.cantiere_id).first()
        if not cant:
            raise HTTPException(status_code=404, detail="Cantiere assegnato non trovato")

    mac = MacchinarioDB(**payload.dict())
    db.add(mac)
    db.commit()
    db.refresh(mac)
    return mac


@app.get("/macchinari", response_model=List[Macchinario])
def list_macchinari(
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    q = db.query(MacchinarioDB)
    if user.ruolo == UserRole.foreman:
        q = q.join(CantiereDB).filter(CantiereDB.foreman_user_id == user.id)

    q = q.order_by(MacchinarioDB.ha_problema.desc(), MacchinarioDB.nome_macchinario.asc())
    return q.all()


class MacchinarioProblemaPayload(BaseModel):
    problema: str


@app.post("/macchinari/{macchinario_id}/problema", response_model=Macchinario)
def segnala_problema_macchinario(
    macchinario_id: int,
    payload: MacchinarioProblemaPayload,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager, UserRole.foreman)),
):
    mac = (
        db.query(MacchinarioDB)
        .outerjoin(CantiereDB, MacchinarioDB.cantiere_id == CantiereDB.id)
        .filter(MacchinarioDB.id == macchinario_id)
        .first()
    )
    if not mac:
        raise HTTPException(status_code=404, detail="Macchinario non trovato")

    if user.ruolo == UserRole.foreman and mac.cantiere and mac.cantiere.foreman_user_id != user.id:
        raise HTTPException(status_code=403, detail="Non puoi modificare questo macchinario")

    note_extra = f"\n[Segnalazione {datetime.utcnow().isoformat()}] {payload.problema}"
    mac.note = (mac.note or "") + note_extra
    mac.ha_problema = True    # sale in alto nelle liste
    mac.problema_corrente = payload.problema

    db.add(mac)
    db.commit()
    db.refresh(mac)
    return mac


@app.post("/macchinari/{macchinario_id}/clear-problema", response_model=Macchinario)
def risolvi_problema_macchinario(
    macchinario_id: int,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    mac = db.query(MacchinarioDB).filter(MacchinarioDB.id == macchinario_id).first()
    if not mac:
        raise HTTPException(status_code=404, detail="Macchinario non trovato")

    mac.ha_problema = False
    mac.problema_corrente = None

    db.add(mac)
    db.commit()
    db.refresh(mac)
    return mac


@app.get("/cantieri/{cantiere_id}/macchinari", response_model=List[Macchinario])
def list_macchinari_cantiere(
    cantiere_id: int,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    cant = db.query(CantiereDB).filter(CantiereDB.id == cantiere_id).first()
    if not cant:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    ensure_user_can_access_cantiere(user, cant)

    q = db.query(MacchinarioDB).filter(MacchinarioDB.cantiere_id == cantiere_id)
    q = q.order_by(MacchinarioDB.ha_problema.desc(), MacchinarioDB.nome_macchinario.asc())
    return q.all()


# =========================
# NOTIFICHE
# =========================

@app.post("/notifications", response_model=Notification)
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    user = db.query(UtenteDB).filter(UtenteDB.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    notif = NotificationDB(
        user_id=payload.user_id,
        message=payload.message,
        tipo=payload.tipo,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


@app.get("/notifications/me", response_model=List[Notification])
def my_notifications(
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    notifs = (
        db.query(NotificationDB)
        .filter(NotificationDB.user_id == user.id)
        .order_by(NotificationDB.read.asc(), NotificationDB.created_at.desc())
        .all()
    )
    return notifs


@app.post("/notifications/{notification_id}/read", response_model=Notification)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: UtenteDB = Depends(get_current_user),
):
    notif = db.query(NotificationDB).filter(NotificationDB.id == notification_id).first()
    if not notif or notif.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notifica non trovata")
    notif.read = True
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


@app.post("/notifications/generate-mancanti-oggi", response_model=int)
def generate_missing_today_notifications(
    db: Session = Depends(get_db),
    _: UtenteDB = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    """
    Crea notifiche automatiche per ogni caposquadra
    se OGGI manca un rapportino sul suo cantiere.
    Messaggio nella lingua dell'utente (it/fr).
    """
    today = date.today()
    created = 0

    foremen = (
        db.query(UtenteDB)
        .filter(UtenteDB.ruolo == UserRole.foreman, UtenteDB.attivo == True)
        .all()
    )

    for f in foremen:
        for cant in f.cantieri_foreman:
            existing = (
                db.query(RapportinoDB)
                .filter(RapportinoDB.cantiere_id == cant.id, RapportinoDB.data == today)
                .first()
            )
            if not existing:
                if f.lingua == "fr":
                    msg = (
                        f"Pense à remplir le rapport journalier d'aujourd'hui "
                        f"({today.isoformat()}) pour le chantier '{cant.nome}'."
                    )
                else:
                    msg = (
                        f"Ricorda di compilare il rapportino di oggi "
                        f"({today.isoformat()}) per il cantiere '{cant.nome}'."
                    )

                notif = NotificationDB(
                    user_id=f.id,
                    message=msg,
                    tipo="rapportino",
                )
                db.add(notif)
                created += 1

    db.commit()
    return created
