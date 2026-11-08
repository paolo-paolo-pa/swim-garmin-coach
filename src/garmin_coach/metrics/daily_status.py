"""Costruzione di ``daily_status``: una riga per giorno, tutto già calcolato.

È la tabella che il coach legge per rispondere a "come sto oggi". Una sola riga
contiene recupero, carico, volume, tecnica e copertura del dato, così che il
briefing non debba interrogare sei tabelle e non sprechi contesto.

Ogni colonna è documentata in ``catalog.py``. Le finestre mobili escludono il
giorno corrente quando calcolano una baseline (altrimenti il valore di oggi
sposterebbe il proprio riferimento) e lo includono quando calcolano un carico
accumulato.
"""

from __future__ import annotations

import duckdb

# Numero minimo di giorni con dato perché una baseline a 28 giorni sia
# pubblicabile. Sotto questa soglia la risposta corretta è "non lo so ancora".
MIN_DAYS_FOR_BASELINE = 14

# Numero minimo di giorni della finestra a 28 che devono ricadere nel periodo in
# cui Garmin registra il carico. Con meno di tre settimane su quattro il
# denominatore del rapporto è troppo instabile per essere pubblicato.
MIN_DAYS_FOR_ACWR = 21

# Numero minimo di giorni **con allenamento** nelle quattro settimane.
#
# La soglia sopra non bastava, e per un motivo che si vede solo misurando:
# dentro l'epoca del carico ogni giorno di calendario è osservato, quindi
# `load_days_28` vale sempre 28 e non impedisce niente. Sull'archivio vero,
# 1.828 giorni pubblicavano un ACWR e novantotto di questi avevano **meno di
# cinque** giorni di allenamento nelle quattro settimane; il minimo osservato
# era uno.
#
# Il denominatore cronico di tre sedute in un mese non descrive un carico
# cronico: descrive tre sedute. Otto giorni sono due allenamenti a settimana per
# quattro settimane — la soglia più bassa a cui la parola «cronico» significa
# ancora qualcosa. È una scelta, non una misura, e va guardata dall'auditor.
MIN_TRAINING_DAYS_FOR_ACWR = 8

