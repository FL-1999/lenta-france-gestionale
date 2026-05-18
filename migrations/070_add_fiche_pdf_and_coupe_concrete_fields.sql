ALTER TABLE site_coupes ADD COLUMN type_beton VARCHAR(100);
ALTER TABLE site_coupes ADD COLUMN type_coulage VARCHAR(100) NOT NULL DEFAULT 'Gravitaire';
ALTER TABLE fiches ADD COLUMN quota_tn FLOAT;
ALTER TABLE fiches ADD COLUMN responsable_pdf VARCHAR(255);
ALTER TABLE fiches ADD COLUMN type_beton VARCHAR(100);
ALTER TABLE fiches ADD COLUMN type_coulage VARCHAR(100) NOT NULL DEFAULT 'Gravitaire';
ALTER TABLE fiches ADD COLUMN terreno_teorico TEXT;
