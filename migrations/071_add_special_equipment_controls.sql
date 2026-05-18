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
);
CREATE INDEX IF NOT EXISTS ix_site_special_equipment_configs_id ON site_special_equipment_configs (id);
CREATE INDEX IF NOT EXISTS ix_site_special_equipment_configs_site_id ON site_special_equipment_configs (site_id);

ALTER TABLE fiches ADD COLUMN sonic_previsto BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE fiches ADD COLUMN sonic_realizzato BOOLEAN;
ALTER TABLE fiches ADD COLUMN inclinometre_previsto BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE fiches ADD COLUMN inclinometre_realizzato BOOLEAN;
