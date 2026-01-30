CREATE TABLE IF NOT EXISTS machine_types (
    id INTEGER PRIMARY KEY,
    code VARCHAR(255) NOT NULL UNIQUE,
    label_it VARCHAR(255) NOT NULL,
    label_fr VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO machine_types (code, label_it, label_fr, is_active, created_at)
VALUES
    ('macchina_base_cingoli', 'Macchina base cingoli', NULL, 1, CURRENT_TIMESTAMP),
    ('pala_gommata', 'Pala gommata', NULL, 1, CURRENT_TIMESTAMP),
    ('scavatore', 'Scavatore', NULL, 1, CURRENT_TIMESTAMP),
    ('gru_cingolata', 'Gru cingolata', NULL, 1, CURRENT_TIMESTAMP),
    ('kelly_diaframmi', 'Kelly diaframmi', NULL, 1, CURRENT_TIMESTAMP),
    ('macchina_operatrice_diaframmi', 'Macchina operatrice diaframmi', NULL, 1, CURRENT_TIMESTAMP),
    ('macchina_operatrice_pali', 'Macchina operatrice pali', NULL, 1, CURRENT_TIMESTAMP),
    ('gruppo_elettrogeno', 'Gruppo elettrogeno', NULL, 1, CURRENT_TIMESTAMP),
    ('dissabbiatore', 'Dissabbiatore', NULL, 1, CURRENT_TIMESTAMP),
    ('miscelatore', 'Miscelatore', NULL, 1, CURRENT_TIMESTAMP),
    ('pompa_bentonite', 'Pompa bentonite', NULL, 1, CURRENT_TIMESTAMP),
    ('pompa_acqua', 'Pompa acqua', NULL, 1, CURRENT_TIMESTAMP),
    ('saldatrice', 'Saldatrice', NULL, 1, CURRENT_TIMESTAMP),
    ('taglia_asfalto', 'Taglia asfalto', NULL, 1, CURRENT_TIMESTAMP);
