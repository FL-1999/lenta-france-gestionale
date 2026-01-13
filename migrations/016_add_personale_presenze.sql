CREATE TABLE IF NOT EXISTS personale_presenze (
    id INTEGER PRIMARY KEY,
    personale_id INTEGER NOT NULL,
    date DATE NOT NULL,
    site_id INTEGER,
    status VARCHAR(20) NOT NULL,
    hours REAL,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(personale_id) REFERENCES personale(id),
    FOREIGN KEY(site_id) REFERENCES sites(id),
    UNIQUE(personale_id, date)
);

CREATE INDEX IF NOT EXISTS ix_personale_presenze_personale_id ON personale_presenze (personale_id);
CREATE INDEX IF NOT EXISTS ix_personale_presenze_date ON personale_presenze (date);
CREATE INDEX IF NOT EXISTS ix_personale_presenze_site_id ON personale_presenze (site_id);
