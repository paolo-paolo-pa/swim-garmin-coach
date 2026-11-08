-- Migrazione 0004 — perché questa seduta ha (o non ha) il suo dettaglio (D5).
--
-- Il prototipo prendeva il file FIT più vicino nel tempo e lo trattava come un
-- fatto. Misurato: su 1.340 sedute di nuoto, 4 hanno più di un candidato entro
-- un minuto. Sono poche, e proprio perché sono poche non vanno risolte tirando
-- a indovinare: vanno mostrate.
--
-- Questa tabella conserva anche i candidati scartati. Senza, "questa seduta non
-- ha il dettaglio" resta una frase senza causa, e non si distingue "il file non
-- esiste" da "ce n'erano due e non so quale".

CREATE TABLE IF NOT EXISTS activity_source_matches (
    activity_id       BIGINT NOT NULL,
    source_object_id  VARCHAR NOT NULL,
    -- matched     un solo candidato, e i controlli tornano
    -- ambiguous   più candidati indistinguibili: nessuno viene scelto
    -- incompatible il file c'è ma descrive un'altra cosa (durata o sport diversi)
    -- rejected    candidato scartato in favore di un altro
    verdict           VARCHAR NOT NULL,
    method            VARCHAR NOT NULL,   -- come si è deciso
    time_gap_s        DOUBLE,             -- scarto fra inizio attività e file
    duration_gap_s    DOUBLE,             -- scarto fra le durate dichiarate
    distance_gap_m    DOUBLE,
    reason            VARCHAR,            -- leggibile da un umano
    decided_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (activity_id, source_object_id)
);
