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

USERS_COLUMNS: tuple[str, ...] = ("can_switch_roles BOOLEAN NOT NULL DEFAULT 0",)

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

MAGAZZINO_MOVIMENTI_COLUMNS: tuple[str, ...] = ("deposito_id INTEGER",)

SITE_LABOR_COST_ENTRIES_COLUMNS: tuple[str, ...] = (
    "is_weekend BOOLEAN NOT NULL DEFAULT 0",
    "is_active BOOLEAN NOT NULL DEFAULT 1",
)

SITE_ECONOMIC_ENTRIES_COLUMNS: tuple[str, ...] = (
    "created_at DATETIME",
    "updated_at DATETIME",
    "created_by_id INTEGER",
    "updated_by_id INTEGER",
)
SITES_COLUMNS: tuple[str, ...] = (
    "labor_cost_per_person FLOAT NOT NULL DEFAULT 0",
    "material_unit_prices TEXT",
    "auto_cost_materials_enabled BOOLEAN NOT NULL DEFAULT 1",
    "auto_cost_labor_enabled BOOLEAN NOT NULL DEFAULT 1",
    "manual_material_entries_override_auto BOOLEAN NOT NULL DEFAULT 1",
    "totale_paratie_da_scavare INTEGER",
    "numero_totale_paratie INTEGER",
    "numero_totale_pali INTEGER",
)

NOTIFICATIONS_COLUMNS: tuple[str, ...] = ("is_read BOOLEAN NOT NULL DEFAULT 0",)
PERSONALE_COLUMNS: tuple[str, ...] = ("user_id INTEGER",)
FICHES_COLUMNS: tuple[str, ...] = (
    "quota_ngf_testa FLOAT",
    "quota_ngf_fondo FLOAT",
    "quota_ngf_note TEXT",
    "coupe_id INTEGER",
    "scavo_da_tn BOOLEAN NOT NULL DEFAULT 1",
    "quota_partenza FLOAT",
    "quota_testa_getto FLOAT",
    "capocantiere_id INTEGER",
    "quota_tn FLOAT",
    "responsable_pdf TEXT",
    "type_beton TEXT",
    "type_coulage TEXT NOT NULL DEFAULT 'Gravitaire'",
    "terreno_teorico TEXT",
    "courbe_beton_active BOOLEAN NOT NULL DEFAULT 0",
    "courbe_beton_realisee TEXT",
    "courbe_beton_tube TEXT",
    "courbe_beton_volume_total FLOAT",
    "courbe_beton_hauteur_initiale FLOAT",
    "courbe_beton_hauteur_finale FLOAT DEFAULT 0",
    "sonic_previsto BOOLEAN NOT NULL DEFAULT 0",
    "sonic_realizzato BOOLEAN",
    "inclinometre_previsto BOOLEAN NOT NULL DEFAULT 0",
    "inclinometre_realizzato BOOLEAN",
)

SITE_COUPES_COLUMNS: tuple[str, ...] = (
    "type_beton TEXT",
    "type_coulage TEXT NOT NULL DEFAULT 'Gravitaire'",
    "base_paroi_mecanique FLOAT",
)

UPGRADE_TARGETS: dict[str, tuple[str, ...]] = {
    "veicoli": VEICOLI_COLUMNS,
    "users": USERS_COLUMNS,
    "trasporti_viaggi": TRASPORTI_VIAGGI_COLUMNS,
    "trasporto_tappe": TRASPORTO_TAPPE_COLUMNS,
    "movimenti_attrezzature": MOVIMENTI_ATTREZZATURE_COLUMNS,
    "magazzino_movimenti": MAGAZZINO_MOVIMENTI_COLUMNS,
    "site_labor_cost_entries": SITE_LABOR_COST_ENTRIES_COLUMNS,
    "site_economic_entries": SITE_ECONOMIC_ENTRIES_COLUMNS,
    "sites": SITES_COLUMNS,
    "notifications": NOTIFICATIONS_COLUMNS,
    "personale": PERSONALE_COLUMNS,
    "fiches": FICHES_COLUMNS,
    "site_coupes": SITE_COUPES_COLUMNS,
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


def _ensure_personale_user_link_constraints(connection: Connection) -> None:
    if not _table_exists(connection, "personale"):
        logger.warning("Skipped personale user link indexes: table not found.")
        return

    existing_columns = _read_existing_columns(connection, "personale")
    if "user_id" not in existing_columns:
        logger.warning("Skipped personale user link indexes: user_id column not found.")
        return

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_personale_user_id_unique "
            "ON personale(user_id) WHERE user_id IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_personale_email_lower "
            "ON personale(lower(email)) WHERE email IS NOT NULL"
        )
    )
    logger.info("Ensured personale user/email lookup indexes.")


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


