from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def safe_add_column(engine: Engine, table_name: str, column_definition: str) -> None:
    """Aggiunge una colonna SQLite solo se non esiste già."""
    column_name = column_definition.strip().split()[0]

    with engine.begin() as connection:
        pragma_query = text(f"PRAGMA table_info({table_name})")
        existing_columns = {
            row[1]
            for row in connection.execute(pragma_query).fetchall()
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
    safe_add_column(engine, "veicoli", "anno INTEGER")
    safe_add_column(engine, "veicoli", "km INTEGER")
    safe_add_column(engine, "veicoli", "carburante TEXT")
    safe_add_column(engine, "veicoli", "assicurazione_scadenza DATE")
    safe_add_column(engine, "veicoli", "revisione_scadenza DATE")
    safe_add_column(engine, "veicoli", "visibile_trasporti INTEGER DEFAULT 1")
    safe_add_column(engine, "veicoli", "assegnato_a_id INTEGER")
