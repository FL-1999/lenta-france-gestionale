-- Applied automatically by ensure_model_columns at application startup.
-- Manual alternative, once only, for installations using SQL migrations.
ALTER TABLE site_plans ADD COLUMN removed_at TIMESTAMP NULL;
