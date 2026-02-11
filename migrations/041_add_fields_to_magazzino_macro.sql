ALTER TABLE magazzino_macro
    ADD COLUMN ordine INTEGER NOT NULL DEFAULT 0;

ALTER TABLE magazzino_macro
    ADD COLUMN icon VARCHAR(32);

ALTER TABLE magazzino_macro
    ADD COLUMN color VARCHAR(40);
