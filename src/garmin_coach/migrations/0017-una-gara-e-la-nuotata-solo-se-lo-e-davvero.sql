-- Una gara e' la nuotata dell'orologio solo se lo e' davvero.
--
-- ## Cosa aveva sbagliato la migrazione 0016
--
-- La 0016 decideva **per giorno**: se quel giorno l'orologio aveva registrato
-- una nuotata, la gara non contava. Sembrava prudente. L'atleta l'ha smontata
-- con un esempio, il 25/08/2026:
--
-- > «Il 23/8 erano due cose diverse: una e' a place04, l'altra e' a place03, non
-- > possono essere mai sovrapposizioni. Inoltre la gara era la mattina,
-- > l'allenamento a place01 il pomeriggio.»
--
-- La gara e' a place04, 2.500 m in 25:35. L'attivita' e' «place03 Open Water
-- Swimming», partita alle [orario], 4.068 m in 1h10'. Cento chilometri e otto ore
-- di distanza: due nuotate diverse, e il criterio per giorno ne contava una.
--
-- Il secondo errore era piu' silenzioso. Il 19/05/2018 ci sono due gare e una
-- sola nuotata registrata; il 18/05/2019 tre gare e una sola. Una nuotata puo'
-- essere al massimo **una** gara: il criterio per giorno le azzerava tutte.
-- L'atleta ha spiegato anche il perche' del fenomeno — «l'orologio era
-- consentito solo in una di queste, mentre nelle altre non lo era».
--
-- ## Cosa lo sostituisce
--
-- Niente deduzioni sul giorno. Una gara e' la nuotata dell'orologio soltanto se
-- qualcuno lo ha stabilito guardando i due dati: luogo, ora, durata. Quel
-- «qualcuno» e' l'atleta, e la sua decisione vive in `coach/correzioni-gare.md`
-- come gia' vive quella sulle attivita' in `coach/correzioni-dati.md`.
--
-- Tre verdetti, gli stessi che l'atleta legge in cima al proprio file:
--
--   `linked`    la gara **e'** quella nuotata: i metri sono gia' contati una
--               volta, la riga di gara non ne aggiunge
--   `separate`  la gara e' una nuotata a se', anche se quel giorno l'orologio
--               ha registrato altro (place04 e place03, lo stesso giorno)
--   `exclude`   la gara non entra nel volume: e' successo qualcosa che la rende
--               non confrontabile, e l'atleta lo dichiara
--
-- Una gara senza verdetto e senza nuotate quel giorno conta: non c'e' niente da
-- decidere. Una gara senza verdetto **con** una nuotata quel giorno e' un caso
-- non ancora esaminato, e il criterio C19 lo fa emergere invece di indovinare.
--
-- ## Perche' una tabella e non due colonne su `races`
--
-- `races` si rifa' dalla sorgente a ogni import: una colonna scritta li' dentro
-- sparirebbe al primo aggiornamento del file della federazione. E' lo stesso
-- motivo per cui le correzioni delle attivita' stanno in `activity_quality` e
-- non dentro `activities`.
--
-- ## La distanza dichiarata dal nome dell'evento non e' una misura
--
-- Tre gare avevano un passo che nessun essere umano nuota: place29 2018
-- dichiarava 1.500 m in 13:54, cioe' 0:55,7 per 100 — il record del mondo sui
-- 1500 e' 14:31. place08 2025 dava 0:42,8 e place04 2026 dava 1:01,4.
--
-- Non e' il tempo a essere sbagliato: e' la distanza, che arriva dal **nome
-- dell'evento** (`distance_source = 'event_field'`) e non da una misura del
-- percorso. Un evento chiamato «3 km» puo' aver ridotto il giro la mattina
-- stessa per il mare mosso.
--
-- `counted_distance_m` porta il numero vero quando l'atleta lo conosce.
-- `distance_is_unknown` copre il caso che un numero non basta a dire: **so che
-- quella distanza e' sbagliata e non so quale sia**. Senza, l'unico modo di
-- correggere sarebbe inventare un numero, e la Regola Aurea n.5 dice che un
-- valore mancante resta mancante.

CREATE TABLE IF NOT EXISTS race_quality (
    race_id              VARCHAR PRIMARY KEY,
    verdict              VARCHAR NOT NULL,  -- linked | separate | exclude
    -- Popolata solo da `linked`: quale nuotata e' questa gara.
    activity_id          BIGINT,
    counted_distance_m   DOUBLE,
    distance_is_unknown  BOOLEAN NOT NULL DEFAULT FALSE,
    reason               VARCHAR NOT NULL,  -- perche': resta con la decisione
    confirmed_on         DATE,
    decided_by           VARCHAR NOT NULL,  -- athlete | automatic
    applied_at           TIMESTAMP NOT NULL
);

-- La vista che decide cosa conta come nuotata. Sostituisce quella della 0016:
-- stessa forma, criterio diverso.
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
    -- La distanza confermata dall'atleta vince su quella del nome dell'evento.
    -- `distance_is_unknown` la riporta a mancante: il giorno resta sconosciuto,
    -- non a zero, e `swim_distance_known_n` dice quante ne avevano una (R5).
    CASE WHEN q.distance_is_unknown THEN NULL
         ELSE coalesce(q.counted_distance_m, CAST(r.distance_m AS DOUBLE))
    END                         AS distance_m,
    r.time_s                    AS duration_s,
    -- Le gare dicono l'ambiente in italiano, le attivita' in inglese. Nel
    -- codice si parla inglese: la vista normalizza qui, una volta, invece di
    -- lasciare a ogni filtro il compito di conoscere due nomi per la stessa cosa.
    'open_water'                AS environment,
    NULL                        AS pool_length_m,
    NULL                        AS avg_swolf,
    NULL                        AS avg_stroke_distance_m,
    NULL                        AS avg_hr_bpm,
    NULL                        AS garmin_training_load,
    NULL                        AS device_id
FROM races r
LEFT JOIN race_quality q ON q.race_id = r.race_id
WHERE r.environment = 'acque libere'
  -- Collegata a una nuotata: quei metri l'orologio li ha gia' contati. Le due
  -- colonne sono due strade per la stessa cosa — `races.activity_id` viene
  -- dalle gare che l'atleta dichiara in `coach/gare-dichiarate.md`,
  -- `race_quality.activity_id` dal file delle correzioni.
  AND r.activity_id IS NULL
  AND (q.activity_id IS NULL OR q.verdict <> 'linked')
  AND coalesce(q.verdict, 'separate') <> 'exclude';
