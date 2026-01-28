CREATE TABLE IF NOT EXISTS machine_site_assignments (
    id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    site_id INTEGER REFERENCES sites(id),
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    unassigned_at DATETIME,
    location_label VARCHAR(255),
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_machine_site_assignments_machine_id
    ON machine_site_assignments (machine_id);
CREATE INDEX IF NOT EXISTS idx_machine_site_assignments_site_id
    ON machine_site_assignments (site_id);
CREATE INDEX IF NOT EXISTS idx_machine_site_assignments_assigned_at
    ON machine_site_assignments (assigned_at);
