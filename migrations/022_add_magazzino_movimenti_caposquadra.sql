ALTER TABLE magazzino_movimenti
ADD COLUMN caposquadra_id INTEGER REFERENCES users(id);
