from __future__ import annotations

import logging
import re
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import SQLModel

from models import RoleEnum
from models.base import Base

logger = logging.getLogger("lenta_france_gestionale.db_upgrade")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

VEICOLI_COLUMNS: tuple[str, ...] = (
    "id INTEGER",
    "marca TEXT",
    "modello TEXT",
    "targa TEXT",
    "anno INTEGER",
    "km INTEGER",
    "carburante TEXT",
    "assicurazione_scadenza DATE",
    "revisione_scadenza DATE",
    "assegnato_a_id INTEGER",
    "note TEXT",
    "visibile_trasporti INTEGER NOT NULL DEFAULT 0",
)

USERS_COLUMNS: tuple[str, ...] = (
    "can_switch_roles BOOLEAN NOT NULL DEFAULT 0",
)

UPGRADE_TARGETS: dict[str, tuple[str, ...]] = {
    "veicoli": VEICOLI_COLUMNS,
    "users": USERS_COLUMNS,
}


def _validate_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Invalid SQLite identifier: {identifier!r}")
    return identifier


def _table_exists(connection: Connection, table_name: str) -> bool:
    query = text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = :table_name LIMIT 1"
    )
    return connection.execute(query, {"table_name": table_name}).scalar() is not None


def _read_existing_columns(connection: Connection, table_name: str) -> set[str]:
    validated_table_name = _validate_identifier(table_name)
    pragma_query = text(f"PRAGMA table_info({validated_table_name})")
    return {row[1] for row in connection.execute(pragma_query).fetchall()}


def safe_add_column(engine: Engine, table_name: str, column_definition: str) -> bool:
    """Add a SQLite column only when it is missing.

    Returns True when the column is added, False when it already exists or the
    table is not available.
    """
    validated_table_name = _validate_identifier(table_name)
    normalized_definition = " ".join(column_definition.strip().split())
    if not normalized_definition:
        raise ValueError("column_definition cannot be empty")

    column_name = _validate_identifier(normalized_definition.split()[0])

    with engine.begin() as connection:
        if not _table_exists(connection, validated_table_name):
            logger.warning(
                "Skipped schema upgrade for table '%s': table not found.",
                validated_table_name,
            )
            return False

        existing_columns = _read_existing_columns(connection, validated_table_name)
        if column_name in existing_columns:
            logger.debug(
                "Column '%s.%s' already exists, skipping.",
                validated_table_name,
                column_name,
            )
            return False

        alter_query = text(
            f"ALTER TABLE {validated_table_name} ADD COLUMN {normalized_definition}"
        )
        connection.execute(alter_query)
        logger.info("Added missing column '%s.%s'.", validated_table_name, column_name)
        return True


def _seed_roles_table(connection: Connection) -> None:
    if not _table_exists(connection, "roles"):
        logger.warning("Skipped roles seeding: roles table not found.")
        return

    for role in RoleEnum:
        connection.execute(
            text(
                "INSERT OR IGNORE INTO roles (name, description) VALUES (:name, :description)"
            ),
            {
                "name": role.value,
                "description": f"Ruolo {role.value}",
            },
        )


def _backfill_user_roles(connection: Connection) -> None:
    if not _table_exists(connection, "user_roles"):
        logger.warning("Skipped user_roles backfill: user_roles table not found.")
        return
    if not _table_exists(connection, "roles") or not _table_exists(connection, "users"):
        logger.warning("Skipped user_roles backfill: prerequisite tables not found.")
        return

    connection.execute(
        text(
            """
            INSERT OR IGNORE INTO user_roles (user_id, role_id, created_at, updated_at)
            SELECT users.id, roles.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM users
            JOIN roles ON roles.name = users.role
            WHERE users.role IS NOT NULL
            """
        )
    )


def upgrade_db(engine: Engine) -> None:
    """Run idempotent SQLite schema upgrades for configured tables."""
    for table_name, column_definitions in UPGRADE_TARGETS.items():
        added_columns: list[str] = []
        for column_definition in column_definitions:
            if safe_add_column(engine, table_name, column_definition):
                added_columns.append(column_definition.split()[0])

        if added_columns:
            logger.info(
                "SQLite schema upgrade completed for '%s'. Added columns: %s",
                table_name,
                ", ".join(added_columns),
            )
        else:
            logger.info(
                "SQLite schema upgrade for '%s' found no missing columns.",
                table_name,
            )

    with engine.begin() as connection:
        _seed_roles_table(connection)
        _backfill_user_roles(connection)


def check_db_schema(engine: Engine) -> dict[str, list[str]]:
    """Controlla coerenza schema DB vs modelli in sola lettura."""
    import models  # noqa: F401  # forza registrazione metadata

    errors: list[str] = []
    warnings: list[str] = []
    model_tables: dict[str, set[str]] = {}

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
                logger.error(msg)
                errors.append(msg)
                continue

            db_columns = _read_existing_columns(connection, table_name)

            for col in sorted(model_columns):
                if col not in db_columns:
                    msg = f"MANCANTE {table_name}.{col}"
                    logger.error(msg)
                    errors.append(msg)
                else:
                    logger.debug("OK %s.%s", table_name, col)

            for col in sorted(db_columns - model_columns):
                msg = f"EXTRA {table_name}.{col}"
                logger.warning(msg)
                warnings.append(msg)

    if not errors and not warnings:
        logger.info("DATABASE ALLINEATO")

    return {"errors": errors, "warnings": warnings}
