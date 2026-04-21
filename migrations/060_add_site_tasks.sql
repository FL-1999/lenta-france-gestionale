CREATE TABLE IF NOT EXISTS site_tasks (
    id INTEGER PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'da_fare',
    priority VARCHAR(20) NOT NULL DEFAULT 'media',
    due_date DATE,
    assigned_to_id INTEGER REFERENCES users(id),
    created_by_id INTEGER NOT NULL REFERENCES users(id),
    updated_by_id INTEGER REFERENCES users(id),
    completed BOOLEAN NOT NULL DEFAULT 0,
    completed_by_id INTEGER REFERENCES users(id),
    completed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_site_tasks_status CHECK (status IN ('da_fare', 'in_corso', 'completato')),
    CONSTRAINT ck_site_tasks_priority CHECK (priority IN ('bassa', 'media', 'alta'))
);

CREATE INDEX IF NOT EXISTS ix_site_tasks_site_id ON site_tasks(site_id);
CREATE INDEX IF NOT EXISTS ix_site_tasks_status ON site_tasks(status);
CREATE INDEX IF NOT EXISTS ix_site_tasks_priority ON site_tasks(priority);
CREATE INDEX IF NOT EXISTS ix_site_tasks_due_date ON site_tasks(due_date);
CREATE INDEX IF NOT EXISTS ix_site_tasks_assigned_to_id ON site_tasks(assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_site_tasks_created_by_id ON site_tasks(created_by_id);
CREATE INDEX IF NOT EXISTS ix_site_tasks_updated_by_id ON site_tasks(updated_by_id);
CREATE INDEX IF NOT EXISTS ix_site_tasks_completed_by_id ON site_tasks(completed_by_id);
