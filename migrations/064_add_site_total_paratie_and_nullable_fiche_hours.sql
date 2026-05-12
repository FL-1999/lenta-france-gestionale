ALTER TABLE sites ADD COLUMN totale_paratie_da_scavare INTEGER;

PRAGMA foreign_keys=off;

CREATE TABLE fiches_new (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    site_id INTEGER NOT NULL,
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
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(site_id) REFERENCES sites(id),
    FOREIGN KEY(machine_id) REFERENCES machines(id),
    FOREIGN KEY(created_by_id) REFERENCES users(id)
);

INSERT INTO fiches_new (
    id, date, site_id, machine_id, created_by_id, fiche_type, description,
    operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
    profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
    data_getto, metri_cubi_gettati, created_at, updated_at
)
SELECT
    id, date, site_id, machine_id, created_by_id, fiche_type, description,
    operator, hours, notes, tipologia_scavo, stratigrafia, materiale,
    profondita_totale, diametro_palo, larghezza_pannello, altezza_pannello,
    data_getto, metri_cubi_gettati, created_at, updated_at
FROM fiches;

DROP TABLE fiches;
ALTER TABLE fiches_new RENAME TO fiches;

CREATE INDEX IF NOT EXISTS ix_fiches_id ON fiches (id);
CREATE INDEX IF NOT EXISTS ix_fiches_site_id ON fiches (site_id);

PRAGMA foreign_keys=on;
