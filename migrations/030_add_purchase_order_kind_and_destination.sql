ALTER TABLE purchase_orders
    ADD COLUMN description TEXT;

ALTER TABLE purchase_orders
    ADD COLUMN order_kind VARCHAR(20) NOT NULL DEFAULT 'warehouse';

ALTER TABLE purchase_orders
    ADD COLUMN site_id INTEGER REFERENCES sites(id);

ALTER TABLE purchase_orders
    ADD COLUMN warehouse_category_id INTEGER REFERENCES magazzino_categorie(id);

ALTER TABLE magazzino_categorie
    ADD COLUMN macro VARCHAR(120) NOT NULL DEFAULT 'Generale';

UPDATE magazzino_categorie
SET macro = 'Generale'
WHERE macro IS NULL OR trim(macro) = '';

CREATE INDEX IF NOT EXISTS ix_purchase_orders_site_id ON purchase_orders (site_id);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_warehouse_category_id ON purchase_orders (warehouse_category_id);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_order_kind ON purchase_orders (order_kind);
