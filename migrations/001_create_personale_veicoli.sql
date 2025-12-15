CREATE TABLE IF NOT EXISTS personale (
    id INTEGER PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    cognome VARCHAR(120) NOT NULL,
    ruolo VARCHAR(120),
    telefono VARCHAR(50),
    email VARCHAR(120),
    note TEXT
);

CREATE TABLE IF NOT EXISTS veicoli (
    id INTEGER PRIMARY KEY,
    marca VARCHAR(120) NOT NULL,
    modello VARCHAR(120) NOT NULL,
    targa VARCHAR(50) NOT NULL UNIQUE,
    anno INTEGER,
    km INTEGER,
    note TEXT
);
