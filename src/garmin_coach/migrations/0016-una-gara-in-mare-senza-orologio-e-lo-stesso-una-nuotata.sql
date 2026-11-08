-- Una gara in mare senza orologio è lo stesso una nuotata.
--
-- ## La domanda dell'atleta
--
-- *«Le gare di Icron sono da contare all'interno delle nuotate anche quando non
-- conteggiate, perché spesso non è consentito l'uso dell'orologio nelle gare in
-- mare, ma sono nuotate a tutti gli effetti. Stesso discorso per quelle
-- registrate da Garmin: sono spesso gare non federali dove l'orologio è
-- consentito. Fine della storia.»* — 24/08/2026.
--
-- Il volume leggeva soltanto `canonical_activities`, cioè soltanto ciò che
-- l'orologio ha scritto. Venticinque gare in acque libere, sessanta chilometri
-- fra il 2016 e il 2026, non esistevano per il coach: nelle settimane in cui
-- l'atleta ha gareggiato davvero, il volume diceva zero.
--
-- ## Il filtro che sembra ovvio è quello sbagliato
--
-- Verrebbe da scrivere `races.activity_id IS NULL` — «le gare che non hanno una
-- nuotata collegata». Quella colonna però non dice se l'orologio c'era: dice se
-- **qualcuno ha collegato** la gara a una seduta. Il criterio C18 ha collegato
-- le cinque gare dichiarate dall'atleta e nessuna delle venticinque di Icron.
--
-- Misurato: nove dei venti giorni di gara hanno già una nuotata Garmin in acque
-- libere. Sommare la riga di gara sopra quella nuotata le conterebbe due volte.
-- Il 23/08/2026 la gara dichiara 2.500 m e l'orologio ne ha segnati 4.068, che
-- contengono già la gara più il riscaldamento: la somma darebbe 6.568 m mai
-- nuotati.
--
-- La domanda giusta è quindi sul **giorno**, non sul collegamento: la gara entra
-- soltanto se quel giorno l'orologio non ha registrato nessuna nuotata.
--
-- ## Cosa costa la regola conservativa
--
-- Scelta dall'atleta il 25/08/2026 fra le tre possibili. Non gonfia mai, e il
-- prezzo va detto: dove l'orologio ha registrato solo una parte della gara,
-- resta la parte registrata. Il 06/10/2019 event02 conta i 6.975 m che
-- l'orologio ha visto prima di fermarsi, non i 10.000 dichiarati. Il 18/05/2019
-- conta 1.500 m mentre le tre gare di quel giorno ne dichiarano 9.200.
--
-- L'alternativa — il maggiore fra i due numeri — avrebbe recuperato quei metri
-- riscrivendo nove giorni di storia con una distanza che nessuna misura
-- sostiene. Un tempo e una distanza dichiarati da un evento non sono una
-- misura dell'atleta, e mescolarli a una misura per farne un massimo li
-- confonde.
--
-- ## Perché una vista e non due query uguali
--
-- La regola sopra è sottile e sta in un punto solo. `daily_status` la usa per
-- il volume del giorno, `analysis/volume.py` per quello del periodo: senza una
-- definizione condivisa le due risposte divergerebbero al primo ritocco, e la
-- Regola Aurea n.8 dice che alla stessa domanda si risponde una volta sola.
--
-- `origin` non è decorativo. Una riga `race` porta metri e minuti dichiarati
-- dall'evento, non misurati: non ha SWOLF, non ha bracciate, non ha battiti e
-- non ha un orologio da nominare in un confronto pluriennale. Chi legge la
-- vista deve poterlo sapere senza chiederlo altrove.
--
-- Tre gare non dichiarano nemmeno la distanza. Restano `NULL`, non zero: il
-- giorno è sconosciuto e `swim_distance_known_n` dice quante nuotate del giorno
-- una distanza ce l'avevano (R5).

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
    -- `races.distance_m` è la distanza dichiarata dall'evento, intera: la
    -- colonna della vista è DOUBLE come quella delle attività perché le due
    -- metà devono restare sommabili senza conversioni sparse nei chiamanti.
    CAST(r.distance_m AS DOUBLE) AS distance_m,
    r.time_s                    AS duration_s,
    -- Le gare dicono l'ambiente in italiano, le attività in inglese. Nel
    -- codice si parla inglese: la vista normalizza qui, una volta, invece di
    -- lasciare a ogni filtro il compito di conoscere due nomi per la stessa
    -- cosa.
    'open_water'                AS environment,
    NULL                        AS pool_length_m,
    NULL                        AS avg_swolf,
    NULL                        AS avg_stroke_distance_m,
    NULL                        AS avg_hr_bpm,
    NULL                        AS garmin_training_load,
    NULL                        AS device_id
FROM races r
WHERE r.environment = 'acque libere'
  AND NOT EXISTS (SELECT 1 FROM canonical_activities a
                  WHERE a.is_swim AND a.activity_date = r.race_date);
