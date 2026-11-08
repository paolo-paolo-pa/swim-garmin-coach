-- Migrazione 0002 — da dove viene ogni riga (D2).
--
-- Finora la provenienza era una stringa dentro ogni tabella: a volte uno
-- SHA-256, a volte un URI travestito da SHA. Due tabelle la rendono una cosa
-- sola, con un nome che non mente.
--
-- source_objects descrive la COSA da cui si legge: un file dell'export, un
-- membro di uno ZIP, una risposta salvata di Garmin Connect.
-- ingest_runs descrive l'ATTO di leggerla: quando, con quale versione, con
-- che esito.
--
-- Non replicano il contenuto: lo indicizzano. Il payload resta dov'è.

CREATE TABLE IF NOT EXISTS source_objects (
    source_object_id  VARCHAR PRIMARY KEY,  -- sha256 + posizione: stabile fra i rebuild
    kind              VARCHAR NOT NULL,     -- export_json | fit | garmin_connect
    locator           VARCHAR NOT NULL,     -- percorso relativo alla radice, o URI locale
    sha256            VARCHAR NOT NULL,     -- SHA-256 vero del contenuto, mai un URI
    size_bytes        BIGINT,
    observed_at       TIMESTAMP NOT NULL,   -- quando l'abbiamo vista, non quando è nata
    parser            VARCHAR,              -- chi la sa leggere
    parser_version    VARCHAR
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id            VARCHAR PRIMARY KEY,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP,
    command           VARCHAR NOT NULL,     -- ingest | sync | details | rebuild
    code_version      VARCHAR,              -- commit git, quando disponibile
    outcome           VARCHAR,              -- ok | failed | partial
    rows_written      BIGINT DEFAULT 0,
    sources_read      BIGINT DEFAULT 0,
    note              VARCHAR
);
