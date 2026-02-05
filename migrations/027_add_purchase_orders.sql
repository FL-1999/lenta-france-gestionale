CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    order_number VARCHAR(50) NOT NULL UNIQUE,
    supplier_name VARCHAR(255),
    order_date DATE,
    requester_user_id INTEGER,
    invoice_number VARCHAR(100),
    file_invoice VARCHAR(255),
    status VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(requester_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    description TEXT,
    qty_ordered FLOAT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES purchase_orders(id)
);

CREATE TABLE IF NOT EXISTS purchase_deliveries (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    delivery_number VARCHAR(100) NOT NULL,
    delivery_date DATE,
    file_delivery VARCHAR(255),
    confirmed BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES purchase_orders(id)
);

CREATE TABLE IF NOT EXISTS purchase_delivery_lines (
    id INTEGER PRIMARY KEY,
    delivery_id INTEGER NOT NULL,
    order_line_id INTEGER NOT NULL,
    qty_delivered FLOAT NOT NULL,
    FOREIGN KEY(delivery_id) REFERENCES purchase_deliveries(id),
    FOREIGN KEY(order_line_id) REFERENCES purchase_order_lines(id)
);

CREATE INDEX IF NOT EXISTS ix_purchase_order_lines_order_id ON purchase_order_lines (order_id);
CREATE INDEX IF NOT EXISTS ix_purchase_deliveries_order_id ON purchase_deliveries (order_id);
CREATE INDEX IF NOT EXISTS ix_purchase_delivery_lines_delivery_id ON purchase_delivery_lines (delivery_id);
CREATE INDEX IF NOT EXISTS ix_purchase_delivery_lines_order_line_id ON purchase_delivery_lines (order_line_id);
