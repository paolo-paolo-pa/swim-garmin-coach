-- Una gara in mare è più di quattro numeri.
--
-- ## Cosa c'era prima, misurato
--
-- place21 2024, dieci chilometri: **4 lap**. place23 2017: **1**.
-- place19-place28, trenta chilometri in dieci ore: **2**. Ventiquattro nuotate in
-- mare su novantasette: **zero**.
--
-- Da quattro numeri non si legge come è stata distribuita una gara, non si vede
-- dove è cambiata, e non si distingue una corrente favorevole da una giornata
-- buona. Il progetto sapeva dire *quanto* era stato nuotato e non *come*.
--
-- Il dato però c'era. Nei FIT, che la decisione n.8 del piano aveva scelto di
-- non importare: place21 ne ha **204 punti**, il lake01 2026 ne ha
-- **14.019**, uno al secondo, con battito e temperatura su ognuno.
--
-- ## La decisione n.8 è stata rivista, non aggirata
--
-- La regola generale resta e resta giusta: importare i campioni al secondo di
-- tutte le 1.341 sedute moltiplicherebbe l'archivio per rispondere a domande
-- che nessuno fa. Del martedì qualunque interessa il totale.
--
-- L'eccezione vale per **le gare e per le acque libere**, ed è motivata da una
-- misura invece che da un'intuizione: in vasca il dettaglio esiste già —
-- 173.864 vasche, una riga per vasca — mentre in mare le vasche non esistono e
-- i lap sono quelli che l'atleta ha premuto a mano, cioè quasi nessuno.
--
-- Decisione dell'atleta del 24/08/2026, scritta in PIANO.md §5 n.8.
--
-- ## Perché qui dentro non ci sono coordinate
--
-- È la scelta di progetto più importante di questa migrazione, e va motivata
-- perché a prima vista sembra una rinuncia.
--
-- Le regole del progetto vietano coordinate GPS precise negli output, e il
-- dizionario dei dati poteva dire una cosa più forte: «la colonna non esiste
-- nemmeno nello schema». Un divieto che poggia sull'assenza del dato è l'unico
-- che non si può dimenticare di applicare.
--
-- Per fortuna non serve rinunciare a niente. Di una posizione assoluta le
-- analisi previste non fanno **nulla**: quello che serve è
--
--   `segment_m`     quanto si è percorso da un punto al successivo;
--   `heading_deg`   in che direzione si stava andando.
--
-- Con questi due si ottengono la lunghezza vera del percorso, il confronto con
-- la distanza dell'orologio, l'andamento a tratti e — la lettura che vale di
-- più in mare — l'asimmetria per direzione, cioè quanto l'acqua ha aiutato o
-- frenato. Sono entrambi **differenze fra due punti**: non dicono dove si
-- nuotava, dicono come ci si muoveva.
--
-- La posizione approssimata per il meteo storico non entra qui. Arriverà con la
-- fase che la usa, se ci arriverà, e con la propria motivazione: creare adesso
-- una colonna per un domani è la cosa che la Regola Aurea n.1 punto 6 vieta.
--
-- ## `activity_track_quality`: il cancello, calcolato una volta
--
-- Non tutte le registrazioni reggono un'analisi a tratti. Misurato sulle 22
-- nuotate in mare oltre i 3 km con un file agganciato: **18 passano**, e le
-- quattro che non passano hanno il GPS rotto in modo grave — copertura fra il
-- 12% e il 65%, e distanza ricalcolata che sbaglia fino al 67%.
--
-- Il verdetto sta in tabella e non in una funzione perché deve essere lo stesso
-- per chiunque legga, e perché il motivo del rifiuto è un'informazione per
-- l'atleta quanto il risultato: «di questa gara posso dirti il totale, non come
-- l'hai distribuita» è una risposta, «nessun dato» non lo è.

CREATE TABLE IF NOT EXISTS activity_track (
    activity_id       BIGINT   NOT NULL,
    point_index       INTEGER  NOT NULL,
    timestamp_utc     TIMESTAMP,
    elapsed_s         DOUBLE,          -- dall'inizio della registrazione
    distance_m        DOUBLE,          -- cumulativa, come la dice l'orologio
    segment_m         DOUBLE,          -- dal punto precedente, ricavata dal GPS
    heading_deg       DOUBLE,          -- direzione del segmento, 0 = nord
    speed_ms          DOUBLE,
    heart_rate_bpm    DOUBLE,
    cadence_spm       DOUBLE,
    temperature_c     DOUBLE,
    source_object_id  VARCHAR  NOT NULL,
    imported_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (activity_id, point_index)
);

CREATE TABLE IF NOT EXISTS activity_track_quality (
    activity_id        BIGINT PRIMARY KEY,
    points             INTEGER NOT NULL,
    gps_points         INTEGER NOT NULL,
    gps_coverage       DOUBLE,        -- quota di punti con un fix, 0-1
    gps_distance_m     DOUBLE,        -- somma dei segmenti
    device_distance_m  DOUBLE,        -- quella dell'orologio, per confronto
    distance_gap       DOUBLE,        -- scarto relativo fra le due, con segno
    median_interval_s  DOUBLE,        -- ogni quanto l'orologio ha registrato
    has_heart_rate     BOOLEAN NOT NULL,
    segments_ok        BOOLEAN NOT NULL,   -- il cancello di qualità
    gate_reason        VARCHAR,            -- perché no, quando è no
    source_object_id   VARCHAR NOT NULL,
    imported_at        TIMESTAMP NOT NULL
);
