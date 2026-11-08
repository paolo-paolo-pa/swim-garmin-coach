-- Migrazione 0005 — finire il lavoro della 0003 (rilievo A2 del secondo audit
-- della Macro-proposta 4).
--
-- La 0003 ha corretto `source_sha` in `activity_laps`, perche conteneva un URI
-- `fit://archivio.zip/file.fit` e non uno SHA. La correzione si e fermata li,
-- alle tabelle nate dai FIT. Le altre dieci hanno continuato a chiamare
-- `source_sha` una colonna che, per le righe arrivate dal sync, contiene
-- `garmin-connect://activity/12345`.
--
-- Misura del 21 agosto 2026, prima di questa migrazione:
--
--     activities      1.469 sha256 |  39 URI
--     daily_health    3.002 sha256 |  51 URI
--     health_status     272 sha256 |  50 URI
--     sleep           2.938 sha256 |  50 URI
--     import_log        116 sha256 |   2 URI
--
-- 192 righe su un nome che promette un hash. Regola Aurea n.5: «ogni riga
-- canonica risale a una sorgente reale; un URI non viene chiamato hash».
--
-- Il nome giusto e quello gia scelto dalla 0003: `source_object_id`, cioe
-- «il riferimento alla sorgente», qualunque forma abbia. Le due forme lecite
-- restano due e restano distinguibili — un SHA-256 di 64 caratteri per i file
-- dell'export, un URI con schema per le risposte di Garmin — e il criterio di
-- verifica C9 controlla che non ne compaia una terza.

ALTER TABLE activities             RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE body_metrics           RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE daily_health           RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE garmin_readiness       RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE garmin_training_load   RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE garmin_training_status RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE health_status          RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE hr_zones               RENAME COLUMN source_sha TO source_object_id;
ALTER TABLE sleep                  RENAME COLUMN source_sha TO source_object_id;

-- import_log ha la stessa colonna dentro la propria chiave primaria. DuckDB
-- rinomina la colonna e la chiave la segue: non serve ricostruire la tabella.
ALTER TABLE import_log             RENAME COLUMN source_sha TO source_object_id;
