CREATE TABLE IF NOT EXISTS depots (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(255) NOT NULL,
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_depots_name ON depots(name);

INSERT INTO depots (name, address, notes)
SELECT 'Depot Nord', 'Zone Industrielle Nord, Lyon', 'Deposito principale per area nord'
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Depot Nord');

INSERT INTO depots (name, address, notes)
SELECT 'Depot Centro', 'Avenue Centrale 45, Paris', 'Deposito di smistamento area centro'
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Depot Centro');

INSERT INTO depots (name, address, notes)
SELECT 'Depot Sud', 'Rue du Port 12, Marseille', 'Deposito principale per area sud'
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Depot Sud');

ALTER TABLE suppliers
    ADD COLUMN legal_name VARCHAR(255);

ALTER TABLE suppliers
    ADD COLUMN contact_name VARCHAR(255);

ALTER TABLE suppliers
    ADD COLUMN contact_email VARCHAR(255);

ALTER TABLE suppliers
    ADD COLUMN contact_phone VARCHAR(100);

UPDATE suppliers
SET legal_name = name
WHERE legal_name IS NULL AND name IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_suppliers_legal_name ON suppliers (legal_name);
CREATE INDEX IF NOT EXISTS ix_suppliers_contact_name ON suppliers (contact_name);
CREATE INDEX IF NOT EXISTS ix_suppliers_contact_email ON suppliers (contact_email);

ALTER TABLE purchase_orders
    ADD COLUMN requester_id INTEGER REFERENCES users(id);

ALTER TABLE purchase_orders
    ADD COLUMN contact_name_override VARCHAR(255);

ALTER TABLE purchase_orders
    ADD COLUMN contact_email_override VARCHAR(255);

ALTER TABLE purchase_orders
    ADD COLUMN email_language VARCHAR(2) CHECK (email_language IN ('IT', 'FR', 'EN'));

UPDATE purchase_orders
SET requester_id = requester_user_id
WHERE requester_id IS NULL AND requester_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_purchase_orders_requester_id ON purchase_orders (requester_id);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_email_language ON purchase_orders (email_language);

ALTER TABLE purchase_deliveries
    ADD COLUMN delivery_type VARCHAR(10) NOT NULL DEFAULT 'SITE' CHECK (delivery_type IN ('SITE', 'DEPOT', 'PICKUP'));

ALTER TABLE purchase_deliveries
    ADD COLUMN delivery_site_id INTEGER REFERENCES sites(id);

ALTER TABLE purchase_deliveries
    ADD COLUMN delivery_depot_id INTEGER REFERENCES depots(id);

UPDATE purchase_deliveries
SET delivery_site_id = (
    SELECT po.site_id
    FROM purchase_orders po
    WHERE po.id = purchase_deliveries.order_id
)
WHERE delivery_site_id IS NULL;

DROP TRIGGER IF EXISTS trg_purchase_deliveries_delivery_scope_insert;
CREATE TRIGGER trg_purchase_deliveries_delivery_scope_insert
BEFORE INSERT ON purchase_deliveries
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.delivery_type = 'SITE' AND NEW.delivery_site_id IS NULL
            THEN RAISE(ABORT, 'delivery_site_id is required when delivery_type=SITE')
        WHEN NEW.delivery_type = 'SITE' AND NEW.delivery_depot_id IS NOT NULL
            THEN RAISE(ABORT, 'delivery_depot_id must be NULL when delivery_type=SITE')
        WHEN NEW.delivery_type = 'DEPOT' AND NEW.delivery_depot_id IS NULL
            THEN RAISE(ABORT, 'delivery_depot_id is required when delivery_type=DEPOT')
        WHEN NEW.delivery_type = 'DEPOT' AND NEW.delivery_site_id IS NOT NULL
            THEN RAISE(ABORT, 'delivery_site_id must be NULL when delivery_type=DEPOT')
        WHEN NEW.delivery_type = 'PICKUP' AND (NEW.delivery_site_id IS NOT NULL OR NEW.delivery_depot_id IS NOT NULL)
            THEN RAISE(ABORT, 'delivery_site_id and delivery_depot_id must be NULL when delivery_type=PICKUP')
    END;
END;

DROP TRIGGER IF EXISTS trg_purchase_deliveries_delivery_scope_update;
CREATE TRIGGER trg_purchase_deliveries_delivery_scope_update
BEFORE UPDATE OF delivery_type, delivery_site_id, delivery_depot_id ON purchase_deliveries
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.delivery_type = 'SITE' AND NEW.delivery_site_id IS NULL
            THEN RAISE(ABORT, 'delivery_site_id is required when delivery_type=SITE')
        WHEN NEW.delivery_type = 'SITE' AND NEW.delivery_depot_id IS NOT NULL
            THEN RAISE(ABORT, 'delivery_depot_id must be NULL when delivery_type=SITE')
        WHEN NEW.delivery_type = 'DEPOT' AND NEW.delivery_depot_id IS NULL
            THEN RAISE(ABORT, 'delivery_depot_id is required when delivery_type=DEPOT')
        WHEN NEW.delivery_type = 'DEPOT' AND NEW.delivery_site_id IS NOT NULL
            THEN RAISE(ABORT, 'delivery_site_id must be NULL when delivery_type=DEPOT')
        WHEN NEW.delivery_type = 'PICKUP' AND (NEW.delivery_site_id IS NOT NULL OR NEW.delivery_depot_id IS NOT NULL)
            THEN RAISE(ABORT, 'delivery_site_id and delivery_depot_id must be NULL when delivery_type=PICKUP')
    END;
END;

CREATE INDEX IF NOT EXISTS ix_purchase_deliveries_delivery_type ON purchase_deliveries (delivery_type);
CREATE INDEX IF NOT EXISTS ix_purchase_deliveries_delivery_site_id ON purchase_deliveries (delivery_site_id);
CREATE INDEX IF NOT EXISTS ix_purchase_deliveries_delivery_depot_id ON purchase_deliveries (delivery_depot_id);
