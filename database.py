import os

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

# In produzione (Render) si usa un database esterno persistente via
# DATABASE_URL (es. PostgreSQL su Neon/Supabase) così i dati NON si perdono
# ad ogni deploy. In locale, senza DATABASE_URL, si usa SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lenta_france.db")

# Alcuni provider forniscono l'URL come postgres:// (vecchio schema):
# SQLAlchemy vuole postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_IS_SQLITE = DATABASE_URL.startswith("sqlite")

if _IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping evita connessioni morte; pool_recycle rinnova periodicamente.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)


def is_sqlite() -> bool:
    """True se il database attivo è SQLite (per saltare le migrazioni
    specifiche SQLite quando si usa Postgres)."""
    return engine.dialect.name == "sqlite"


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from models.base import Base


def upgrade_db_schema() -> None:
    """
    Aggiorna in modo idempotente lo schema SQLite per la tabella veicoli,
    aggiungendo solo le colonne mancanti senza perdere dati esistenti.
    """
    if not _IS_SQLITE:
        # Su Postgres lo schema completo è creato da create_all: niente ALTER.
        return

    veicoli_columns = {
        "anno": "INTEGER",
        "km": "INTEGER",
        "carburante": "VARCHAR(50)",
        "assicurazione_scadenza": "DATE",
        "revisione_scadenza": "DATE",
        "visibile_trasporti": "BOOLEAN NOT NULL DEFAULT 0",
    }

    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        if "veicoli" not in existing_tables:
            return

        existing_columns = {
            column["name"] for column in inspector.get_columns("veicoli")
        }

        for column_name, column_sql_type in veicoli_columns.items():
            if column_name in existing_columns:
                continue

            statement = text(
                f"ALTER TABLE veicoli ADD COLUMN {column_name} {column_sql_type}"
            )
            connection.execute(statement)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    with Session(engine) as session:
        yield session