def _ensure_fiche_hours_nullable(connection: Connection) -> None:
    if not _table_exists(connection, "fiches"):
        logger.warning("Skipped fiches.hours nullable migration: table not found.")
        return

    columns = connection.execute(text("PRAGMA table_info(fiches)")).fetchall()
    hours_column = next((row for row in columns if row[1] == "hours"), None)
    if hours_column is None:
        logger.warning("Skipped fiches.hours nullable migration: column not found.")
        return
    if not bool(hours_column[3]):
        logger.info("fiches.hours already nullable.")
        return

    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(
        text(
            """
            CREATE TABLE fiches_nullable_hours (
                id INTEGER PRIMARY KEY,
                date DATE NOT NULL,
                numero_pannello INTEGER NOT NULL,
                site_id INTEGER NOT NULL,
                coupe_id INTEGER,
                machine_id INTEGER,
                created_by_id INTEGER NOT NULL,
                fiche_type VARCHAR(15) NOT NULL,
                description TEXT NOT NULL,
                operator VARCHAR(255),
                hours FLOAT,
                notes TEXT,
                tipologia_scavo VARCHAR(50),
                stratigrafia TEXT,
                materiale VARCHAR(100),
                profondita_totale FLOAT,
                diametro_palo FLOAT,
                larghezza_pannello FLOAT,
                altezza_pannello FLOAT,
                data_getto DATE,
                metri_cubi_gettati FLOAT,
                quota_ngf_testa FLOAT,
                quota_ngf_fondo FLOAT,
                quota_ngf_note TEXT,
                scavo_da_tn BOOLEAN NOT NULL DEFAULT 1,
                quota_partenza FLOAT,
                quota_testa_getto FLOAT,
                capocantiere_id INTEGER,
                quota_tn FLOAT,
                responsable_pdf TEXT,
                type_beton TEXT,
                type_coulage TEXT NOT NULL DEFAULT 'Gravitaire',
                terreno_teorico TEXT,
                courbe_beton_active BOOLEAN NOT NULL DEFAULT 0,
                courbe_beton_realisee TEXT,
                courbe_beton_tube TEXT,
                courbe_beton_volume_total FLOAT,
                courbe_beton_hauteur_initiale FLOAT,
                courbe_beton_hauteur_finale FLOAT DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(site_id) REFERENCES sites(id),
                FOREIGN KEY(coupe_id) REFERENCES site_coupes(id),
                FOREIGN KEY(machine_id) REFERENCES machines(id),
                FOREIGN KEY(created_by_id) REFERENCES users(id)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO fiches_nullable_hours (
                id, date, numero_pannello, site_id, coupe_id, machine_id, created_by_id, fiche_type, description,
                operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
                profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
                data_getto, metri_cubi_gettati, quota_ngf_testa, quota_ngf_fondo,
                quota_ngf_note, scavo_da_tn, quota_partenza, quota_testa_getto, capocantiere_id,
                quota_tn, responsable_pdf, type_beton, type_coulage, terreno_teorico, courbe_beton_active, courbe_beton_realisee, courbe_beton_tube, courbe_beton_volume_total, courbe_beton_hauteur_initiale, courbe_beton_hauteur_finale, created_at, updated_at
            )
            SELECT
                id, date, numero_pannello, site_id, coupe_id, machine_id, created_by_id, fiche_type, description,
                operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
                profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
                data_getto, metri_cubi_gettati, quota_ngf_testa, quota_ngf_fondo,
                quota_ngf_note, scavo_da_tn, quota_partenza, quota_testa_getto, capocantiere_id,
                quota_tn, responsable_pdf, type_beton, type_coulage, terreno_teorico, courbe_beton_active, courbe_beton_realisee, courbe_beton_tube, courbe_beton_volume_total, courbe_beton_hauteur_initiale, courbe_beton_hauteur_finale, created_at, updated_at
            FROM fiches
            """
        )
    )
    connection.execute(text("DROP TABLE fiches"))
    connection.execute(text("ALTER TABLE fiches_nullable_hours RENAME TO fiches"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiches_id ON fiches (id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiches_site_id ON fiches (site_id)"))
    connection.execute(text("PRAGMA foreign_keys=ON"))
    logger.info("Migrated fiches.hours to nullable.")


def _ensure_fiches_unique_per_tipologia(connection: Connection) -> None:
    if not _table_exists(connection, "fiches"):
        logger.warning("Skipped fiches unique migration: table not found.")
        return

    create_sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='fiches'")
    ).scalar() or ""
    if "uq_fiches_site_tipologia_numero_pannello" in create_sql or (
        "tipologia_scavo" in create_sql
        and "numero_pannello" in create_sql
        and "UNIQUE (site_id, tipologia_scavo, numero_pannello)" in create_sql
    ):
        logger.info("fiches unique constraint already separates tipologia_scavo.")
        return

    columns = _read_existing_columns(connection, "fiches")
    required_columns = {
        "id", "date", "numero_pannello", "site_id", "machine_id", "created_by_id",
        "fiche_type", "description", "operator", "hours", "notes", "tipologia_scavo",
        "stratigrafia", "materiale", "profondita_totale", "diametro_palo",
        "larghezza_pannello", "altezza_pannello", "data_getto", "metri_cubi_gettati",
        "created_at", "updated_at",
    }
    if not required_columns.issubset(columns):
        logger.warning("Skipped fiches unique migration: required columns not found.")
        return

    duplicate_rows = connection.execute(
        text(
            """
            SELECT site_id, lower(tipologia_scavo) AS tipologia, numero_pannello, COUNT(*) AS total
            FROM fiches
            WHERE tipologia_scavo IS NOT NULL
            GROUP BY site_id, lower(tipologia_scavo), numero_pannello
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        logger.warning("Skipped fiches unique migration: duplicate type/number rows exist.")
        return

    optional_columns = ["quota_ngf_testa", "quota_ngf_fondo", "quota_ngf_note", "coupe_id", "scavo_da_tn", "quota_partenza", "quota_testa_getto", "capocantiere_id", "quota_tn", "responsable_pdf", "type_beton", "type_coulage", "terreno_teorico", "courbe_beton_active", "courbe_beton_realisee", "courbe_beton_tube", "courbe_beton_volume_total", "courbe_beton_hauteur_initiale", "courbe_beton_hauteur_finale"]
    optional_defaults = {"scavo_da_tn": "1", "type_coulage": "'Gravitaire'", "courbe_beton_active": "0", "courbe_beton_hauteur_finale": "0"}
    select_optional = [
        col if col in columns else f"{optional_defaults.get(col, 'NULL')} AS {col}"
        for col in optional_columns
    ]

    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(
        text(
            """
            CREATE TABLE fiches_tipologia_unique (
                id INTEGER PRIMARY KEY,
                date DATE NOT NULL,
                numero_pannello INTEGER NOT NULL,
                site_id INTEGER NOT NULL,
                coupe_id INTEGER,
                machine_id INTEGER,
                created_by_id INTEGER NOT NULL,
                fiche_type VARCHAR(15) NOT NULL,
                description TEXT NOT NULL,
                operator VARCHAR(255),
                hours FLOAT,
                notes TEXT,
                tipologia_scavo VARCHAR(50),
                stratigrafia TEXT,
                materiale VARCHAR(100),
                profondita_totale FLOAT,
                diametro_palo FLOAT,
                larghezza_pannello FLOAT,
                altezza_pannello FLOAT,
                data_getto DATE,
                metri_cubi_gettati FLOAT,
                quota_ngf_testa FLOAT,
                quota_ngf_fondo FLOAT,
                quota_ngf_note TEXT,
                scavo_da_tn BOOLEAN NOT NULL DEFAULT 1,
                quota_partenza FLOAT,
                quota_testa_getto FLOAT,
                capocantiere_id INTEGER,
                quota_tn FLOAT,
                responsable_pdf TEXT,
                type_beton TEXT,
                type_coulage TEXT NOT NULL DEFAULT 'Gravitaire',
                terreno_teorico TEXT,
                courbe_beton_active BOOLEAN NOT NULL DEFAULT 0,
                courbe_beton_realisee TEXT,
                courbe_beton_tube TEXT,
                courbe_beton_volume_total FLOAT,
                courbe_beton_hauteur_initiale FLOAT,
                courbe_beton_hauteur_finale FLOAT DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_fiches_site_tipologia_numero_pannello UNIQUE (site_id, tipologia_scavo, numero_pannello),
                CONSTRAINT ck_fiches_numero_pannello_positive CHECK (numero_pannello > 0),
                FOREIGN KEY(site_id) REFERENCES sites(id),
                FOREIGN KEY(coupe_id) REFERENCES site_coupes(id),
                FOREIGN KEY(machine_id) REFERENCES machines(id),
                FOREIGN KEY(created_by_id) REFERENCES users(id)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            INSERT INTO fiches_tipologia_unique (
                id, date, numero_pannello, site_id, coupe_id, machine_id, created_by_id, fiche_type,
                description, operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
                profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
                data_getto, metri_cubi_gettati, quota_ngf_testa, quota_ngf_fondo,
                quota_ngf_note, scavo_da_tn, quota_partenza, quota_testa_getto, capocantiere_id,
                quota_tn, responsable_pdf, type_beton, type_coulage, terreno_teorico, courbe_beton_active, courbe_beton_realisee, courbe_beton_tube, courbe_beton_volume_total, courbe_beton_hauteur_initiale, courbe_beton_hauteur_finale, created_at, updated_at
            )
            SELECT
                id, date, numero_pannello, site_id, {select_optional[3]}, machine_id, created_by_id, fiche_type,
                description, operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
                profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
                data_getto, metri_cubi_gettati, {select_optional[0]}, {select_optional[1]},
                {select_optional[2]}, {select_optional[4]}, {select_optional[5]}, {select_optional[6]}, {select_optional[7]},
                {select_optional[8]}, {select_optional[9]}, {select_optional[10]}, {select_optional[11]}, {select_optional[12]}, {select_optional[13]}, {select_optional[14]}, {select_optional[15]}, {select_optional[16]}, {select_optional[17]}, {select_optional[18]}, created_at, updated_at
            FROM fiches
            """
        )
    )
    connection.execute(text("DROP TABLE fiches"))
    connection.execute(text("ALTER TABLE fiches_tipologia_unique RENAME TO fiches"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiches_id ON fiches (id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_fiches_site_id ON fiches (site_id)"))
    connection.execute(text("PRAGMA foreign_keys=ON"))
    logger.info("Migrated fiches unique constraint to include tipologia_scavo.")



def _ensure_site_special_equipment_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS site_special_equipment_configs (
                id INTEGER PRIMARY KEY,
                site_id INTEGER NOT NULL,
                tipologia_scavo VARCHAR(50) NOT NULL,
                numero_elemento INTEGER NOT NULL,
                sonic_previsto BOOLEAN NOT NULL DEFAULT 0,
                inclinometre_previsto BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE,
                CONSTRAINT uq_site_special_equipment_site_tipo_numero UNIQUE (site_id, tipologia_scavo, numero_elemento),
                CONSTRAINT ck_site_special_equipment_numero_positive CHECK (numero_elemento > 0)
            )
            """
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_site_special_equipment_configs_id ON site_special_equipment_configs (id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_site_special_equipment_configs_site_id ON site_special_equipment_configs (site_id)"))

def upgrade_db(engine: Engine) -> None:
    """Run idempotent SQLite schema upgrades for configured tables."""
    with engine.begin() as connection:
        _ensure_site_special_equipment_table(connection)
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
        _ensure_personale_user_link_constraints(connection)
        _ensure_fiche_hours_nullable(connection)
        _ensure_fiches_unique_per_tipologia(connection)


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
