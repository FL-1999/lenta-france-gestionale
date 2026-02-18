ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS contact_name_override VARCHAR(255),
    ADD COLUMN IF NOT EXISTS contact_email_override VARCHAR(255);
