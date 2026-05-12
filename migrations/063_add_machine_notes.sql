CREATE TABLE IF NOT EXISTS machine_notes (
    id INTEGER PRIMARY KEY,
    machine_id INTEGER REFERENCES machines(id),
    attrezzatura_id INTEGER REFERENCES attrezzature(id),
    site_id INTEGER REFERENCES sites(id),
    operator_id INTEGER NOT NULL REFERENCES users(id),
    note_type VARCHAR(50),
    text TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_machine_notes_single_asset CHECK (
        (machine_id IS NOT NULL AND attrezzatura_id IS NULL)
        OR (machine_id IS NULL AND attrezzatura_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_machine_notes_machine_id ON machine_notes(machine_id);
CREATE INDEX IF NOT EXISTS ix_machine_notes_attrezzatura_id ON machine_notes(attrezzatura_id);
CREATE INDEX IF NOT EXISTS ix_machine_notes_site_id ON machine_notes(site_id);
CREATE INDEX IF NOT EXISTS ix_machine_notes_operator_id ON machine_notes(operator_id);
CREATE INDEX IF NOT EXISTS ix_machine_notes_note_type ON machine_notes(note_type);
CREATE INDEX IF NOT EXISTS ix_machine_notes_created_at ON machine_notes(created_at);
