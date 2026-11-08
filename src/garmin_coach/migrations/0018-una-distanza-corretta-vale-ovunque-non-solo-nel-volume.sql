-- Una distanza corretta vale ovunque, non solo nel volume.
--
-- ## Il difetto
--
-- La migrazione 0017 ha dato all'atleta il modo di correggere la distanza di
-- una gara, e l'ha applicata **solo dentro `counted_swims`**, cioè solo al
-- volume. Tutto il resto — la pagina Gare, i confronti, i record, l'MCP —
-- continuava a leggere `races.distance_m`, cioè il numero sbagliato.
--
-- Il risultato è la peggiore delle situazioni: due superfici che rispondono
-- alla stessa domanda con due numeri diversi. Il 23/08/2026 il volume conta
-- place04 a 1.900 m, e la pagina Gare avrebbe continuato a mostrare 2.500 m con
-- il passo di 1:01,4 per 100 — quello che l'atleta aveva appena dichiarato
-- impossibile. La Regola Aurea n.8 dice che alla stessa domanda si risponde
-- una volta sola.
--
-- ## Cosa fa questa migrazione
--
-- Quello che `canonical_activities` fa da sempre per le attività: una vista
-- che applica le decisioni dell'atleta e che tutto il resto legge al posto
-- della tabella grezza. Stessa forma, stesse tre cose:
--
--   1. la distanza corretta prende il posto di quella dichiarata;
--   2. le gare escluse spariscono, perché una decisione dimenticata in un
--      angolo non è una decisione;
--   3. la correzione **resta visibile** — `distance_corrected`,
--      `declared_distance_m`, `athlete_verdict`, `athlete_reason` — perché
--      altrimenti fra un anno qualcuno scambia il numero giusto per un difetto
--      e lo «ripara».
--
-- `activity_id` si unifica qui. Il collegamento fra una gara e la nuotata che
-- la registra arriva da due strade — `coach/gare-dichiarate.md` lo scrive in
-- `races.activity_id`, `coach/correzioni-gare.md` in `race_quality.activity_id`
-- — e chi legge non deve doverle conoscere entrambe.
--
-- ## Perché `canonical_races` e non direttamente `personal_races`
--
-- `personal_races` scarta staffette, squalifiche e gare senza tempo: sono
-- filtri giusti per leggere una prestazione, sbagliati per contare metri
-- nuotati. Due gare in archivio non hanno un tempo, e una gara senza tempo
-- resta una gara che l'atleta ha nuotato. `counted_swims` legge quindi
-- `canonical_races`, che applica le correzioni e basta.

CREATE OR REPLACE VIEW canonical_races AS
SELECT r.* EXCLUDE (distance_m, activity_id),
       -- `distance_is_unknown` riporta la distanza a mancante: l'atleta sa che
       -- il numero dell'evento è sbagliato e non sa quale sia quello vero.
       -- Mancante è la risposta onesta; inventarlo sarebbe peggio (R5).
       CASE WHEN q.distance_is_unknown THEN NULL
            ELSE coalesce(q.counted_distance_m, CAST(r.distance_m AS DOUBLE))
       END                                            AS distance_m,
       coalesce(r.activity_id, q.activity_id)         AS activity_id,
       CAST(r.distance_m AS DOUBLE)                   AS declared_distance_m,
       q.counted_distance_m IS NOT NULL
           OR coalesce(q.distance_is_unknown, FALSE)  AS distance_corrected,
       q.verdict                                      AS athlete_verdict,
       q.reason                                       AS athlete_reason,
       q.confirmed_on                                 AS athlete_confirmed_on
FROM races r
LEFT JOIN race_quality q ON q.race_id = r.race_id
WHERE coalesce(q.verdict, '') <> 'exclude';

-- Le tre viste di lettura poggiano ora sulla vista canonica invece che sulla
-- tabella grezza. Vanno ricreate tutte e tre: in DuckDB le colonne di una
-- vista si fissano quando la si crea, e senza ricrearle continuerebbero a
-- mostrare lo schema di ieri senza dire perché — è già successo con la 0009 e
-- con la 0011.
CREATE OR REPLACE VIEW personal_races AS
SELECT * FROM canonical_races
WHERE NOT is_relay AND status = 'valid' AND time_s IS NOT NULL;

CREATE OR REPLACE VIEW pool_races AS
SELECT * FROM personal_races
WHERE environment = 'piscina'
  AND distance_source = 'certified_pool'
  AND distance_m IS NOT NULL
  AND stroke IS NOT NULL;

CREATE OR REPLACE VIEW open_water_races AS
SELECT * FROM personal_races
WHERE environment = 'acque libere';

-- `counted_swims` non risolve più la distanza per conto suo: la chiede a
-- `canonical_races`, che è l'unico posto in cui quella regola sta scritta.
CREATE OR REPLACE VIEW counted_swims AS
SELECT
    'garmin'                    AS origin,
    a.session_key               AS unit_key,
    a.activity_date             AS swim_date,
    a.distance_m,
    a.duration_s,
    a.environment,
    a.pool_length_m,
    a.avg_swolf,
    a.avg_stroke_distance_m,
    a.avg_hr_bpm,
    a.garmin_training_load,
    a.device_id
FROM canonical_activities a
WHERE a.is_swim

UNION ALL

SELECT
    'race'                      AS origin,
    r.race_id                   AS unit_key,
    r.race_date                 AS swim_date,
    r.distance_m,
    r.time_s                    AS duration_s,
    -- Le gare dicono l'ambiente in italiano, le attività in inglese. Nel
    -- codice si parla inglese: la vista normalizza qui, una volta, invece di
    -- lasciare a ogni filtro il compito di conoscere due nomi per la stessa cosa.
    'open_water'                AS environment,
    NULL                        AS pool_length_m,
    NULL                        AS avg_swolf,
    NULL                        AS avg_stroke_distance_m,
    NULL                        AS avg_hr_bpm,
    NULL                        AS garmin_training_load,
    NULL                        AS device_id
FROM canonical_races r
WHERE r.environment = 'acque libere'
  -- Collegata a una nuotata: quei metri l'orologio li ha già contati.
  AND r.activity_id IS NULL;
