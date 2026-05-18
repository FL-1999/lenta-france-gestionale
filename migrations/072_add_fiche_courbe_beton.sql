ALTER TABLE fiches ADD COLUMN courbe_beton_active BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE fiches ADD COLUMN courbe_beton_realisee TEXT;
ALTER TABLE fiches ADD COLUMN courbe_beton_tube TEXT;
ALTER TABLE fiches ADD COLUMN courbe_beton_volume_total FLOAT;
ALTER TABLE fiches ADD COLUMN courbe_beton_hauteur_initiale FLOAT;
ALTER TABLE fiches ADD COLUMN courbe_beton_hauteur_finale FLOAT DEFAULT 0;
