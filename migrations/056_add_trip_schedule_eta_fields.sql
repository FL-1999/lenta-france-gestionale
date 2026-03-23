ALTER TABLE trasporti_viaggi ADD COLUMN orario_partenza TIME;
ALTER TABLE trasporti_viaggi ADD COLUMN arrivo_stimato TIME;
ALTER TABLE trasporti_viaggi ADD COLUMN arrivo_stimato_manuale BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE trasporti_viaggi ADD COLUMN durata_stimata_minuti INTEGER;
ALTER TABLE trasporti_viaggi ADD COLUMN materiali_attrezzature TEXT;
ALTER TABLE trasporti_viaggi ADD COLUMN note TEXT;
