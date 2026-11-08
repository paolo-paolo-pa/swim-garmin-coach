-- Migrazione 0001 — lo schema esistente al 21 agosto 2026.
-- Nasce da CREATE TABLE IF NOT EXISTS: applicarla a un database gia
-- popolato non cambia niente, applicarla a uno vuoto lo costruisce.
-- E il ponte fra i due mondi richiesto dal cancello D1.

-- ─────────────────────────────────────────────────────────────────────────
-- ATTIVITÀ — spina dorsale, da summarizedActivities.json (2017-2026)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activities (
    activity_id            BIGINT PRIMARY KEY,
    start_time_utc         TIMESTAMP NOT NULL,
    start_time_local       TIMESTAMP,
    activity_date          DATE NOT NULL,      -- giorno locale dell'atleta
    timezone_id            VARCHAR,
    sport                  VARCHAR NOT NULL,   -- activityType Garmin, non tradotto
    is_swim                BOOLEAN NOT NULL,
    environment            VARCHAR,            -- 'pool' | 'open_water' | NULL
    name                   VARCHAR,
    duration_s             DOUBLE,
    elapsed_s              DOUBLE,
    moving_s               DOUBLE,
    distance_m             DOUBLE,
    avg_speed_ms           DOUBLE,
    max_speed_ms           DOUBLE,
    calories_kcal          DOUBLE,
    bmr_calories_kcal      DOUBLE,
    -- Intensità: assente prima del 2021 (R9). NULL resta NULL.
    avg_hr_bpm             DOUBLE,
    max_hr_bpm             DOUBLE,
    min_hr_bpm             DOUBLE,
    hr_zone_0_s            DOUBLE,
    hr_zone_1_s            DOUBLE,
    hr_zone_2_s            DOUBLE,
    hr_zone_3_s            DOUBLE,
    hr_zone_4_s            DOUBLE,
    hr_zone_5_s            DOUBLE,
    -- Carico: metriche proprietarie Garmin, esposte non ricalcolate
    garmin_training_load   DOUBLE,
    garmin_aerobic_te      DOUBLE,
    garmin_anaerobic_te    DOUBLE,
    garmin_te_label        VARCHAR,
    moderate_minutes       DOUBLE,
    vigorous_minutes       DOUBLE,
    -- Nuoto: copertura 97-100% su tutti e nove gli anni
    pool_length_m          DOUBLE,
    avg_swolf              DOUBLE,
    avg_stroke_distance_m  DOUBLE,
    avg_swim_cadence_spm   DOUBLE,
    max_swim_cadence_spm   DOUBLE,
    total_strokes          DOUBLE,
    avg_strokes_per_length DOUBLE,
    active_lengths         BIGINT,
    lap_count              BIGINT,
    -- Soggettivo: presente sul 38% delle sedute, scala da confermare
    rpe                    DOUBLE,
    feel                   DOUBLE,
    -- Contesto
    device_id              BIGINT,
    is_personal_record     BOOLEAN,
    is_favorite            BOOLEAN,
    max_temperature_c      DOUBLE,
    min_temperature_c      DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- SALUTE — da UDSFile_*.json (DI-Connect-Aggregator)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_health (
    health_date            DATE PRIMARY KEY,
    resting_hr_bpm         DOUBLE,
    min_hr_bpm             DOUBLE,
    max_hr_bpm             DOUBLE,
    steps                  BIGINT,
    distance_m             DOUBLE,
    active_kcal            DOUBLE,
    total_kcal             DOUBLE,
    active_s               DOUBLE,
    highly_active_s        DOUBLE,
    moderate_minutes       DOUBLE,
    vigorous_minutes       DOUBLE,
    stress_avg             DOUBLE,
    stress_max             DOUBLE,
    stress_rest_s          DOUBLE,
    body_battery_min       DOUBLE,
    body_battery_max       DOUBLE,
    respiration_avg        DOUBLE,
    spo2_avg               DOUBLE,
    spo2_lowest            DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- SONNO — da *_sleepData.json (DI-Connect-Wellness)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sleep (
    sleep_date             DATE PRIMARY KEY,
    sleep_start_utc        TIMESTAMP,
    sleep_end_utc          TIMESTAMP,
    total_sleep_s          DOUBLE,
    deep_s                 DOUBLE,
    light_s                DOUBLE,
    rem_s                  DOUBLE,
    awake_s                DOUBLE,
    unmeasurable_s         DOUBLE,
    sleep_score            DOUBLE,
    avg_respiration        DOUBLE,
    avg_sleep_stress       DOUBLE,
    restless_count         BIGINT,
    awake_count            BIGINT,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- HRV E BASELINE GARMIN — da *_healthStatusData.json. Solo dal 2025-09 (R5)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS health_status (
    status_date            DATE PRIMARY KEY,
    hrv_ms                 DOUBLE,
    hrv_baseline_low       DOUBLE,
    hrv_baseline_high      DOUBLE,
    hrv_status             VARCHAR,
    hr_bpm                 DOUBLE,
    hr_baseline_low        DOUBLE,
    hr_baseline_high       DOUBLE,
    hr_status              VARCHAR,
    spo2_pct               DOUBLE,
    respiration            DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- CARICO GARMIN — da MetricsAcuteTrainingLoad_*.json
-- ATTENZIONE: calendarDate è epoch in millisecondi, non una data ISO.
-- È l'errore che ha bloccato il progetto precedente (15 file non importati).
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS garmin_training_load (
    load_date              DATE PRIMARY KEY,
    acute_load             DOUBLE,
    chronic_load           DOUBLE,
    acwr                   DOUBLE,
    acwr_percent           DOUBLE,
    acwr_status            VARCHAR,
    device_id              BIGINT,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- STATO ALLENAMENTO GARMIN — da TrainingHistory_*.json
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS garmin_training_status (
    status_date            DATE PRIMARY KEY,
    training_status        VARCHAR,
    fitness_trend          VARCHAR,
    device_id              BIGINT,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- READINESS GARMIN — da TrainingReadinessDTO_*.json. Solo dal 2024-06
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS garmin_readiness (
    readiness_date         DATE PRIMARY KEY,
    score                  DOUBLE,
    level                  VARCHAR,
    recovery_time_h        DOUBLE,
    hrv_weekly_avg         DOUBLE,
    sleep_score_pct        DOUBLE,
    sleep_history_pct      DOUBLE,
    stress_history_pct     DOUBLE,
    hrv_factor_pct         DOUBLE,
    acwr_factor_pct        DOUBLE,
    recovery_factor_pct    DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- PESO E ALTEZZA — da 00000000_userBioMetrics.json
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS body_metrics (
    measure_date           DATE PRIMARY KEY,
    weight_kg              DOUBLE,
    height_cm              DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- ZONE DI FREQUENZA CARDIACA — da 00000000_heartRateZones.json
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hr_zones (
    sport                  VARCHAR PRIMARY KEY,
    method                 VARCHAR,
    max_hr_used            DOUBLE,
    resting_hr_used        DOUBLE,
    zone1_floor            DOUBLE,
    zone2_floor            DOUBLE,
    zone3_floor            DOUBLE,
    zone4_floor            DOUBLE,
    zone5_floor            DOUBLE,
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- ─────────────────────────────────────────────────────────────────────────
-- SERIE DI NUOTO — dai file FIT (Fase 5)
-- ─────────────────────────────────────────────────────────────────────────
-- Una riga per ripetuta: quello che l'orologio ha registrato come "lap".
-- I riepiloghi JSON danno solo i totali della seduta; qui c'è come la seduta
-- era fatta dentro — 8×100 stile o 2.000 continui non sono la stessa cosa
-- anche quando il totale coincide.
--
-- Il recupero è una riga come le altre, con is_rest = true: cancellarlo
-- renderebbe impossibile ricostruire i tempi di partenza.
CREATE TABLE IF NOT EXISTS swim_sets (
    activity_id            BIGINT NOT NULL,
    set_index              INTEGER NOT NULL,   -- message_index del lap nel FIT
    start_time_utc         TIMESTAMP,
    duration_s             DOUBLE,
    distance_m             DOUBLE,
    lengths_count          INTEGER,
    active_lengths_count   INTEGER,
    stroke                 VARCHAR,            -- freestyle, backstroke, breaststroke,
                                               -- butterfly, drill, mixed, im
    total_strokes          DOUBLE,
    avg_hr_bpm             DOUBLE,
    max_hr_bpm             DOUBLE,
    avg_cadence_spm        DOUBLE,
    pace_per_100m_s        DOUBLE,             -- calcolato: duration/distance*100
    swolf                  DOUBLE,             -- calcolato per vasca, non per ripetuta
    lap_trigger            VARCHAR,            -- manual | interval | distance | time
    is_rest                BOOLEAN,            -- nessuna vasca attiva: è un recupero
    source_sha             VARCHAR NOT NULL,
    imported_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (activity_id, set_index)
);

-- ─────────────────────────────────────────────────────────────────────────
-- VASCHE — dai file FIT (Fase 5)
-- ─────────────────────────────────────────────────────────────────────────
-- Una riga per vasca percorsa. È il livello più fine che l'orologio registra
-- e l'unico che permette di vedere il decadimento dentro una ripetuta.
-- Solo vasca: in acque libere il concetto non esiste.
CREATE TABLE IF NOT EXISTS swim_lengths (
    activity_id            BIGINT NOT NULL,
    length_index           INTEGER NOT NULL,   -- message_index del length nel FIT
    set_index              INTEGER,            -- la ripetuta a cui appartiene
    start_time_utc         TIMESTAMP,
    duration_s             DOUBLE,
    stroke                 VARCHAR,
    total_strokes          DOUBLE,
    avg_speed_ms           DOUBLE,
    cadence_spm            DOUBLE,
    is_active              BOOLEAN,            -- false = vasca di riposo
    PRIMARY KEY (activity_id, length_index)
);

-- ─────────────────────────────────────────────────────────────────────────
-- REGISTRO DEGLI IMPORT — evidenza per il criterio C6d
-- Dimostra che ogni riga proviene da un file di garmin-export/, non dal
-- vecchio database. Non è un sistema di governance: è una prova.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS import_log (
    source_path            VARCHAR NOT NULL,   -- relativo alla radice del progetto
    source_sha             VARCHAR NOT NULL,
    target_table           VARCHAR NOT NULL,
    rows_written           BIGINT NOT NULL,
    imported_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (source_sha, target_table)
);
