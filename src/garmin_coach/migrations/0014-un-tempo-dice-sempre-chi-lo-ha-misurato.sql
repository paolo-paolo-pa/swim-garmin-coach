-- Un tempo dice sempre chi lo ha misurato.
--
-- ## La decisione dell'atleta, e perché serve una colonna
--
-- Il 24/08/2026 l'atleta ha deciso di usare i tempi dell'orologio per le cinque
-- gare in mare che nessun archivio cronometra: *«non differiscono di molto,
-- massimo di 1/2 minuti, che non cambiano una 10 km»*.
--
-- È una decisione ragionevole e ribalta una regola che il progetto si era dato
-- il 23/08 — «il tempo dell'orologio non riempie mai un tempo di gara
-- mancante». Ribaltarla in silenzio sarebbe la cosa che REGOLE.md vieta: una
-- regola sbagliata alla prova dei fatti **si modifica esplicitamente**.
--
-- La modifica esplicita è questa colonna. Il tempo entra, e porta con sé da
-- dove viene.
--
-- ## Perché non basta scriverlo nella nota
--
-- Senza colonna, un tempo di piastra e un tempo di orologio hanno la stessa
-- forma in `races`, e qualunque confronto li tratta allo stesso modo. È
-- esattamente il difetto che la migrazione 0009 aveva già corretto per le
-- distanze con `distance_source`: qui vale per i tempi, per la stessa ragione.
--
-- ## Il controesempio che impedisce di considerarli equivalenti
--
-- place05 2019: l'orologio dice 6.975 m in 2h13', il cronometro ufficiale
-- 10 km in **3h00'46"**. Quarantasette minuti di scarto, che nessuna
-- ripulitura delle estremità spiega — l'orologio è stato fermato e ripreso, o
-- si è spento.
--
-- Quella gara ha già il proprio tempo ufficiale e non è toccata da questa
-- decisione. Resta però la prova, dentro questo stesso archivio, che i due
-- numeri **non sono la stessa cosa** anche quando quasi sempre si somigliano.
--
-- ## I valori
--
--   chronometer     cronometro ufficiale della manifestazione. È una misura di
--                   terzi, ed è il caso di tutte le gare di Aquatime e Icron.
--   watch_trimmed   orologio, ripulito dei minuti a cadenza anomala alle due
--                   estremità (`analysis/swimming_time.py`). Sull'archivio vero
--                   toglie 1-2 minuti quasi ovunque, e 8 sul lake01 2018,
--                   dove l'orologio è partito ben prima del via.
--   watch           orologio così com'è, quando la cadenza non permette di
--                   distinguere l'attesa dal nuoto.
--
-- Vuoto sulle righe più vecchie non è una lacuna: significa cronometro, ed è
-- riempito qui sotto per non lasciare che il vuoto vada indovinato.

ALTER TABLE races ADD COLUMN IF NOT EXISTS time_source VARCHAR;

-- Tutte le gare già in archivio con un tempo vengono da un cronometro: la
-- federazione in vasca, l'organizzazione in mare. Dirlo adesso evita che
-- restino NULL e che una query futura debba indovinare cosa significhi il vuoto
-- — è la stessa cura che la 0009 ha avuto con `environment`.
UPDATE races
   SET time_source = 'chronometer'
 WHERE time_source IS NULL AND time_s IS NOT NULL;

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
