-- Performance indexes for frequent filters on sites, reports, machines, and vehicles.
CREATE INDEX IF NOT EXISTS idx_sites_caposquadra_id ON sites (caposquadra_id);
CREATE INDEX IF NOT EXISTS idx_sites_is_active ON sites (is_active);
CREATE INDEX IF NOT EXISTS idx_sites_status ON sites (status);

CREATE INDEX IF NOT EXISTS idx_reports_site_id ON reports (site_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_by_id ON reports (created_by_id);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports (date);

CREATE INDEX IF NOT EXISTS idx_machines_code ON machines (code);
CREATE INDEX IF NOT EXISTS idx_machines_plate ON machines (plate);
CREATE INDEX IF NOT EXISTS idx_machines_status ON machines (status);

CREATE INDEX IF NOT EXISTS idx_veicoli_targa ON veicoli (targa);
