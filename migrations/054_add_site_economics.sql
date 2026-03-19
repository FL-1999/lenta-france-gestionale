CREATE TABLE IF NOT EXISTS site_economic_entries (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    entry_date DATE NOT NULL,
    entry_type VARCHAR(20) NOT NULL,
    category VARCHAR(30) NOT NULL,
    amount FLOAT NOT NULL DEFAULT 0,
    description VARCHAR(255),
    notes TEXT,
    created_by_id INTEGER REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_site_economic_entries_amount_positive CHECK (amount >= 0)
);
CREATE INDEX IF NOT EXISTS ix_site_economic_entries_site_id ON site_economic_entries (site_id);
CREATE INDEX IF NOT EXISTS ix_site_economic_entries_entry_date ON site_economic_entries (entry_date);
CREATE INDEX IF NOT EXISTS ix_site_economic_entries_entry_type ON site_economic_entries (entry_type);
CREATE INDEX IF NOT EXISTS ix_site_economic_entries_category ON site_economic_entries (category);

CREATE TABLE IF NOT EXISTS site_labor_cost_entries (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    worker_count INTEGER NOT NULL DEFAULT 0,
    unit_cost FLOAT NOT NULL DEFAULT 0,
    total_cost FLOAT NOT NULL DEFAULT 0,
    notes TEXT,
    created_by_id INTEGER REFERENCES users(id),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_site_labor_cost_entries_site_work_date UNIQUE (site_id, work_date),
    CONSTRAINT ck_site_labor_cost_entries_worker_count_positive CHECK (worker_count >= 0),
    CONSTRAINT ck_site_labor_cost_entries_unit_cost_positive CHECK (unit_cost >= 0),
    CONSTRAINT ck_site_labor_cost_entries_total_cost_positive CHECK (total_cost >= 0)
);
CREATE INDEX IF NOT EXISTS ix_site_labor_cost_entries_site_id ON site_labor_cost_entries (site_id);
CREATE INDEX IF NOT EXISTS ix_site_labor_cost_entries_work_date ON site_labor_cost_entries (work_date);
