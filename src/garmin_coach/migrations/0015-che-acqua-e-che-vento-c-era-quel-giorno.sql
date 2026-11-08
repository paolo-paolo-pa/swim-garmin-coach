-- Che acqua e che vento c'era, quel giorno.
--
-- ## La domanda dell'atleta
--
-- *«Non ho bisogno di una precisione millimetrica, ma almeno di avere dei
-- parametri chiari da poter confrontare.»* — 24/08/2026, autorizzando
-- l'interrogazione di modelli meteo esterni.
--
-- È la domanda giusta. Due nuotate in mare sulla stessa distanza dichiarata,
-- con tempi diversi, oggi non si possono confrontare: manca il pezzo che
-- spiega la differenza. Un'acqua a 19 °C con onda mezzo metro e un'acqua a
-- 24 °C piatta non sono la stessa gara, e il passo non lo dice.
--
-- ## Perché la posizione arrotondata arriva solo adesso
--
-- La migrazione 0012 ha deciso, di proposito, di non conservare **nessuna**
-- coordinata: alle analisi di allora servivano solo differenze fra punti, e un
-- divieto che poggia sull'assenza del dato è l'unico che non si può dimenticare
-- di applicare.
--
-- Quella scelta resta valida per la traccia: `activity_track` non ha e non avrà
-- coordinate. Qui serve un'altra cosa — **dove chiedere il meteo** — e serve una
-- volta per attività, non una volta per punto.
--
-- Arrotondata a un decimo di grado, cioè circa **undici chilometri**. Non è una
-- precauzione simbolica: è la risoluzione a cui i modelli meteo lavorano
-- comunque, quindi un valore più preciso non darebbe una risposta migliore.
-- Dice in quale tratto di costa si nuotava, non da quale spiaggia si è partiti.
--
-- La Regola Aurea n.1 punto 6 dice di creare le cose quando servono. Servono
-- adesso, e non servivano ieri.
--
-- ## Perché le condizioni stanno in tabella e non si richiedono ogni volta
--
-- Ogni riga costa una richiesta a un servizio di terzi che ci fa un favore
-- gratis. Si chiede una volta per gara e non si chiede mai più: dopo il primo
-- scaricamento il progetto continua a funzionare senza rete, come già fa con
-- gli snapshot di Garmin.
--
-- ## Cosa questi numeri non sono
--
-- **Non sono una misura di quella gara.** Sono la ricostruzione di un modello
-- su una griglia di chilometri, e la corrente sotto costa — quella che un
-- nuotatore sente davvero — non ci sta dentro.
--
-- Servono a due cose oneste: dare **contesto** a un tempo, e fare da
-- **riscontro** alla corrente misurata dall'asimmetria per direzione della
-- nuotata stessa. Se il GPS dice assistenza verso nord e il vento quel giorno
-- soffiava da sud, le due cose concordano e la lettura si rafforza; se si
-- contraddicono, il coach lo dice invece di scegliere la versione più comoda.
--
-- Non entrano mai in una formula che «corregge» un tempo. Un tempo corretto da
-- un modello non è più un tempo.

ALTER TABLE activity_track_quality
    ADD COLUMN IF NOT EXISTS start_lat_rounded DOUBLE;
ALTER TABLE activity_track_quality
    ADD COLUMN IF NOT EXISTS start_lon_rounded DOUBLE;

CREATE TABLE IF NOT EXISTS race_conditions (
    activity_id           BIGINT PRIMARY KEY,
    observed_date         DATE    NOT NULL,
    from_hour_utc         INTEGER,          -- finestra davvero coperta dalla
    to_hour_utc           INTEGER,          -- nuotata, non l'intera giornata
    air_temperature_c     DOUBLE,
    water_temperature_c   DOUBLE,
    wind_speed_kmh        DOUBLE,
    wind_direction_deg    DOUBLE,           -- da dove soffia, 0 = da nord
    wave_height_m         DOUBLE,
    wave_direction_deg    DOUBLE,
    hours_covered         INTEGER NOT NULL,
    model                 VARCHAR NOT NULL, -- chi ha risposto, sempre dichiarato
    source_object_id      VARCHAR NOT NULL,
    imported_at           TIMESTAMP NOT NULL
);
