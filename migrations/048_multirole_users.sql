-- Multi-role support for users.
ALTER TABLE users ADD COLUMN can_switch_roles BOOLEAN NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    CHECK (name IN ('admin', 'manager', 'caposquadra', 'magazzino', 'driver'))
);

CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, role_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO roles (name, description) VALUES
    ('admin', 'Ruolo admin'),
    ('manager', 'Ruolo manager'),
    ('caposquadra', 'Ruolo caposquadra'),
    ('magazzino', 'Ruolo magazzino'),
    ('driver', 'Ruolo driver');

INSERT OR IGNORE INTO user_roles (user_id, role_id, created_at, updated_at)
SELECT users.id, roles.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM users
JOIN roles ON roles.name = users.role;
