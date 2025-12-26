CREATE TABLE IF NOT EXISTS magazzino_movimenti (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    quantita FLOAT NOT NULL,
    cantiere_id INTEGER,
    user_id INTEGER,
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(item_id) REFERENCES magazzino_items(id),
    FOREIGN KEY(cantiere_id) REFERENCES sites(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
