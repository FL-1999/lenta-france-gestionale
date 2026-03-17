ALTER TABLE attrezzature ADD COLUMN qr_code VARCHAR(50);
UPDATE attrezzature SET qr_code = 'ATT-' || printf('%04d', id) WHERE qr_code IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_attrezzature_qr_code ON attrezzature (qr_code);

CREATE TABLE IF NOT EXISTS trasporto_tappe (
    id INTEGER PRIMARY KEY,
    viaggio_id INTEGER NOT NULL REFERENCES trasporti_viaggi(id) ON DELETE CASCADE,
    ordine INTEGER NOT NULL DEFAULT 1,
    destinazione VARCHAR(255) NOT NULL,
    UNIQUE(viaggio_id, ordine)
);

INSERT INTO trasporto_tappe (viaggio_id, ordine, destinazione)
SELECT id, 1, destinazione FROM trasporti_viaggi
WHERE NOT EXISTS (
    SELECT 1 FROM trasporto_tappe tt WHERE tt.viaggio_id = trasporti_viaggi.id
);

ALTER TABLE trasporto_richiesta_attrezzature ADD COLUMN tappa_id INTEGER REFERENCES trasporto_tappe(id);
UPDATE trasporto_richiesta_attrezzature
SET tappa_id = (
    SELECT tt.id FROM trasporto_tappe tt
    WHERE tt.viaggio_id = trasporto_richiesta_attrezzature.viaggio_id
    ORDER BY tt.ordine ASC LIMIT 1
)
WHERE tappa_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_trasporto_richiesta_attrezzature_tappa_id ON trasporto_richiesta_attrezzature (tappa_id);

ALTER TABLE trasporto_attrezzature_viaggio ADD COLUMN tappa_destinazione_id INTEGER REFERENCES trasporto_tappe(id);
ALTER TABLE trasporto_attrezzature_viaggio ADD COLUMN scaricato BOOLEAN NOT NULL DEFAULT 0;
UPDATE trasporto_attrezzature_viaggio
SET tappa_destinazione_id = (
    SELECT tt.id FROM trasporto_tappe tt
    WHERE tt.viaggio_id = trasporto_attrezzature_viaggio.viaggio_id
    ORDER BY tt.ordine ASC LIMIT 1
)
WHERE tappa_destinazione_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_trasporto_attrezzature_viaggio_tappa_destinazione_id ON trasporto_attrezzature_viaggio (tappa_destinazione_id);
