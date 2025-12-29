ALTER TABLE magazzino_richieste
ADD COLUMN priorita VARCHAR(10) NOT NULL DEFAULT 'MED';

ALTER TABLE magazzino_richieste
ADD COLUMN data_necessaria DATE;
