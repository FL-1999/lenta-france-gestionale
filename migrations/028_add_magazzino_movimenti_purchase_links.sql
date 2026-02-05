ALTER TABLE magazzino_movimenti ADD COLUMN purchase_order_id INTEGER;
ALTER TABLE magazzino_movimenti ADD COLUMN purchase_delivery_id INTEGER;

CREATE INDEX IF NOT EXISTS ix_magazzino_movimenti_purchase_order_id
    ON magazzino_movimenti (purchase_order_id);
CREATE INDEX IF NOT EXISTS ix_magazzino_movimenti_purchase_delivery_id
    ON magazzino_movimenti (purchase_delivery_id);
