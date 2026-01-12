ALTER TABLE sites ADD COLUMN cordoli_total_m FLOAT;
ALTER TABLE sites ADD COLUMN cordoli_done_m FLOAT;
ALTER TABLE sites ADD COLUMN paratie_total_panels INTEGER;
ALTER TABLE sites ADD COLUMN paratie_done_panels INTEGER;
ALTER TABLE sites ADD COLUMN strut_levels_count INTEGER;

CREATE TABLE IF NOT EXISTS site_strut_levels (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL,
    level_index INTEGER NOT NULL,
    level_quota VARCHAR(50),
    total_struts_level INTEGER NOT NULL DEFAULT 0,
    done_struts_level INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE,
    UNIQUE(site_id, level_index)
);

CREATE INDEX IF NOT EXISTS ix_site_strut_levels_site_id ON site_strut_levels (site_id);
