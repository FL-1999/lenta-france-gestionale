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

TRASPORTI_VIAGGI_COLUMNS: tuple[str, ...] = (
    "origine_site_id INTEGER",
    "origine_depot_id INTEGER",
    "destinazione_site_id INTEGER",
    "destinazione_depot_id INTEGER",
    "orario_partenza TIME",
    "arrivo_stimato TIME",
    "arrivo_stimato_manuale BOOLEAN NOT NULL DEFAULT 0",
    "durata_stimata_minuti INTEGER",
    "materiali_attrezzature TEXT",
    "note TEXT",
)

TRASPORTO_TAPPE_COLUMNS: tuple[str, ...] = (
    "site_id INTEGER",
    "depot_id INTEGER",
)

MOVIMENTI_ATTREZZATURE_COLUMNS: tuple[str, ...] = (
    "origine_site_id INTEGER",
    "origine_depot_id INTEGER",
    "destinazione_site_id INTEGER",
    "destinazione_depot_id INTEGER",
)

MAGAZZINO_MOVIMENTI_COLUMNS: tuple[str, ...] = (
    "deposito_id INTEGER",
)

SITE_LABOR_COST_ENTRIES_COLUMNS: tuple[str, ...] = (
    "is_weekend BOOLEAN NOT NULL DEFAULT 0",
    "is_active BOOLEAN NOT NULL DEFAULT 1",
)

UPGRADE_TARGETS: dict[str, tuple[str, ...]] = {
    "veicoli": VEICOLI_COLUMNS,
    "users": USERS_COLUMNS,
    "trasporti_viaggi": TRASPORTI_VIAGGI_COLUMNS,
    "trasporto_tappe": TRASPORTO_TAPPE_COLUMNS,
    "movimenti_attrezzature": MOVIMENTI_ATTREZZATURE_COLUMNS,
    "magazzino_movimenti": MAGAZZINO_MOVIMENTI_COLUMNS,
    "site_labor_cost_entries": SITE_LABOR_COST_ENTRIES_COLUMNS,
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


def _migrate_legacy_roles(connection: Connection) -> None:
    legacy_roles = ("contabilita", "hr")
    if not _table_exists(connection, "users") or not _table_exists(connection, "roles"):
        logger.warning("Skipped legacy role migration: prerequisite tables not found.")
        return

    connection.execute(
        text(
            """
            UPDATE users
            SET role = 'manager'
            WHERE role IN ('contabilita', 'hr')
            """
        )
    )

    if _table_exists(connection, "user_roles"):
        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO user_roles (user_id, role_id, created_at, updated_at)
                SELECT DISTINCT ur.user_id, manager_role.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM user_roles ur
                JOIN roles legacy_role ON legacy_role.id = ur.role_id
                JOIN roles manager_role ON manager_role.name = 'manager'
                WHERE legacy_role.name IN ('contabilita', 'hr')
                """
            )
        )
        connection.execute(
            text(
                """
                DELETE FROM user_roles
                WHERE role_id IN (
                    SELECT id FROM roles WHERE name IN ('contabilita', 'hr')
                )
                """
            )
        )

    connection.execute(
        text(
            """
            DELETE FROM roles
            WHERE name IN ('contabilita', 'hr')
            """
        )
    )
    logger.info("Legacy roles migrated to 'manager': %s", ", ".join(legacy_roles))


def _backfill_site_labor_weekend_flags(connection: Connection) -> None:
    if not _table_exists(connection, "site_labor_cost_entries"):
        logger.warning("Skipped site_labor_cost_entries backfill: table not found.")
        return

    existing_columns = _read_existing_columns(connection, "site_labor_cost_entries")
    if not {"work_date", "is_weekend", "is_active"}.issubset(existing_columns):
        logger.warning(
            "Skipped site_labor_cost_entries backfill: required columns not found."
        )
        return

    connection.execute(
        text(
            """
            UPDATE site_labor_cost_entries
            SET
                is_weekend = CASE
                    WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 1
                    ELSE 0
                END,
                is_active = CASE
                    WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 0
                    ELSE 1
                END,
                total_cost = CASE
                    WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 0
                    ELSE COALESCE(worker_count, 0) * COALESCE(unit_cost, 0)
                END
            """
        )
    )
    logger.info("Backfilled weekend flags for site_labor_cost_entries.")


def upgrade_db(engine: Engine) -> None:
    """Run idempotent SQLite schema upgrades for configured tables."""
    site_labor_columns_added = False
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

        if table_name == "site_labor_cost_entries" and added_columns:
            site_labor_columns_added = True

    with engine.begin() as connection:
        if site_labor_columns_added:
            _backfill_site_labor_weekend_flags(connection)
        _seed_roles_table(connection)
        _migrate_legacy_roles(connection)
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
