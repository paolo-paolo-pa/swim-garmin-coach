-- Una gara e la nuotata che la registra sono la stessa mattina.
--
-- ## Il buco, misurato
--
-- `coach/gare-dichiarate.md` ha una colonna «Seduta Garmin» dal 23/08/2026, e
-- `declared_races.py` la legge davvero: la mette in `DeclaredRace.activity_id`
-- e la conta nel rapporto finale come `linked_to_garmin`.
--
-- Poi la butta. La `INSERT` in `races` non ha mai avuto una colonna dove
-- metterla, e nessuno se n'era accorto perché il numero nel rapporto tornava.
--
-- Conseguenza: il collegamento fra place21 2024 e i 10.152 metri che
-- l'orologio ha registrato quella mattina **esiste solo in un markdown**. Da
-- SQL non è raggiungibile, e quindi nessuna analisi può passare dall'una
-- all'altra.
--
-- ## Perché blocca tutto il resto
--
-- La Macro-proposta 5 vuole leggere una gara nel profondo: percorso, andamento
-- a tratti, asimmetria per direzione, sforzo. Tutti quei dati stanno
-- nell'attività, non nella gara — la gara ha un tempo, un piazzamento e una
-- distanza dichiarata, e nient'altro.
--
-- Senza questa colonna ogni lettura profonda comincerebbe rileggendo un file
-- markdown, che è esattamente il genere di scorciatoia che il progetto ha già
-- pagato altrove.
--
-- ## Perché resta una dichiarazione e non un'inferenza
--
-- Si potrebbe agganciare per data: una gara del 26/05/2024 e l'unica nuotata in
-- mare del 26/05/2024 sono quasi certamente la stessa cosa. **Quasi.** E il
-- «quasi» è il punto: il giorno prima di place23 e di place21 ci sono
-- ricognizioni del percorso, cioè altre nuotate in mare nello stesso posto, e
-- una regola per data avrebbe la stessa fiducia per l'una e per l'altra.
--
-- La colonna accetta perciò soltanto ciò che l'atleta ha scritto. Il codice può
-- **proporre** un candidato — è la stessa forma del rilevatore di nuotate
-- lunghe e dello strato delle correzioni confermate — e la promozione resta una
-- riga scritta a mano.
--
-- Per le gare di Aquatime e di Icron la colonna resta NULL e non è un dato
-- mancante: la federazione non sa cosa avesse al polso chi nuotava, e in vasca
-- la domanda non si pone nemmeno.

ALTER TABLE races ADD COLUMN IF NOT EXISTS activity_id BIGINT;

-- Le tre viste sono `SELECT *`, e in DuckDB le colonne di una vista si fissano
-- quando la si crea: senza ricrearle continuerebbero a mostrare lo schema di
-- ieri, senza la colonna nuova e senza dire perché. È già stato il caso della
-- migrazione 0009.
CREATE OR REPLACE VIEW personal_races AS
SELECT * FROM races
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
