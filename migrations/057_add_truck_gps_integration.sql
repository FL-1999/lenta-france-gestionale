ALTER TABLE veicoli
    ADD COLUMN IF NOT EXISTS categoria VARCHAR(50) NOT NULL DEFAULT 'altro',
    ADD COLUMN IF NOT EXISTS gps_device_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS provider_vehicle_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS gps_last_latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS gps_last_longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS gps_last_timestamp TIMESTAMP,
    ADD COLUMN IF NOT EXISTS gps_last_speed_kmh DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS gps_last_status VARCHAR(100);

CREATE INDEX IF NOT EXISTS ix_veicoli_gps_device_id ON veicoli(gps_device_id);
CREATE INDEX IF NOT EXISTS ix_veicoli_provider_vehicle_id ON veicoli(provider_vehicle_id);

CREATE TABLE IF NOT EXISTS vehicle_gps_track_points (
    id SERIAL PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES veicoli(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    speed_kmh DOUBLE PRECISION,
    vehicle_status VARCHAR(100),
    payload JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_vehicle_gps_track_points_vehicle_id ON vehicle_gps_track_points(vehicle_id);
CREATE INDEX IF NOT EXISTS ix_vehicle_gps_track_points_recorded_at ON vehicle_gps_track_points(recorded_at DESC);
