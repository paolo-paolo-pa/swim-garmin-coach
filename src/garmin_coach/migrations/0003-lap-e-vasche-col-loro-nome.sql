-- Migrazione 0003 — chiamare le cose col loro nome (D4).
--
-- swim_sets conteneva messaggi FIT 'lap'. Un lap è quello che l'orologio ha
-- segnato; "8×100" è un'interpretazione. Il nome prometteva la seconda cosa e
-- conteneva la prima, e sopra un nome così si costruiscono analisi sbagliate
-- senza accorgersene.
--
--   swim_sets     → activity_laps    (un lap registrato)
--   swim_lengths  → pool_lengths     (una vasca, solo in piscina)
--
-- swim_sets tornerà a esistere il giorno che esisterà il codice che ricostruisce
-- le serie davvero, e conterrà serie. Non prima: una tabella vuota in attesa
-- del futuro è la stessa cosa di una cartella vuota (Regola Aurea n.1, punto 6).
--
-- Nella stessa migrazione si ripara l'altra bugia: source_sha conteneva
-- 'fit://archivio.zip/file.fit', che non è uno SHA. Diventa source_object_id,
-- che è quello che è sempre stato — un riferimento al catalogo.

ALTER TABLE swim_sets RENAME TO activity_laps;
ALTER TABLE swim_lengths RENAME TO pool_lengths;

ALTER TABLE activity_laps RENAME COLUMN set_index TO lap_index;
ALTER TABLE activity_laps RENAME COLUMN source_sha TO source_object_id;

-- Le vasche non conservavano né provenienza né momento di import: erano le
-- uniche righe granulari non risalibili alla sorgente.
ALTER TABLE pool_lengths RENAME COLUMN set_index TO lap_index;
ALTER TABLE pool_lengths ADD COLUMN source_object_id VARCHAR;
ALTER TABLE pool_lengths ADD COLUMN imported_at TIMESTAMP;

-- L'ambiente della seduta viaggia col lap: in mare non ci sono vasche, e una
-- query che confronta passi deve poterlo sapere senza raggiungere activities.
ALTER TABLE activity_laps ADD COLUMN environment VARCHAR;
