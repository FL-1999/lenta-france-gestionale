CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(100),
    address VARCHAR(255),
    city VARCHAR(120),
    zip_code VARCHAR(20),
    province VARCHAR(120),
    country VARCHAR(120),
    vat_number VARCHAR(100),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE purchase_orders
    ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id);

CREATE INDEX IF NOT EXISTS ix_suppliers_name ON suppliers (name);
CREATE INDEX IF NOT EXISTS ix_suppliers_email ON suppliers (email);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier_id ON purchase_orders (supplier_id);
