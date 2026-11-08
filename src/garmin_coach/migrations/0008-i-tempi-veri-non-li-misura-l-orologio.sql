-- I tempi veri non li misura l'orologio.
--
-- Fino a qui l'archivio conteneva solo ciò che il Fenix ha registrato: volumi,
-- passi medi, lap. Nessuno di quei numeri è una prestazione. `coach/riferimenti.md`
-- lo dice da sempre — «la media di una seduta con i recuperi dentro non è un
-- tempo prestativo» — e per questo dichiarava bloccate tre cose: la velocità
-- critica, gli intervalli di passo di una serie, e qualunque previsione di gara.
--
-- Lo storico Aquatime le sblocca. Sono 116 risultati FIN dal 2014 al 2026,
-- cronometraggio automatico su 103 di essi, con 145 passaggi. Sono la misura
-- più affidabile di tutto il progetto: non le ha prodotte un orologio al polso
-- di una persona che nuota, le ha prodotte una piastra.
--
-- ## Perché nel database e non in `coach/`
--
-- La Regola Aurea n.3 divide i fatti misurati dalle intenzioni. Un tempo di
-- gara ufficiale è un fatto misurato da terzi, come un'attività Garmin: sta
-- qui. `coach/gare.md` continua a contenere le gare **future** e gli obiettivi,
-- che sono intenzioni, e `coach/riferimenti.md` le prove che l'atleta conferma
-- di suo pugno. Sono tre cose diverse e restano tre tabelle diverse.
--
-- ## Le staffette sono qui e non sono tempi personali
--
-- Otto risultati su 116 sono staffette. Il tempo è della squadra, e i passaggi
-- descrivono le quattro frazioni senza dire quale sia dell'atleta. Entrano
-- nell'archivio perché sono successe, con `is_relay` a vero, e ogni lettura di
-- prestazione personale le esclude: attribuire a una persona il tempo di
-- quattro sarebbe l'errore più facile e più difficile da vedere dopo.
--
-- ## Le squalifiche restano senza tempo
--
-- Due risultati dicono «Squalificato». `time_s` resta NULL e `status` lo
-- dichiara: un valore mancante resta mancante (Regola Aurea n.5), e una
-- squalifica non è un tempo lento.

CREATE TABLE IF NOT EXISTS races (
    race_id           VARCHAR PRIMARY KEY,   -- data + evento + specialità
    race_date         DATE NOT NULL,
    meet              VARCHAR NOT NULL,      -- il nome della manifestazione
    event_label       VARCHAR NOT NULL,      -- come lo scrive la federazione
    distance_m        INTEGER,               -- della singola frazione, non del totale
    stroke            VARCHAR,               -- stile | dorso | rana | delfino | misti
    is_relay          BOOLEAN NOT NULL,
    relay_legs        INTEGER,               -- 4 in una 4x100, NULL se individuale
    pool_length_m     INTEGER NOT NULL,      -- 25 | 50
    time_s            DOUBLE,                -- NULL se non c'è un tempo
    status            VARCHAR NOT NULL,      -- valid | disqualified
    timing            VARCHAR,               -- A automatico | M manuale
    federation        VARCHAR,
    category          VARCHAR,
    meet_id           VARCHAR,
    event_id          VARCHAR,
    source_object_id  VARCHAR NOT NULL,
    imported_at       TIMESTAMP NOT NULL
);

-- Un passaggio per riga. `cumulative_s` è il tempo dalla partenza,
-- `split_s` la frazione appena nuotata, `leg_s` il tempo dei 100 metri chiusi
-- in quel punto quando la federazione lo espone.
--
-- Non si ricalcola `split_s` da `cumulative_s`: quando la sorgente lo espone lo
-- si conserva com'è, e se manca resta NULL. Ricostruirlo sarebbe un valore
-- derivato che assomiglia a una misura (Regola Aurea n.5).
CREATE TABLE IF NOT EXISTS race_splits (
    race_id           VARCHAR NOT NULL,
    split_m           INTEGER NOT NULL,
    cumulative_s      DOUBLE,
    split_s           DOUBLE,
    leg_s             DOUBLE,
    source_object_id  VARCHAR NOT NULL,
    imported_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (race_id, split_m)
);

-- Le sole gare che descrivono la prestazione di questa persona. È la vista che
-- ogni lettura di record, progressione e passo di riferimento deve interrogare,
-- per lo stesso motivo per cui le analisi interrogano `canonical_activities` e
-- non `activities`: perché escludere a mano, ogni volta, prima o poi si dimentica.
CREATE OR REPLACE VIEW personal_races AS
SELECT * FROM races
WHERE NOT is_relay AND status = 'valid' AND time_s IS NOT NULL;
