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


def ensure_model_columns(db_engine, metadatas) -> None:
    """Migrazione leggera e portabile (SQLite + PostgreSQL).

    Per ogni tabella già esistente, confronta le colonne dei modelli con quelle
    reali del database e aggiunge quelle mancanti con ALTER TABLE ADD COLUMN.
    Le colonne nuove vengono sempre aggiunte come NULLABLE (per non fallire su
    tabelle già popolate); l'eventuale server_default viene mantenuto.
    Le tabelle nuove sono gestite da create_all e qui vengono ignorate.
    """
    from sqlalchemy.schema import CreateColumn
    import copy as _copy

    dialect = db_engine.dialect
    inspector = inspect(db_engine)
    try:
        existing_tables = set(inspector.get_table_names())
    except Exception:
        return

    seen_tables: set[str] = set()
    for metadata in metadatas:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables or table.name in seen_tables:
                continue
            seen_tables.add(table.name)
            try:
                existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            except Exception:
                continue
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                # Copia la colonna resa nullable, per un ADD COLUMN sicuro.
                col_copy = column._copy()
                col_copy.nullable = True
                try:
                    col_ddl = str(CreateColumn(col_copy).compile(dialect=dialect))
                    with db_engine.begin() as conn:
                        conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {col_ddl}'))
                    print(f"[migrazione] aggiunta colonna {table.name}.{column.name}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[migrazione] impossibile aggiungere {table.name}.{column.name}: {exc}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    with Session(engine) as session:
        yield session
