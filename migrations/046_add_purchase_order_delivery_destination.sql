ALTER TABLE purchase_orders
    ADD COLUMN delivery_type VARCHAR(10) NOT NULL DEFAULT 'PICKUP' CHECK (delivery_type IN ('SITE', 'DEPOT', 'PICKUP'));

ALTER TABLE purchase_orders
    ADD COLUMN delivery_site_id INTEGER REFERENCES sites(id);

ALTER TABLE purchase_orders
    ADD COLUMN delivery_depot_id INTEGER REFERENCES depots(id);

UPDATE purchase_orders
SET delivery_type = 'SITE',
    delivery_site_id = site_id,
    delivery_depot_id = NULL
WHERE order_kind = 'closed' AND site_id IS NOT NULL;

UPDATE purchase_orders
SET delivery_type = 'PICKUP',
    delivery_site_id = NULL,
    delivery_depot_id = NULL
WHERE order_kind IS NULL OR order_kind != 'closed' OR site_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_purchase_orders_delivery_type ON purchase_orders (delivery_type);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_delivery_site_id ON purchase_orders (delivery_site_id);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_delivery_depot_id ON purchase_orders (delivery_depot_id);
