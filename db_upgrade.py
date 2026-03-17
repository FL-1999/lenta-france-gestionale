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
        "visibile_trasporti BOOLEAN DEFAULT 1",
        "assegnato_a_id INTEGER",
    ),
}


def safe_add_column(engine: Engine, table_name: str, column_definition: str) -> None:
    """Aggiunge una colonna SQLite solo se non esiste già."""
    column_name = column_definition.strip().split()[0]

    with engine.begin() as connection:
        pragma_query = text(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in connection.execute(pragma_query).fetchall()}

        if column_name in existing_columns:
            print(f"Colonna {column_name} già esistente")
            return

        alter_query = text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")
        connection.execute(alter_query)
        print(f"Aggiunta colonna {column_name} a {table_name}")


def upgrade_db(engine: Engine) -> None:
    """Esegue upgrade incrementale del database SQLite."""
    for table_name, column_definitions in UPGRADE_TARGETS.items():
        for column_definition in column_definitions:
            safe_add_column(engine, table_name, column_definition)


def check_db_schema(engine: Engine) -> dict[str, list[str]]:
    """Controlla coerenza schema DB vs modelli SQLAlchemy/SQLModel in sola lettura."""
    import models  # noqa: F401  # assicura registrazione tabelle nei metadata
    errors: list[str] = []
    warnings: list[str] = []

    model_tables: dict[str, set[str]] = {}
    for metadata in (Base.metadata, SQLModel.metadata):
        for table_name, table in metadata.tables.items():
            model_tables.setdefault(table_name, set()).update(col.name for col in table.columns)

    required_tables: Iterable[str] = (
        "veicoli",
        "trasporti_viaggi",
        "trasporto_attrezzature",
        "attrezzature",
    )

    with engine.connect() as connection:
        db_tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

        for required_table in required_tables:
            if required_table not in model_tables:
                print(f"WARNING tabella non presente nei modelli: {required_table}")
                warnings.append(f"tabella non presente nei modelli: {required_table}")

        for table_name, model_columns in sorted(model_tables.items()):
            if table_name.startswith("sqlite_"):
                continue

            if table_name not in db_tables:
                message = f"MANCANTE tabella {table_name}"
                print(message)
                errors.append(message)
                continue

            pragma_rows = connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            db_columns = {row[1] for row in pragma_rows}

            for column_name in sorted(model_columns):
                if column_name in db_columns:
                    print(f"OK {table_name}.{column_name}")
                else:
                    message = f"MANCANTE {table_name}.{column_name}"
                    print(message)
                    errors.append(message)

            for column_name in sorted(db_columns - model_columns):
                message = f"EXTRA {table_name}.{column_name}"
                print(f"WARNING {message}")
                warnings.append(message)

    # Copertura upgrade_db (solo tabelle configurate in UPGRADE_TARGETS)
    for table_name, column_definitions in UPGRADE_TARGETS.items():
        model_columns = model_tables.get(table_name)
        if not model_columns:
            warnings.append(f"upgrade_db: tabella {table_name} non presente nei modelli")
            print(f"WARNING upgrade_db: tabella {table_name} non presente nei modelli")
            continue

        covered_columns = {definition.strip().split()[0] for definition in column_definitions}
        missing_in_upgrade = sorted(model_columns - covered_columns)

        if missing_in_upgrade:
            message = (
                f"upgrade_db non copre tutte le colonne di {table_name}: "
                f"{', '.join(missing_in_upgrade)}"
            )
            warnings.append(message)
            print(f"WARNING {message}")

    print("\n--- RISULTATO FINALE ---")
    if errors:
        print("ERRORI:")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("WARNING:")
        for item in warnings:
            print(f"- {item}")
    if not errors and not warnings:
        print("DATABASE ALLINEATO")

    return {"errors": errors, "warnings": warnings}
