ALTER TABLE suppliers
    ADD COLUMN IF NOT EXISTS contact_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255);

ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS supplier_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS supplier_phone VARCHAR(100),
    ADD COLUMN IF NOT EXISTS contact_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(255);

CREATE TABLE IF NOT EXISTS depots (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    address VARCHAR(255),
    city VARCHAR(120),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO depots (name, address, city, is_active)
VALUES
    ('Deposito Nord', 'Via del Commercio 12', 'Lille', TRUE),
    ('Deposito Centrale', 'Rue des Artisans 8', 'Paris', TRUE),
    ('Deposito Sud', 'Avenue du Port 21', 'Marseille', TRUE)
ON CONFLICT (name) DO NOTHING;
