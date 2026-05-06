-- Notification read-state hardening.
-- Fresh installs define notifications.is_read in 014_add_notifications.sql.
-- Existing SQLite deployments receive the missing is_read column through
-- db_upgrade.NOTIFICATIONS_COLUMNS, because SQLite does not support
-- ALTER TABLE ADD COLUMN IF NOT EXISTS portably.
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_user_id ON notifications (recipient_user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_role ON notifications (recipient_role);
CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);
