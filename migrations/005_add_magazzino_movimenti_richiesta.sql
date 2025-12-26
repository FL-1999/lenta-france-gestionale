ALTER TABLE magazzino_movimenti
ADD COLUMN riferimento_richiesta_id INTEGER REFERENCES magazzino_richieste(id);
