-- Una seduta è quello che hai nuotato, non quello che l'orologio ha registrato.
--
-- L'orologio si ferma e riparte: una chiamata, un cambio di vasca, un tasto
-- premuto per sbaglio. Una sola nuotata arriva nel database come due o tre
-- attività separate, e ogni conteggio «sedute» le tratta come distinte.
--
-- Misurato sull'archivio: fino a sei registrazioni di nuoto nello stesso giorno
-- (05/09/2017, sei per 825 m in totale). Su 86 intervalli fra registrazioni
-- consecutive dello stesso giorno, undici sono sotto il minuto.
--
-- La soglia è di tre minuti, e non è statistica: è il tempo minimo per uscire
-- dall'acqua, fare un'altra cosa e rientrare. Sotto, è un orologio fermato e
-- riacceso. Sopra — una doppia seduta mattina e sera — restano due, perché
-- unirle sarebbe l'errore opposto, e più difficile da vedere: toglie invece di
-- aggiungere.
--
-- Il raggruppamento sta nella vista e non in una tabella perché è una lettura
-- dei dati, non un fatto nuovo: cambia da sé se cambia un timestamp, e non c'è
-- niente da tenere allineato.

CREATE OR REPLACE VIEW canonical_activities AS
WITH scoperte AS (
    SELECT a.*,
           coalesce(q.status, 'valid')  AS quality_status,
           q.reason                     AS quality_reason,
           q.confirmed_on               AS quality_confirmed_on,
           -- Quanto tempo è passato dalla fine della registrazione precedente
           -- dello stesso giorno e dello stesso sport. NULL sulla prima.
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
           -- Un contatore che avanza solo quando l'intervallo supera la soglia:
           -- tutte le registrazioni con lo stesso valore sono la stessa seduta.
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
