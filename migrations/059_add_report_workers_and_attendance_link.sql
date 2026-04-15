CREATE TABLE IF NOT EXISTS report_workers (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    personale_id INTEGER NOT NULL REFERENCES personale(id),
    site_id INTEGER REFERENCES sites(id),
    attendance_date DATE NOT NULL,
    role_label VARCHAR(120),
    note TEXT,
    hours_worked FLOAT NOT NULL DEFAULT 8.0,
    day_type VARCHAR(20) NOT NULL DEFAULT 'FULL',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_report_workers_report_personale UNIQUE (report_id, personale_id),
    CONSTRAINT ck_report_workers_hours_worked_non_negative CHECK (hours_worked >= 0)
);

CREATE INDEX IF NOT EXISTS ix_report_workers_report_id ON report_workers(report_id);
CREATE INDEX IF NOT EXISTS ix_report_workers_personale_id ON report_workers(personale_id);
CREATE INDEX IF NOT EXISTS ix_report_workers_attendance_date ON report_workers(attendance_date);
CREATE INDEX IF NOT EXISTS ix_report_workers_site_id ON report_workers(site_id);

ALTER TABLE personale_presenze ADD COLUMN report_id INTEGER REFERENCES reports(id);
CREATE INDEX IF NOT EXISTS ix_personale_presenze_report_id ON personale_presenze(report_id);
