INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'macchina_base_cingoli', 'Macchina base cingoli', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'macchina_base_cingoli'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'pala_gommata', 'Pala gommata', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'pala_gommata'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'scavatore', 'Scavatore', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'scavatore'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'gru_cingolata', 'Gru cingolata', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'gru_cingolata'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'kelly_diaframmi', 'Kelly diaframmi', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'kelly_diaframmi'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'macchina_operatrice_diaframmi', 'Macchina operatrice diaframmi', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'macchina_operatrice_diaframmi'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'macchina_operatrice_pali', 'Macchina operatrice pali', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'macchina_operatrice_pali'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'gruppo_elettrogeno', 'Gruppo elettrogeno', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'gruppo_elettrogeno'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'dissabbiatore', 'Dissabbiatore', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'dissabbiatore'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'miscelatore', 'Miscelatore', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'miscelatore'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'pompa_bentonite', 'Pompa bentonite', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'pompa_bentonite'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'pompa_acqua', 'Pompa acqua', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'pompa_acqua'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'saldatrice', 'Saldatrice', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'saldatrice'
);

INSERT INTO machine_types (code, label_it, label_fr, is_active, created_at)
SELECT 'taglia_asfalto', 'Taglia asfalto', NULL, 1, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM machine_types WHERE code = 'taglia_asfalto'
);

UPDATE machine_types
SET is_active = 1
WHERE is_active = 0;
