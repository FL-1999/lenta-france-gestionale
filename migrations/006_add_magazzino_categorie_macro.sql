CREATE TABLE IF NOT EXISTS magazzino_categorie (
    id INTEGER PRIMARY KEY,
    nome VARCHAR(255) NOT NULL UNIQUE,
    slug VARCHAR(255) NOT NULL UNIQUE,
    ordine INTEGER NOT NULL DEFAULT 0,
    attiva BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE magazzino_items
    ADD COLUMN categoria_id INTEGER;

INSERT OR IGNORE INTO magazzino_categorie (nome, slug, ordine, attiva, created_at, updated_at)
SELECT DISTINCT categoria,
    replace(lower(categoria), ' ', '-'),
    0,
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM magazzino_items
WHERE categoria IS NOT NULL;

INSERT OR IGNORE INTO magazzino_categorie (nome, slug, ordine, attiva, created_at, updated_at)
VALUES ('Vari', 'vari', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

UPDATE magazzino_items
SET categoria_id = (
    SELECT id
    FROM magazzino_categorie
    WHERE slug = replace(lower(magazzino_items.categoria), ' ', '-')
)
WHERE categoria IS NOT NULL;
