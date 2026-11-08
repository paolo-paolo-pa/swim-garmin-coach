-- Una gara in mare non è una gara in vasca.
--
-- La 0008 ha portato in archivio 114 gare della federazione. Tutte in piscina:
-- `pool_length_m` era NOT NULL perché non esisteva altro. Adesso arrivano 26
-- risultati in acque libere dal profilo Icron, dal 2016 al 2026, e non entrano
-- in quello schema — non per un dettaglio tecnico, ma perché **sono un'altra
-- cosa**.
--
-- ## Cosa cambia davvero fra i due ambienti
--
-- In vasca il tempo e la distanza sono **entrambi** misurati: la piastra
-- cronometra, e i 400 m sono 400 m certificati. Un tempo di gara in piscina è
-- il dato più affidabile di tutto questo progetto.
--
-- In mare è misurato **solo il tempo**. Il percorso è quello che le boe, la
-- corrente e la traiettoria di chi nuota hanno reso quel giorno; il numero nel
-- nome della gara — «3K», «MIGLIO», «2500M» — è una dichiarazione
-- dell'organizzazione. L'atleta lo ha detto con parole sue: «i tempi non
-- possono essere precisi a causa delle distanze quasi mai precise con quelle
-- indicate dalla gara». La prova sta nell'archivio: il 04/07/2026, per la gara
-- che Icron chiama «MIGLIO», la traccia Garmin misura 1.234 m — meno sia di
-- 1.609 sia di 1.852.
--
-- Perciò un passo per 100 m ricavato da una gara in mare **non è un passo**: è
-- un tempo diviso per una distanza dichiarata. Resta utile — è l'unica misura
-- di fondo che questa persona abbia in acqua salata — e va letto sapendo cosa
-- è. Da qui le due colonne nuove.
--
-- ## `environment`: perché una colonna e non una convenzione
--
-- Si sarebbe potuto dire «pool_length_m NULL vuol dire mare». Sarebbe una
-- convenzione da ricordare, e la prima query che dimentica di controllarla
-- mette una gara di 10 km in mare dentro i record di vasca. Una colonna che
-- dice il proprio nome non si dimentica.
--
-- ## `distance_source`: da dove viene il numero, sempre
--
-- Regola Aurea n.5, «valore Garmin, valore normalizzato e valore calcolato
-- restano distinti e riconoscibili». Qui la distanza può venire da tre posti
-- diversi, e la differenza fra loro è la differenza fra un record e una stima:
--
--   certified_pool  la vasca è certificata e la distanza è quella dichiarata
--                   dalla federazione. È una misura.
--   event_field     il campo «prova» di Icron contiene un numero: 2500M, 5K,
--                   1800. È una dichiarazione dell'organizzazione.
--   meet_name       il numero è nel nome della gara e non nella prova
--                   («event08 - 3KM FIN»). È una dichiarazione
--                   letta di seconda mano.
--   unknown         «MASTER», «AGONISTI», «MIGLIO» senza quantificarlo: non è
--                   una distanza, è una categoria. `distance_m` resta NULL.
--
-- Cinque risultati su 26 finiscono in `unknown`, e due nel caso del miglio non
-- quantificato. Non vengono riempiti con 1.609 né con 1.852: un valore
-- mancante resta mancante, e sceglierne uno dei due significherebbe inventare
-- 243 metri.
--
-- ## `overall_place` e `category_place`, e perché non sono decorazione
--
-- La Regola Aurea n.2 chiede quale domanda dell'atleta giustifica una colonna.
-- Questa: *«in mare, come è andata?»* — a cui il tempo non sa rispondere.
-- Due gare sulla stessa distanza dichiarata, con corrente diversa, danno tempi
-- che non si possono confrontare; il piazzamento, nella stessa gara e contro le
-- stesse persone, è l'unico fatto confrontabile che il mare produca. Non è una
-- misura di forma — dipende da chi si è presentato — ed è registrato come
-- fatto, mai come prestazione.
--
-- ## `venue`
--
-- Icron espone la località separata dal nome della gara. In vasca resta NULL:
-- la federazione la scrive dentro il nome della manifestazione e spaccarla a
-- posteriori sarebbe inventare struttura.

-- Le gare in mare non hanno una vasca. La colonna smette di essere obbligatoria
-- e diventa il segno di distinzione fra i due mondi, insieme a `environment`.
ALTER TABLE races ALTER COLUMN pool_length_m DROP NOT NULL;

ALTER TABLE races ADD COLUMN IF NOT EXISTS environment VARCHAR;
ALTER TABLE races ADD COLUMN IF NOT EXISTS distance_source VARCHAR;
ALTER TABLE races ADD COLUMN IF NOT EXISTS venue VARCHAR;
ALTER TABLE races ADD COLUMN IF NOT EXISTS overall_place INTEGER;
ALTER TABLE races ADD COLUMN IF NOT EXISTS category_place INTEGER;

-- Le 114 righe già in archivio vengono tutte dalla federazione, in piscina, con
-- distanza certificata. Dirlo esplicitamente adesso evita che restino NULL e
-- che una query futura debba indovinare cosa significhi il vuoto.
UPDATE races
   SET environment = 'piscina'
 WHERE environment IS NULL;

UPDATE races
   SET distance_source = 'certified_pool'
 WHERE distance_source IS NULL AND distance_m IS NOT NULL;

-- La vista va ricreata: era `SELECT *` e le colonne di una vista in DuckDB si
-- fissano quando la si crea. Senza questo, `personal_races` continuerebbe a
-- mostrare lo schema di ieri.
--
-- Il filtro non cambia — niente staffette, niente squalifiche, niente tempi
-- assenti — perché la regola su cosa sia una prestazione personale è la stessa
-- in mare e in vasca. Ciò che cambia è che adesso la vista porta con sé
-- `environment` e `distance_source`, così chi legge sa sempre cosa ha in mano.
CREATE OR REPLACE VIEW personal_races AS
SELECT * FROM races
WHERE NOT is_relay AND status = 'valid' AND time_s IS NOT NULL;

-- Le sole gare che si possono confrontare fra loro senza precauzioni: piscina,
-- distanza certificata, stile noto. È la vista che i record e la velocità
-- critica devono interrogare. Il mare non ci entra, e non per sfiducia: perché
-- confrontare 2.500 m dichiarati con 2.500 m dichiarati altrove è confrontare
-- due numeri che nessuno ha misurato.
CREATE OR REPLACE VIEW pool_races AS
SELECT * FROM personal_races
WHERE environment = 'piscina'
  AND distance_source = 'certified_pool'
  AND distance_m IS NOT NULL
  AND stroke IS NOT NULL;

-- Le gare in mare, con la loro distanza dichiarata quando c'è. Vista separata
-- e non un filtro sparso nelle query, per la stessa ragione per cui esiste
-- `canonical_activities`: escludere a mano, ogni volta, prima o poi si dimentica.
CREATE OR REPLACE VIEW open_water_races AS
SELECT * FROM personal_races
WHERE environment = 'acque libere';
