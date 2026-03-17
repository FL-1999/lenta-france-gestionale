from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, String

from db_upgrade import safe_add_column


_TYPE_MAPPING = {
    Integer: "INTEGER",
    String: "TEXT",
    Boolean: "INTEGER",
    Date: "DATE",
    DateTime: "DATETIME",
}


def _sqlite_type_for_column(column: Column[Any]) -> str:
    """Converte il tipo SQLAlchemy in una dichiarazione SQL SQLite minimale."""
    for sqlalchemy_type, sqlite_type in _TYPE_MAPPING.items():
        if isinstance(column.type, sqlalchemy_type):
            return sqlite_type
    return "TEXT"


def _format_column_definition(column: Column[Any]) -> str:
    sql_type = _sqlite_type_for_column(column)
    default_clause = ""

    if column.server_default is not None:
        rendered_default = str(column.server_default.arg)
        default_clause = f" DEFAULT {rendered_default}"

    return f"{column.name} {sql_type}{default_clause}".strip()


def _read_db_tables(connection: Any) -> set[str]:
    query = text("SELECT name FROM sqlite_master WHERE type='table'")
    return {
        row[0]
        for row in connection.execute(query).fetchall()
        if row[0] and not row[0].startswith("sqlite_")
    }


def _read_db_columns(connection: Any, table_name: str) -> set[str]:
    query = text(f"PRAGMA table_info({table_name})")
    return {row[1] for row in connection.execute(query).fetchall()}


def check_and_suggest_db_upgrade(engine: Engine, Base: Any, auto_fix: bool = False) -> bool:
    """
    Confronta i modelli SQLAlchemy con lo schema SQLite reale.

    - Non modifica il DB quando auto_fix=False
    - Stampa suggerimenti pronti per upgrade_db
    - Restituisce True se il DB è allineato, False altrimenti
    """
    ok_columns: list[str] = []
    missing_columns: list[str] = []
    extra_columns: list[str] = []
    missing_tables: list[str] = []
    suggested_code: list[str] = []

    metadata_tables = Base.metadata.tables

    with engine.connect() as connection:
        db_tables = _read_db_tables(connection)
        model_tables = set(metadata_tables.keys())

        for table_name in sorted(model_tables):
            model_table = metadata_tables[table_name]

            if table_name not in db_tables:
                missing_tables.append(table_name)
                continue

            db_columns = _read_db_columns(connection, table_name)
            model_columns = {column.name: column for column in model_table.columns}

            for column_name, column in sorted(model_columns.items()):
                qualified_name = f"{table_name}.{column_name}"
                if column_name in db_columns:
                    ok_columns.append(qualified_name)
                    continue

                missing_columns.append(qualified_name)
                column_definition = _format_column_definition(column)
                suggestion = (
                    f'safe_add_column(engine, "{table_name}", "{column_definition}")'
                )
                suggested_code.append(suggestion)

                if auto_fix:
                    safe_add_column(engine, table_name, column_definition)

            for column_name in sorted(db_columns):
                if column_name not in model_columns:
                    extra_columns.append(f"{table_name}.{column_name}")

    print("\nOK:")
    for item in ok_columns:
        print(f"✔ {item}")

    print("\nMANCANTI:")
    for item in missing_columns:
        print(f"❌ {item}")

    if missing_tables:
        print("\nTABELLE MANCANTI NEL DB:")
        for table_name in missing_tables:
            print(f"❌ {table_name}")

    print("\nEXTRA DB:")
    for item in extra_columns:
        print(f"⚠ {item}")

    print("\n--- CODICE DA AGGIUNGERE ---")
    for line in suggested_code:
        print(line)

    if not missing_columns and not missing_tables:
        print("\n✅ DATABASE ALLINEATO")
        return True

    print("\n❌ DATABASE NON ALLINEATO")
    return False
