ALTER TABLE magazzino_items
    ADD COLUMN codice VARCHAR(100);

UPDATE magazzino_items
    SET codice = 'ITEM-' || id
    WHERE codice IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_magazzino_items_codice
    ON magazzino_items (codice);

CREATE TABLE magazzino_movimenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    item_id INTEGER NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    quantita FLOAT NOT NULL,
    cantiere_id INTEGER,
    note TEXT,
    creato_da_user_id INTEGER NOT NULL,
    riferimento_richiesta_id INTEGER,
    FOREIGN KEY(item_id) REFERENCES magazzino_items(id),
    FOREIGN KEY(cantiere_id) REFERENCES sites(id),
    FOREIGN KEY(creato_da_user_id) REFERENCES users(id),
    FOREIGN KEY(riferimento_richiesta_id) REFERENCES magazzino_richieste(id)
);

CREATE INDEX IF NOT EXISTS ix_magazzino_movimenti_item_id
    ON magazzino_movimenti (item_id);

CREATE INDEX IF NOT EXISTS ix_magazzino_movimenti_created_at
    ON magazzino_movimenti (created_at);
