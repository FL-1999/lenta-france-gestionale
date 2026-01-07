CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    notification_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    recipient_user_id INTEGER,
    recipient_role VARCHAR(50),
    target_url VARCHAR(255),
    is_read BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(recipient_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_notifications_recipient_user_id ON notifications (recipient_user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_role ON notifications (recipient_role);
CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);
