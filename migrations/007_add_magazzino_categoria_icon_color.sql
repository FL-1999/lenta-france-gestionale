ALTER TABLE magazzino_categorie
    ADD COLUMN icon VARCHAR(32);

ALTER TABLE magazzino_categorie
    ADD COLUMN color VARCHAR(20);

UPDATE magazzino_categorie
SET icon = COALESCE(icon, '📦'),
    color = COALESCE(color, 'indigo');
