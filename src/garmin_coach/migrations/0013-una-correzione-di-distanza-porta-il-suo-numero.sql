-- Una correzione di distanza porta il proprio numero.
--
-- ## Il limite che l'audit aveva previsto, e che si è avverato
--
-- L'audit del 23/08/2026 lasciava aperto il residuo A2 con queste parole: «lo
-- stato generico `correct` non ha campi numerici strutturati: oggi place03
-- funziona perché il riepilogo contiene già i 6.000 m scelti, ma una futura
-- correzione di distanza non potrebbe sostituire il raw in modo canonico».
--
-- La futura correzione è arrivata il 24/08/2026, ed è la Traversata del lake01 del 14/06/2026.
--
-- ## Il caso, misurato
--
-- L'orologio dichiara 11.155 m. L'atleta dichiara **14 km**, e ricorda che fino
-- al primo rifornimento il GPS ha preso circa metà della distanza.
--
-- La traccia importata con la fase 5.3 gli dà ragione in modo che non lascia
-- spazio a interpretazioni: **nei primi 80 minuti non esiste un solo fix GPS**
-- — zero segmenti su 4.800 punti — e l'orologio ha ricavato la distanza dalle
-- sole bracciate, arrivando a 2.877 m.
--
-- Il conto chiude da solo: quei 2.877 m raddoppiati aggiungono 2.877 m, e
-- 11.155 + 2.877 = **14.032 m**. L'atleta ha detto «14 km» a memoria, la
-- traccia lo conferma a trenta metri, e le due cose sono state stabilite
-- indipendentemente.
--
-- ## Perché non basta scriverlo nella nota
--
-- Con lo stato `correct` di prima, la distanza vera viveva in una frase in
-- italiano. Nessuna query poteva usarla, e `canonical_activities` continuava a
-- restituire 11.155: cioè un passo di 2:05,7/100 m invece di 1:40,1/100 m su
-- una nuotata di quasi quattro ore.
--
-- Non è un dettaglio contabile. Quel 2:05,7 è finito in `coach/gare.md` fra i
-- riferimenti in mare dell'atleta, dove faceva sembrare la sua nuotata più
-- lenta di venticinque secondi al cento di quanto sia stata.
--
-- ## Cosa cambia, e cosa resta intoccabile
--
-- `activities` non si tocca: resta il fatto grezzo, 11.155 m, con la sua
-- provenienza. La correzione vive dove vivono le decisioni umane — il markdown
-- dell'atleta — ed entra qui dentro come numero.
--
-- `avg_speed_ms` viene ricalcolata insieme alla distanza. Lasciarla ferma
-- creerebbe una vista in cui `distance_m / duration_s` e `avg_speed_ms` dicono
-- due cose diverse: la stessa classe di difetto della media di medie, che
-- questo progetto ha già pagato una volta.
--
-- I lap e le vasche restano quelli del file e continuano a sommare 11.155 m.
-- È giusto che sia così, e la pagina della seduta deve poterlo dire: il
-- dettaglio descrive ciò che l'orologio ha visto, il totale ciò che è successo.

ALTER TABLE activity_quality
    ADD COLUMN IF NOT EXISTS corrected_distance_m DOUBLE;

-- La vista si ricrea per intero: `a.*` conteneva `distance_m` e `avg_speed_ms`
-- così come stavano, e in DuckDB le colonne di una vista si fissano quando la
-- si crea.
--
-- `EXCLUDE` toglie le due colonne dal `*` e le rimette calcolate subito sotto,
-- così l'elenco delle altre cinquanta non va riscritto a mano — e non va
-- aggiornato la prossima volta che una colonna nasce.
CREATE OR REPLACE VIEW canonical_activities AS
WITH scoperte AS (
    SELECT a.* EXCLUDE (distance_m, avg_speed_ms),
           coalesce(q.corrected_distance_m, a.distance_m)  AS distance_m,
           CASE
               WHEN q.corrected_distance_m IS NOT NULL AND a.duration_s > 0
                   THEN q.corrected_distance_m / a.duration_s
               ELSE a.avg_speed_ms
           END                                             AS avg_speed_ms,
           -- Chi legge deve poter sapere che sta guardando un numero
           -- dichiarato dall'atleta e non uno misurato dall'orologio. Senza
           -- questa colonna la correzione diventa invisibile, ed è esattamente
           -- il modo in cui una correzione giusta viene scambiata per un
           -- difetto e «riparata» da qualcuno, un anno dopo.
           q.corrected_distance_m IS NOT NULL              AS distance_corrected,
           coalesce(q.status, 'valid')  AS quality_status,
           q.reason                     AS quality_reason,
           q.confirmed_on               AS quality_confirmed_on,
           date_diff('second',
                     lag(a.start_time_utc + to_seconds(coalesce(a.duration_s, 0)::BIGINT))
                         OVER (PARTITION BY a.activity_date, a.sport
                               ORDER BY a.start_time_utc),
                     a.start_time_utc)  AS gap_from_previous_s
    FROM activities a
    LEFT JOIN activity_quality q ON q.activity_id = a.activity_id
    WHERE coalesce(q.status, 'valid') <> 'exclude'
),
raggruppate AS (
    SELECT *,
           sum(CASE WHEN gap_from_previous_s IS NULL
                         OR gap_from_previous_s >= 180 THEN 1 ELSE 0 END)
               OVER (PARTITION BY activity_date, sport
                     ORDER BY start_time_utc
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
               AS session_ordinal
    FROM scoperte
)
SELECT *,
       activity_date::VARCHAR || '·' || sport || '·' || session_ordinal::VARCHAR
           AS session_key
FROM raggruppate;
