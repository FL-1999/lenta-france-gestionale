ALTER TABLE magazzino_movimenti ADD COLUMN deposito_id INTEGER REFERENCES depots(id);
CREATE INDEX IF NOT EXISTS ix_magazzino_movimenti_deposito_id ON magazzino_movimenti (deposito_id);

ALTER TABLE trasporti_viaggi ADD COLUMN origine_site_id INTEGER REFERENCES sites(id);
ALTER TABLE trasporti_viaggi ADD COLUMN origine_depot_id INTEGER REFERENCES depots(id);
ALTER TABLE trasporti_viaggi ADD COLUMN destinazione_site_id INTEGER REFERENCES sites(id);
ALTER TABLE trasporti_viaggi ADD COLUMN destinazione_depot_id INTEGER REFERENCES depots(id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_origine_site_id ON trasporti_viaggi (origine_site_id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_origine_depot_id ON trasporti_viaggi (origine_depot_id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_destinazione_site_id ON trasporti_viaggi (destinazione_site_id);
CREATE INDEX IF NOT EXISTS ix_trasporti_viaggi_destinazione_depot_id ON trasporti_viaggi (destinazione_depot_id);

ALTER TABLE trasporto_tappe ADD COLUMN site_id INTEGER REFERENCES sites(id);
ALTER TABLE trasporto_tappe ADD COLUMN depot_id INTEGER REFERENCES depots(id);
CREATE INDEX IF NOT EXISTS ix_trasporto_tappe_site_id ON trasporto_tappe (site_id);
CREATE INDEX IF NOT EXISTS ix_trasporto_tappe_depot_id ON trasporto_tappe (depot_id);

ALTER TABLE movimenti_attrezzature ADD COLUMN origine_site_id INTEGER REFERENCES sites(id);
ALTER TABLE movimenti_attrezzature ADD COLUMN origine_depot_id INTEGER REFERENCES depots(id);
ALTER TABLE movimenti_attrezzature ADD COLUMN destinazione_site_id INTEGER REFERENCES sites(id);
ALTER TABLE movimenti_attrezzature ADD COLUMN destinazione_depot_id INTEGER REFERENCES depots(id);
CREATE INDEX IF NOT EXISTS ix_movimenti_attrezzature_origine_site_id ON movimenti_attrezzature (origine_site_id);
CREATE INDEX IF NOT EXISTS ix_movimenti_attrezzature_origine_depot_id ON movimenti_attrezzature (origine_depot_id);
CREATE INDEX IF NOT EXISTS ix_movimenti_attrezzature_destinazione_site_id ON movimenti_attrezzature (destinazione_site_id);
CREATE INDEX IF NOT EXISTS ix_movimenti_attrezzature_destinazione_depot_id ON movimenti_attrezzature (destinazione_depot_id);
