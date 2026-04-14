ALTER TABLE site_economic_entries ADD COLUMN updated_by_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS ix_site_economic_entries_updated_by_id ON site_economic_entries (updated_by_id);

UPDATE site_economic_entries
SET updated_by_id = created_by_id
WHERE updated_by_id IS NULL;
