-- Nullable for legacy records: the application infers their existing type.
-- The startup schema upgrader adds this column automatically when absent.
ALTER TABLE site_coupes ADD COLUMN tipologia_scavo VARCHAR(20);
