CREATE TABLE IF NOT EXISTS magazzino_macro (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO magazzino_macro (name)
SELECT DISTINCT trim(macro)
FROM magazzino_categorie
WHERE macro IS NOT NULL
  AND trim(macro) <> '';

INSERT OR IGNORE INTO magazzino_macro (name)
VALUES ('Generale');

ALTER TABLE magazzino_categorie
    ADD COLUMN macro_id INTEGER REFERENCES magazzino_macro(id);

UPDATE magazzino_categorie
SET macro_id = (
    SELECT mm.id
    FROM magazzino_macro mm
    WHERE lower(mm.name) = lower(trim(magazzino_categorie.macro))
)
WHERE macro_id IS NULL
  AND macro IS NOT NULL
  AND trim(macro) <> '';

UPDATE magazzino_categorie
SET macro_id = (
    SELECT id FROM magazzino_macro WHERE name = 'Generale'
)
WHERE macro_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_magazzino_categorie_macro_id
    ON magazzino_categorie (macro_id);
