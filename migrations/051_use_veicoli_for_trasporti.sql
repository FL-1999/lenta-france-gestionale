ALTER TABLE veicoli ADD COLUMN visibile_trasporti BOOLEAN NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS trasporti_viaggi_new (
    id INTEGER PRIMARY KEY,
    codice_viaggio VARCHAR(50) NOT NULL UNIQUE,
    data_partenza DATE NOT NULL,
    data_arrivo_prevista DATE,
    autista_id INTEGER REFERENCES users(id),
    mezzo_id INTEGER REFERENCES veicoli(id),
    origine VARCHAR(255) NOT NULL,
    destinazione VARCHAR(255) NOT NULL,
    stato VARCHAR(20) NOT NULL DEFAULT 'programmato',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO trasporti_viaggi_new (
    id,
    codice_viaggio,
    data_partenza,
    data_arrivo_prevista,
    autista_id,
    mezzo_id,
    origine,
    destinazione,
    stato,
    created_at,
    updated_at
)
SELECT
    tv.id,
    tv.codice_viaggio,
    tv.data_partenza,
    tv.data_arrivo_prevista,
    tv.autista_id,
    (
        SELECT v.id
        FROM veicoli v
        LEFT JOIN trasporti_mezzi tm2 ON tm2.id = tv.mezzo_id
        WHERE tm2.id IS NOT NULL
          AND UPPER(v.targa) = UPPER(tm2.targa)
        LIMIT 1
    ) AS mezzo_id,
    tv.origine,
    tv.destinazione,
    tv.stato,
    tv.created_at,
    tv.updated_at
FROM trasporti_viaggi tv;

DROP TABLE trasporti_viaggi;
ALTER TABLE trasporti_viaggi_new RENAME TO trasporti_viaggi;

CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_codice_viaggio ON trasporti_viaggi (codice_viaggio);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_data_partenza ON trasporti_viaggi (data_partenza);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_autista_id ON trasporti_viaggi (autista_id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_mezzo_id ON trasporti_viaggi (mezzo_id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_stato ON trasporti_viaggi (stato);
