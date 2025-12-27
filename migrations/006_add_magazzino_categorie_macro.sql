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
VALUES
    ('Accessori macchinari', 'accessori-macchinari', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('Bulloni', 'bulloni', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('Vari', 'vari', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

UPDATE magazzino_items
SET categoria_id = (
    SELECT id
    FROM magazzino_categorie
    WHERE lower(magazzino_categorie.nome) = (
        CASE
            WHEN lower(magazzino_items.categoria) IN (
                'accessori macchinari',
                'accessori',
                'macchinari'
            ) THEN 'accessori macchinari'
            WHEN lower(magazzino_items.categoria) IN (
                'bulloni',
                'bullone',
                'bulloneria',
                'viti'
            ) THEN 'bulloni'
            WHEN lower(magazzino_items.categoria) IN (
                'vari',
                'varie',
                'misc',
                'altro'
            ) THEN 'vari'
            ELSE NULL
        END
    )
)
WHERE categoria IS NOT NULL;
