from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./lenta_france.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from models.base import Base


def upgrade_db_schema() -> None:
    """
    Aggiorna in modo idempotente lo schema SQLite per la tabella veicoli,
    aggiungendo solo le colonne mancanti senza perdere dati esistenti.
    """
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