BUILD = f"""
CREATE OR REPLACE TABLE daily_status AS
WITH
-- Le gare in mare che l'orologio non ha registrato.
--
-- «Le gare di Icron sono da contare all'interno delle nuotate anche quando non
-- conteggiate, perché spesso non è consentito l'uso dell'orologio nelle gare in
-- mare, ma sono nuotate a tutti gli effetti» — l'atleta, 24/08/2026. Venticinque
-- gare in acque libere per 60 km, che il volume non vedeva perché lo leggeva
-- solo da `canonical_activities`, cioè solo da ciò che l'orologio ha scritto.
--
-- Quali gare contano lo decide la vista `counted_swims`, che è l'unico posto in
-- cui quella regola sta scritta: il volume del giorno e quello del periodo
-- (`analysis/volume.py`) leggono la stessa definizione. La regola in breve — la
-- gara entra soltanto se quel giorno l'orologio non ha registrato nessuna
-- nuotata — e il perché non basti `races.activity_id IS NULL` stanno nella
-- migrazione 0016.
--
-- Una gara è una seduta, anche quando in un giorno ce ne sono due: sono due
-- prove con partenza e arrivo propri (decisione dell'atleta, 25/08/2026).
race_day AS (
    SELECT
        swim_date                                       AS status_date,
        count(*)                                        AS race_sessions_count,
        -- `sum` salta i NULL: tre gare dell'archivio non hanno una distanza
        -- (il nome dell'evento non la dichiara). Il conteggio qui sotto dice
        -- quante ne avevano una, così la somma parziale non sembra il totale.
        sum(distance_m)                                 AS race_distance_m,
        count(*) FILTER (WHERE distance_m IS NOT NULL)  AS race_distance_known_n,
        sum(duration_s)                                 AS race_duration_s
    FROM counted_swims
    WHERE origin = 'race'
    GROUP BY swim_date
),

-- Spina temporale: ogni giorno fra il primo e l'ultimo dato disponibile,
-- anche quelli senza attività. Un giorno di riposo è un'informazione.
bounds AS (
    SELECT min(day) AS first_day, max(day) AS last_day FROM (
        SELECT min(activity_date) AS day FROM canonical_activities
        UNION ALL SELECT max(activity_date) FROM canonical_activities
        UNION ALL SELECT min(health_date) FROM daily_health
        UNION ALL SELECT max(health_date) FROM daily_health
        UNION ALL SELECT min(sleep_date) FROM sleep
        UNION ALL SELECT max(sleep_date) FROM sleep
        -- Una gara è un dato quanto una seduta. Senza queste due righe la
        -- spina partirebbe dal 04/09/2017 e le gare del 28/05/2016 e del
        -- 27/05/2017 cadrebbero fuori dal calendario senza dire niente.
        UNION ALL SELECT min(status_date) FROM race_day
        UNION ALL SELECT max(status_date) FROM race_day
    ) WHERE day IS NOT NULL
),
spine AS (
    SELECT unnest(generate_series(first_day, last_day, INTERVAL 1 DAY))::DATE AS status_date
    FROM bounds
),

-- Da quando Garmin registra il carico per attività. Prima di questa data il
-- carico non è zero: è assente, e ogni metrica che ne dipende resta NULL (R9).
load_era AS (
    SELECT min(activity_date) AS first_load_day
    FROM canonical_activities WHERE garmin_training_load IS NOT NULL
),

-- Aggregato giornaliero delle attività.
day_activity AS (
    SELECT
        activity_date                                              AS status_date,
        count(DISTINCT session_key)                                AS sessions_count,
        count(DISTINCT session_key) FILTER (WHERE is_swim)        AS swim_sessions_count,
        sum(distance_m) FILTER (WHERE is_swim)                     AS swim_distance_m,
        -- Quante delle nuotate del giorno hanno davvero una distanza. Otto
        -- attività dell'archivio non ce l'hanno: senza questo conteggio la
        -- somma parziale sembrerebbe il totale.
        count(*) FILTER (WHERE is_swim AND distance_m IS NOT NULL)
                                                   AS swim_distance_known_n,
        sum(duration_s)                                            AS session_duration_s,
        sum(garmin_training_load)                                  AS day_load,
        count(*) FILTER (WHERE avg_hr_bpm IS NOT NULL) > 0         AS has_intensity,
        count(*) FILTER (WHERE garmin_training_load IS NOT NULL) > 0 AS has_load,
        list_distinct(list(device_id) FILTER (WHERE device_id IS NOT NULL)) AS device_ids,
        -- Le medie tecniche si pesano sui metri, non sulle sedute.
        --
        -- `avg(avg_swolf)` faceva pesare una seduta da 500 m quanto una da
        -- 4.500. Misurato sui 25 giorni dell'archivio con più di una seduta in
        -- vasca da 25: scarto medio 0,69 SWOLF, massimo 2,35.
        --
        -- Numeratore e denominatore restano separati perché la finestra a 28
        -- giorni deve poterli sommare e dividere una volta sola: fare la media
        -- delle medie giornaliere ripeterebbe lo stesso errore un piano sopra.
        --
        -- I metri di una seduta senza SWOLF non entrano nel denominatore. Se
        -- entrassero, una seduta in cui l'orologio non ha misurato abbasserebbe
        -- la media come se fosse stata nuotata a zero.
        sum(avg_swolf * distance_m) FILTER (
            WHERE pool_length_m = 25 AND avg_swolf IS NOT NULL)   AS swolf_p25_num,
        sum(distance_m) FILTER (
            WHERE pool_length_m = 25 AND avg_swolf IS NOT NULL)   AS swolf_p25_den,
        sum(avg_swolf * distance_m) FILTER (
            WHERE pool_length_m = 50 AND avg_swolf IS NOT NULL)   AS swolf_p50_num,
        sum(distance_m) FILTER (
            WHERE pool_length_m = 50 AND avg_swolf IS NOT NULL)   AS swolf_p50_den,
        sum(avg_stroke_distance_m * distance_m) FILTER (
            WHERE pool_length_m = 25 AND avg_stroke_distance_m IS NOT NULL) AS dps_p25_num,
        sum(distance_m) FILTER (
            WHERE pool_length_m = 25 AND avg_stroke_distance_m IS NOT NULL) AS dps_p25_den,
        sum(avg_stroke_distance_m * distance_m) FILTER (
            WHERE pool_length_m = 50 AND avg_stroke_distance_m IS NOT NULL) AS dps_p50_num,
        sum(distance_m) FILTER (
            WHERE pool_length_m = 50 AND avg_stroke_distance_m IS NOT NULL) AS dps_p50_den,
        -- Quali orologi hanno contribuito a un numero tecnico quel giorno.
        -- Serve a dire, sulla finestra, se la media ne attraversa più di uno:
        -- su questo archivio due dispositivi danno 28,9 e 30,7 di SWOLF medio a
        -- parità di vasca, cioè 1,8 di scarto — l'ordine di grandezza di un
        -- vero cambiamento tecnico.
        list_distinct(list(device_id) FILTER (
            WHERE device_id IS NOT NULL
              AND (avg_swolf IS NOT NULL OR avg_stroke_distance_m IS NOT NULL)))
            AS technique_devices
    FROM canonical_activities
    GROUP BY activity_date
),

-- Tutte le sorgenti allineate sulla spina temporale.
joined AS (
    SELECT
        s.status_date,
        -- Le due sorgenti si sommano, e possono coesistere nello stesso
        -- giorno: il 23/08/2026 la gara era a place04 la mattina e
        -- l'allenamento a place03 alle [orario], cento chilometri più in là. Nulla
        -- è contato due volte perché `counted_swims` esclude le gare che
        -- l'atleta ha dichiarato essere quella stessa nuotata.
        --
        -- Una versione precedente prendeva i metri della gara **al posto** di
        -- quelli dell'orologio, perché nasceva dall'idea che le due cose non
        -- potessero stare insieme: quel giorno mostrava 1.900 m invece di
        -- 5.968.
        coalesce(a.sessions_count, 0)
            + coalesce(r.race_sessions_count, 0)  AS sessions_count,
        coalesce(a.swim_sessions_count, 0)
            + coalesce(r.race_sessions_count, 0)  AS swim_sessions_count,
        -- Tre casi, in quest'ordine. Zero soltanto se non c'è stata nessuna
        -- nuotata: quello è uno zero vero, e trasformarlo in «non lo so»
        -- sarebbe l'errore opposto. Sconosciuto se nuotate ce ne sono state ma
        -- nessuna dichiara i metri (R5). Altrimenti la somma di ciò che si sa,
        -- e `swim_distance_known_n` dice su quante nuotate è calcolata — come
        -- fa già `sum(...) FILTER (WHERE is_swim)`, che salta i valori
        -- mancanti invece di annullare tutto il giorno.
        CASE WHEN coalesce(a.swim_sessions_count, 0)
                    + coalesce(r.race_sessions_count, 0) = 0 THEN 0
             WHEN coalesce(a.swim_distance_known_n, 0)
                    + coalesce(r.race_distance_known_n, 0) = 0 THEN NULL
             ELSE coalesce(a.swim_distance_m, 0)
                    + coalesce(r.race_distance_m, 0) END AS swim_distance_m,
        coalesce(a.swim_distance_known_n, 0)
            + coalesce(r.race_distance_known_n, 0) AS swim_distance_known_n,
        CASE WHEN r.race_duration_s IS NULL THEN a.session_duration_s
             ELSE coalesce(a.session_duration_s, 0)
                    + r.race_duration_s END   AS session_duration_s,
        -- Dentro il periodo con carico, un giorno di riposo vale zero e deve
        -- entrare nelle medie: ignorarlo gonfierebbe la monotonia e falserebbe
        -- l'ACWR. Fuori da quel periodo il carico resta sconosciuto.
        CASE WHEN s.status_date >= le.first_load_day
             THEN coalesce(a.day_load, 0) END AS day_load,
        coalesce(a.has_intensity, FALSE)     AS has_intensity,
        coalesce(a.has_load, FALSE)          AS has_load,
        a.device_ids,
        a.swolf_p25_num, a.swolf_p25_den, a.swolf_p50_num, a.swolf_p50_den,
        a.dps_p25_num, a.dps_p25_den, a.dps_p50_num, a.dps_p50_den,
        coalesce(a.technique_devices, []) AS technique_devices,
        hs.hrv_ms, hs.hrv_baseline_low, hs.hrv_baseline_high, hs.hrv_status,
        dh.resting_hr_bpm, dh.body_battery_min, dh.body_battery_max,
        dh.stress_avg, dh.steps,
        sl.total_sleep_s AS sleep_total_s, sl.sleep_score, sl.deep_s, sl.rem_s,
        rd.score AS garmin_readiness_score,
        rd.level AS garmin_readiness_level,
        rd.recovery_time_h AS garmin_recovery_time_h,
        ts.training_status AS garmin_training_status,
        tl.acute_load   AS garmin_acute_load,
        tl.chronic_load AS garmin_chronic_load,
        tl.acwr         AS garmin_acwr,
        tl.acwr_status  AS garmin_acwr_status
    FROM spine s
    CROSS JOIN load_era le
    LEFT JOIN day_activity           a  ON a.status_date  = s.status_date
    -- Il carico e l'intensità restano quelli dell'orologio: una gara porta
    -- metri e minuti, non battiti. `has_intensity` e `has_load` non la vedono.
    LEFT JOIN race_day               r  ON r.status_date  = s.status_date
    LEFT JOIN health_status          hs ON hs.status_date = s.status_date
    LEFT JOIN daily_health           dh ON dh.health_date = s.status_date
    LEFT JOIN sleep                  sl ON sl.sleep_date  = s.status_date
    LEFT JOIN garmin_readiness       rd ON rd.readiness_date = s.status_date
    LEFT JOIN garmin_training_status ts ON ts.status_date = s.status_date
    LEFT JOIN garmin_training_load   tl ON tl.load_date   = s.status_date
),

-- Finestre mobili. RANGE lavora sui giorni di calendario, non sulle righe:
-- un buco nei dati non sposta la finestra.
windowed AS (
    SELECT
        j.*,
        -- Baseline: 28 giorni precedenti, oggi ESCLUSO
        avg(hrv_ms) OVER base28  AS hrv_baseline_28_raw,
        count(hrv_ms) OVER base28 AS hrv_baseline_n,
        avg(resting_hr_bpm) OVER base28  AS resting_hr_baseline_28_raw,
        count(resting_hr_bpm) OVER base28 AS resting_hr_baseline_n,
        avg(sleep_total_s) OVER base28  AS sleep_baseline_28_raw,
        count(sleep_total_s) OVER base28 AS sleep_baseline_n,
        -- Carico: finestre che includono oggi
        sum(day_load) OVER load7   AS load_acute_7,
        sum(day_load) OVER load28  AS load_sum_28,
        count(day_load) OVER load28 AS load_days_28,
        -- I giorni in cui si è davvero allenato. `load_days_28` conta i giorni
        -- **osservati**, e dentro l'epoca del carico sono sempre tutti: da solo
        -- non impedisce di calcolare un carico cronico su tre sedute.
        sum(CASE WHEN sessions_count > 0 THEN 1 ELSE 0 END) OVER load28
            AS load_training_days_28,
        avg(day_load) OVER load7   AS load_mean_7,
        stddev_samp(day_load) OVER load7 AS load_sd_7,
        -- Volume
        sum(swim_distance_m) OVER load7  AS swim_m_7d,
        sum(swim_distance_m) OVER load28 AS swim_m_28d,
        sum(swim_sessions_count) OVER load7  AS swim_sessions_7d,
        sum(swim_sessions_count) OVER load28 AS swim_sessions_28d,
        -- Tecnica, 28 giorni, separata per vasca
        -- Somma dei numeratori diviso somma dei denominatori: la media pesata
        -- della finestra, non la media delle medie giornaliere.
        sum(swolf_p25_num) OVER load28 AS swolf_p25_num_28,
        sum(swolf_p25_den) OVER load28 AS swolf_p25_den_28,
        sum(swolf_p50_num) OVER load28 AS swolf_p50_num_28,
        sum(swolf_p50_den) OVER load28 AS swolf_p50_den_28,
        sum(dps_p25_num) OVER load28   AS dps_p25_num_28,
        sum(dps_p25_den) OVER load28   AS dps_p25_den_28,
        sum(dps_p50_num) OVER load28   AS dps_p50_num_28,
        sum(dps_p50_den) OVER load28   AS dps_p50_den_28,
        -- Quanti orologi diversi hanno contribuito ai numeri tecnici della
        -- finestra. `flatten` di liste giornaliere e poi `list_distinct`:
        -- `count(DISTINCT ...)` non si può usare su una finestra RANGE.
        len(list_distinct(flatten(list(technique_devices) OVER load28)))
            AS technique_devices_28d,
        -- Ultima nuotata
        max(CASE WHEN swim_sessions_count > 0 THEN status_date END)
            OVER (ORDER BY status_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            AS last_swim_date
    FROM joined j
    WINDOW
        base28 AS (ORDER BY status_date RANGE BETWEEN INTERVAL 28 DAY PRECEDING
                                                  AND INTERVAL 1 DAY PRECEDING),
        load7  AS (ORDER BY status_date RANGE BETWEEN INTERVAL 6 DAY PRECEDING
                                                  AND CURRENT ROW),
        load28 AS (ORDER BY status_date RANGE BETWEEN INTERVAL 27 DAY PRECEDING
                                                  AND CURRENT ROW)
)

SELECT
    status_date,

    -- Attività
    sessions_count,
    swim_sessions_count,
    swim_distance_known_n,
    swim_distance_m,
    session_duration_s,

    -- Recupero, valori Garmin
    hrv_ms, hrv_baseline_low, hrv_baseline_high, hrv_status,
    resting_hr_bpm,
    sleep_total_s, sleep_score, deep_s, rem_s,
    body_battery_min, body_battery_max, stress_avg, steps,
    garmin_readiness_score, garmin_readiness_level, garmin_recovery_time_h,
    garmin_training_status,
    garmin_acute_load, garmin_chronic_load, garmin_acwr, garmin_acwr_status,

    -- Baseline calcolate: pubblicate solo con abbastanza giorni alle spalle
    CASE WHEN hrv_baseline_n >= {MIN_DAYS_FOR_BASELINE}
         THEN hrv_baseline_28_raw END AS hrv_baseline_28,
    CASE WHEN hrv_baseline_n >= {MIN_DAYS_FOR_BASELINE} AND hrv_ms IS NOT NULL
              AND hrv_baseline_28_raw > 0
         THEN 100.0 * (hrv_ms - hrv_baseline_28_raw) / hrv_baseline_28_raw
         END AS hrv_delta_pct,
    CASE WHEN resting_hr_baseline_n >= {MIN_DAYS_FOR_BASELINE}
         THEN resting_hr_baseline_28_raw END AS resting_hr_baseline_28,
    CASE WHEN resting_hr_baseline_n >= {MIN_DAYS_FOR_BASELINE} AND resting_hr_bpm IS NOT NULL
         THEN resting_hr_bpm - resting_hr_baseline_28_raw END AS resting_hr_delta,
    CASE WHEN sleep_baseline_n >= {MIN_DAYS_FOR_BASELINE}
         THEN sleep_baseline_28_raw END AS sleep_baseline_28_s,

    -- Carico calcolato
    load_acute_7,
    CASE WHEN load_days_28 > 0 THEN load_sum_28 / 4.0 END AS load_chronic_28,
    load_days_28,
    load_training_days_28,
    CASE WHEN load_days_28 >= {MIN_DAYS_FOR_ACWR}
              AND load_training_days_28 >= {MIN_TRAINING_DAYS_FOR_ACWR}
              AND load_sum_28 > 0
         THEN load_acute_7 / (load_sum_28 / 4.0) END AS acwr,
    CASE WHEN load_sd_7 > 0 THEN load_mean_7 / load_sd_7 END AS monotony_7,
    CASE WHEN load_sd_7 > 0 THEN load_acute_7 * (load_mean_7 / load_sd_7) END AS strain_7,

    -- Volume
    swim_m_7d / 1000.0  AS swim_km_7d,
    swim_m_28d / 1000.0 AS swim_km_28d,
    swim_sessions_7d,
    swim_sessions_28d,
    CASE WHEN last_swim_date IS NOT NULL
         THEN date_diff('day', last_swim_date, status_date) END AS days_since_last_swim,

    -- Tecnica, mai mescolata fra vasche diverse, pesata sui metri, e con
    -- dichiarato quanti orologi ha attraversato.
    CASE WHEN swolf_p25_den_28 > 0
         THEN swolf_p25_num_28 / swolf_p25_den_28 END AS swolf_28d_pool25,
    CASE WHEN swolf_p50_den_28 > 0
         THEN swolf_p50_num_28 / swolf_p50_den_28 END AS swolf_28d_pool50,
    CASE WHEN dps_p25_den_28 > 0
         THEN dps_p25_num_28 / dps_p25_den_28 END     AS dps_28d_pool25,
    CASE WHEN dps_p50_den_28 > 0
         THEN dps_p50_num_28 / dps_p50_den_28 END     AS dps_28d_pool50,
    technique_devices_28d,

    -- Copertura, sempre dichiarata
    hrv_ms IS NOT NULL AS has_hrv,
    has_intensity,
    has_load,
    device_ids
FROM windowed
ORDER BY status_date;
"""


def build(connection: duckdb.DuckDBPyConnection) -> dict:
    """Ricostruisce ``daily_status`` da zero. È deterministica: stessi dati in
    ingresso, stessa tabella in uscita."""
    connection.execute(BUILD)
    rows, first_day, last_day = connection.execute(
        "SELECT count(*), min(status_date), max(status_date) FROM daily_status"
    ).fetchone()
    return {"table": "daily_status", "rows": rows,
            "first_day": first_day, "last_day": last_day}
