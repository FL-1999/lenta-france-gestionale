from __future__ import annotations

from collections.abc import Iterable
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel
from models.base import Base


UPGRADE_TARGETS: dict[str, tuple[str, ...]] = {
    "veicoli": (
        "anno INTEGER",
        "km INTEGER",
        "carburante TEXT",
        "assicurazione_scadenza DATE",
        "revisione_scadenza DATE",
        "visibile_trasporti INTEGER DEFAULT 1",
        "assegnato_a_id INTEGER",
    ),
}


def safe_add_column(engine: Engine, table_name: str, column_definition: str) -> None:
    """Aggiunge una colonna SQLite solo se non esiste già."""
    column_name = column_definition.strip().split()[0]

    with engine.begin() as connection:
        pragma_query = text(f"PRAGMA table_info({table_name})")
        existing_columns = {
            row[1] for row in connection.execute(pragma_query).fetchall()
        }

        if column_name in existing_columns:
            print(f"Colonna {column_name} già esistente")
            return

        alter_query = text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"
        )
        connection.execute(alter_query)

        print(f"Aggiunta colonna {column_name} a {table_name}")


def upgrade_db(engine: Engine) -> None:
    """Esegue upgrade incrementale del database SQLite."""
    for table_name, column_definitions in UPGRADE_TARGETS.items():
        for column_definition in column_definitions:
            safe_add_column(engine, table_name, column_definition)


def check_db_schema(engine: Engine) -> dict[str, list[str]]:
    """Controlla coerenza schema DB vs modelli in sola lettura."""
    import models  # forza registrazione metadata

    errors: list[str] = []
    warnings: list[str] = []
    model_tables: dict[str, set[str]] = {}

    # raccoglie colonne dai modelli
    for metadata in (Base.metadata, SQLModel.metadata):
        for table_name, table in metadata.tables.items():
            model_tables.setdefault(table_name, set()).update(
                col.name for col in table.columns
            )

    with engine.connect() as connection:
        db_tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

        for table_name, model_columns in sorted(model_tables.items()):
            if table_name.startswith("sqlite_"):
                continue

            if table_name not in db_tables:
                msg = f"MANCANTE tabella {table_name}"
                print(msg)
                errors.append(msg)
                continue

            pragma_rows = connection.execute(
                text(f"PRAGMA table_info({table_name})")
            ).fetchall()

            db_columns = {row[1] for row in pragma_rows}

            # colonne mancanti
            for col in sorted(model_columns):
                if col not in db_columns:
                    msg = f"MANCANTE {table_name}.{col}"
                    print(msg)
                    errors.append(msg)
                else:
                    print(f"OK {table_name}.{col}")

            # colonne extra
            for col in sorted(db_columns - model_columns):
                msg = f"EXTRA {table_name}.{col}"
                print(f"WARNING {msg}")
                warnings.append(msg)

    print("\n--- RISULTATO FINALE ---")

    if errors:
        print("ERRORI:")
        for e in errors:
            print(f"- {e}")

    if warnings:
        print("WARNING:")
        for w in warnings:
            print(f"- {w}")

    if not errors and not warnings:
        print("DATABASE ALLINEATO")

    return {"errors": errors, "warnings": warnings}