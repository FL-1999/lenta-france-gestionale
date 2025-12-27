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
SELECT
    nome,
    CASE
        WHEN rn = 1 THEN base_slug
        ELSE base_slug || '-' || rn
    END,
    0,
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM (
    SELECT
        categoria AS nome,
        replace(lower(categoria), ' ', '-') AS base_slug,
        row_number() OVER (
            PARTITION BY replace(lower(categoria), ' ', '-')
            ORDER BY categoria
        ) AS rn
    FROM (
        SELECT DISTINCT categoria
        FROM magazzino_items
        WHERE categoria IS NOT NULL
    )
);

INSERT OR IGNORE INTO magazzino_categorie (nome, slug, ordine, attiva, created_at, updated_at)
VALUES ('Vari', 'vari', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

UPDATE magazzino_items
SET categoria_id = (
    SELECT id
    FROM magazzino_categorie
    WHERE lower(magazzino_categorie.nome) = lower(magazzino_items.categoria)
)
WHERE categoria IS NOT NULL;
