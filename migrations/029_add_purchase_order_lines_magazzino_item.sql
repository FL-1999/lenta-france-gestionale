ALTER TABLE purchase_order_lines
    ADD COLUMN magazzino_item_id INTEGER REFERENCES magazzino_items(id);

CREATE INDEX IF NOT EXISTS ix_purchase_order_lines_magazzino_item_id
    ON purchase_order_lines (magazzino_item_id);

UPDATE purchase_order_lines
SET magazzino_item_id = (
        SELECT id
        FROM magazzino_items
        WHERE lower(trim(codice)) = lower(trim(purchase_order_lines.description))
        LIMIT 1
    )
WHERE magazzino_item_id IS NULL
  AND description IS NOT NULL;

UPDATE purchase_order_lines
SET magazzino_item_id = (
        SELECT id
        FROM magazzino_items
        WHERE lower(trim(nome)) = lower(trim(purchase_order_lines.description))
        LIMIT 1
    )
WHERE magazzino_item_id IS NULL
  AND description IS NOT NULL;
