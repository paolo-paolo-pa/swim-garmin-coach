-- Lo strato fra ciò che Garmin ha registrato e ciò che l'atleta ha fatto.
--
-- Un'attività può essere formalmente perfetta e non descrivere un allenamento.
-- Il caso che ha reso necessario questo strato: 25.824 m registrati a place20 il
-- 20/09/2025, con riepilogo e file FIT in accordo numerico esatto, e dentro il
-- FIT 2.306 bracciate in totale, cadenza 8, 11,2 m per bracciata. Un'attività
-- mista, o l'orologio rimasto acceso: non una prestazione.
--
-- Il raw non si tocca — è la Regola Aurea n.4, e serve anche a poter cambiare
-- idea. La decisione umana vive in `coach/correzioni-dati.md`, che è markdown
-- perché è un'intenzione e non un fatto misurato (Regola Aurea n.3), e da lì
-- entra qui a ogni import. Questa tabella è derivata: si cancella e si riottiene.

CREATE TABLE IF NOT EXISTS activity_quality (
    activity_id    BIGINT PRIMARY KEY,
    status         VARCHAR NOT NULL,   -- exclude | correct | keep | review
    scope          VARCHAR,            -- a cosa si applica, in parole dell'atleta
    reason         VARCHAR NOT NULL,   -- perché: resta con la decisione, sempre
    confirmed_on   DATE,
    decided_by     VARCHAR NOT NULL,   -- athlete | automatic
    applied_at     TIMESTAMP NOT NULL
);

-- La vista che ogni analisi interroga al posto di `activities`.
--
-- Non è una comodità: è il punto in cui la decisione dell'atleta diventa
-- inevitabile. Una funzione che interroga `activities` direttamente riporta
-- dentro ciò che è stato escluso, e lo fa in silenzio — il test contrattuale in
-- `test_athlete_corrections.py` esiste per questo.
--
-- `review` resta dentro: significa "non ancora verificata", non "falsa", e
-- toglierla dai totali sarebbe una decisione che nessuno ha preso. Le
-- conclusioni forti la escludono guardando `quality_status`.
CREATE OR REPLACE VIEW canonical_activities AS
SELECT a.*,
       coalesce(q.status, 'valid')  AS quality_status,
       q.reason                     AS quality_reason,
       q.confirmed_on               AS quality_confirmed_on
FROM activities a
LEFT JOIN activity_quality q ON q.activity_id = a.activity_id
WHERE coalesce(q.status, 'valid') <> 'exclude';
