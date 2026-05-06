ALTER TABLE personale ADD COLUMN user_id INTEGER REFERENCES users(id);

CREATE UNIQUE INDEX IF NOT EXISTS ix_personale_user_id_unique
    ON personale(user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_personale_email_lower
    ON personale(lower(email))
    WHERE email IS NOT NULL;
