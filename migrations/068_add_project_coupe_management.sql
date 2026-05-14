ALTER TABLE site_coupes ADD COLUMN descrizione_zona TEXT;
ALTER TABLE site_coupes ADD COLUMN scavo_da_tn BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE site_coupes ADD COLUMN quota_partenza_scavo FLOAT;
ALTER TABLE site_coupes ADD COLUMN quota_testa_getto_prevista FLOAT;
ALTER TABLE site_coupes ADD COLUMN larghezza FLOAT;
ALTER TABLE site_coupes ADD COLUMN diametro FLOAT;

CREATE TABLE site_coupe_assignments (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    coupe_id INTEGER NOT NULL REFERENCES site_coupes(id) ON DELETE CASCADE,
    tipologia_scavo VARCHAR(50) NOT NULL,
    numero_elemento INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_site_coupe_assignments_site_tipo_numero UNIQUE (site_id, tipologia_scavo, numero_elemento),
    CONSTRAINT ck_site_coupe_assignments_numero_positive CHECK (numero_elemento > 0)
);
CREATE INDEX ix_site_coupe_assignments_site_id ON site_coupe_assignments(site_id);
CREATE INDEX ix_site_coupe_assignments_coupe_id ON site_coupe_assignments(coupe_id);
CREATE INDEX ix_site_coupe_assignments_id ON site_coupe_assignments(id);
