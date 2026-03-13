CREATE TABLE IF NOT EXISTS trasporti_mezzi (
    id INTEGER PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    targa VARCHAR(20) NOT NULL UNIQUE,
    tipo VARCHAR(100),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attrezzature (
    id INTEGER PRIMARY KEY,
    codice VARCHAR(50) NOT NULL UNIQUE,
    nome VARCHAR(255) NOT NULL,
    tipo VARCHAR(100) NOT NULL,
    stato VARCHAR(20) NOT NULL DEFAULT 'disponibile',
    posizione_attuale VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trasporti_viaggi (
    id INTEGER PRIMARY KEY,
    codice_viaggio VARCHAR(50) NOT NULL UNIQUE,
    data_partenza DATE NOT NULL,
    data_arrivo_prevista DATE,
    autista_id INTEGER REFERENCES users(id),
    mezzo_id INTEGER REFERENCES trasporti_mezzi(id),
    origine VARCHAR(255) NOT NULL,
    destinazione VARCHAR(255) NOT NULL,
    stato VARCHAR(20) NOT NULL DEFAULT 'programmato',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trasporto_richiesta_attrezzature (
    id INTEGER PRIMARY KEY,
    viaggio_id INTEGER NOT NULL REFERENCES trasporti_viaggi(id) ON DELETE CASCADE,
    tipo_attrezzatura VARCHAR(100) NOT NULL,
    quantita INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trasporto_attrezzature_viaggio (
    id INTEGER PRIMARY KEY,
    viaggio_id INTEGER NOT NULL REFERENCES trasporti_viaggi(id) ON DELETE CASCADE,
    attrezzatura_id INTEGER NOT NULL REFERENCES attrezzature(id),
    caricato BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE(viaggio_id, attrezzatura_id)
);

CREATE TABLE IF NOT EXISTS movimenti_attrezzature (
    id INTEGER PRIMARY KEY,
    attrezzatura_id INTEGER NOT NULL REFERENCES attrezzature(id),
    viaggio_id INTEGER NOT NULL REFERENCES trasporti_viaggi(id),
    origine VARCHAR(255) NOT NULL,
    destinazione VARCHAR(255) NOT NULL,
    data DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    autista_id INTEGER REFERENCES users(id)
);

INSERT OR IGNORE INTO trasporti_mezzi (id, nome, targa, tipo) VALUES
    (1, 'Camion 1', 'TR-0001', 'camion'),
    (2, 'Camion gru 2', 'TR-0002', 'camion_gru');

INSERT OR IGNORE INTO attrezzature (id, codice, nome, tipo, stato, posizione_attuale) VALUES
    (1, 'P01', 'Pompa P01', 'pompa', 'disponibile', 'Magazzino'),
    (2, 'P02', 'Pompa P02', 'pompa', 'disponibile', 'Magazzino'),
    (3, 'P03', 'Pompa P03', 'pompa', 'disponibile', 'Magazzino'),
    (4, 'G01', 'Generatore G01', 'generatore', 'disponibile', 'Magazzino'),
    (5, 'G02', 'Generatore G02', 'generatore', 'disponibile', 'Magazzino');
