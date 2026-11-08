"""I criteri di accettazione della Fase 1, eseguibili.

Il piano dice che una fase non è finita finché i suoi criteri non sono
soddisfatti, anche se il codice gira. Questo modulo li trasforma da frasi in
controlli che restituiscono vero o falso.

Riferimento: ``docs/CONTESTO-OPERATIVO.md`` §14, controlli C1-C6d.

## Perché i conteggi si fermano al 4 luglio 2026

I criteri sono nati quando l'unica sorgente era ``garmin-export/``, e
confrontavano numeri esatti. Dalla Fase 3 il sync aggiunge attività ogni volta
che l'atleta nuota: un criterio che fallisce perché sono arrivati dati nuovi
non sta più verificando niente, sta solo abbaiando.

I conteggi si applicano quindi al **periodo coperto dall'export**, che è chiuso
e non deve più cambiare. Non contano *chi* ha scritto la riga: il sync riscrive
di proposito gli ultimi giorni, perché Garmin corregge i dati del giorno prima,
e due sedute a cavallo del 4 luglio portano ormai la firma di Garmin Connect
invece che quella del file. La domanda a cui il criterio risponde non è "da
dove viene questa riga" ma "manca qualcosa di quello che c'era".
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .database import table_exists

# Attesi misurati sull'export il 2026-08-16 e riportati in docs/SCOPERTE-DATI.md.
EXPECTED_ACTIVITIES = 1471
EXPECTED_SWIMS = 1306
EXPECTED_POOL = 1207
EXPECTED_OPEN_WATER = 99
EXPECTED_SWIMS_BY_YEAR = {
    2017: 71, 2018: 183, 2019: 118, 2020: 88, 2021: 109,
    2022: 160, 2023: 165, 2024: 188, 2025: 110, 2026: 114,
}
MIN_DAILY_STATUS_DAYS = 2900

# Ultimo giorno coperto dall'export Garmin del 2026-08-16. Oltre questa data i
# dati arrivano dal sync e i conteggi non sono più confrontabili con un atteso.
EXPORT_LAST_DAY = "2026-07-04"
FROM_EXPORT = f"activity_date <= DATE '{EXPORT_LAST_DAY}'"

# Quota minima di sedute il cui dettaglio FIT combacia col riepilogo. Non è 100%:
# su quattro sedute su 1.167 l'orologio conta nel totale qualche vasca che poi
# non compare in nessun lap. Sono 0,3%, si vedono per data nel controllo, e
# fingere che non esistano sarebbe peggio che dichiararle.
MIN_DETAIL_AGREEMENT = 0.99

# Oltre questa velocità istantanea non c'è nuoto. Il record mondiale sui 50
# stile — 20,91 s — corrisponde a 2,39 m/s di media, e la velocità di picco
# dentro quella vasca è più alta; il novantesimo percentile di questo atleta è
# 2,14. Tre metri al secondo lascia margine a un nuotatore e non a un satellite.
MAX_HUMAN_SWIM_SPEED_MS = 3.0


@dataclass(frozen=True)
class Check:
    identifier: str
    description: str
    expected: object
    actual: object
    passed: bool


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str,
            parametri: list | None = None) -> object:
    return connection.execute(sql, parametri or []).fetchone()[0]


def run_checks(connection: duckdb.DuckDBPyConnection) -> list[Check]:
    checks: list[Check] = []

    def add(identifier: str, description: str, expected: object, actual: object,
            passed: bool | None = None) -> None:
        checks.append(Check(identifier, description, expected, actual,
                            expected == actual if passed is None else passed))

    add("C1", "Attività fino al 4 luglio 2026", EXPECTED_ACTIVITIES,
        _scalar(connection, f"SELECT count(*) FROM activities WHERE {FROM_EXPORT}"))

    add("C2", "Sedute di nuoto fino al 4 luglio 2026", EXPECTED_SWIMS,
        _scalar(connection,
                f"SELECT count(*) FROM activities WHERE is_swim AND {FROM_EXPORT}"))

    add("C3", "Sedute in piscina fino al 4 luglio 2026", EXPECTED_POOL,
        _scalar(connection, "SELECT count(*) FROM activities "
                            f"WHERE sport = 'lap_swimming' AND {FROM_EXPORT}"))

    add("C4", "Sedute in acque libere fino al 4 luglio 2026", EXPECTED_OPEN_WATER,
        _scalar(connection, "SELECT count(*) FROM activities "
                            f"WHERE sport = 'open_water_swimming' AND {FROM_EXPORT}"))

    by_year = dict(connection.execute(
        "SELECT year(activity_date), count(*) FROM activities "
        f"WHERE is_swim AND {FROM_EXPORT} GROUP BY 1 ORDER BY 1").fetchall())
    add("C5", "Distribuzione annuale del nuoto fino al 4 luglio 2026",
        EXPECTED_SWIMS_BY_YEAR, by_year)

    # Non un criterio ma un dato da vedere: quanto è cresciuto l'archivio dopo
    # l'export. Passa sempre — serve a leggere gli altri numeri, non a giudicarli.
    from_sync = _scalar(connection,
                        f"SELECT count(*) FROM activities WHERE NOT ({FROM_EXPORT})")
    add("C5b", "Attività successive al 4 luglio 2026, arrivate col sync",
        "qualunque", from_sync, passed=True)

    days = _scalar(connection, "SELECT count(*) FROM daily_status")
    add("C6", f"daily_status popolata (almeno {MIN_DAILY_STATUS_DAYS} giorni)",
        f">= {MIN_DAILY_STATUS_DAYS}", days, passed=bool(days) and days >= MIN_DAILY_STATUS_DAYS)

    # C6d — origine diretta. Ogni riga deve risalire a un file dell'export, e
    # nessuna al vecchio database.
    tables = ["activities", "daily_health", "sleep", "health_status",
              "garmin_training_load", "garmin_training_status",
              "garmin_readiness", "body_metrics", "hr_zones"]
    orphans = {}
    for table in tables:
        missing = _scalar(connection, f"SELECT count(*) FROM {table} "
                                      "WHERE source_object_id IS NULL OR source_object_id = ''")
        if missing:
            orphans[table] = missing
    add("C6d.1", "Ogni riga importata ha una provenienza", {}, orphans)

    # Le sorgenti ammesse sono due: l'export locale e — dalla Fase 3 — Garmin
    # Connect. Qualunque altra origine, in particolare il vecchio database,
    # farebbe fallire questo controllo.
    foreign = _scalar(connection,
                      "SELECT count(*) FROM import_log "
                      "WHERE source_path NOT LIKE 'garmin-export/%' "
                      "  AND source_path NOT LIKE 'garmin-connect://%'")
    add("C6d.2", "Ogni sorgente è l'export locale o Garmin Connect", 0, foreign)

    # Controllo di coerenza interna: il totale dei metri nuotati non deve
    # cambiare fra ciò che conta come nuotata e la tabella giornaliera.
    #
    # Il confronto è con la vista, non con il raw. Da quando esistono le
    # correzioni confermate dall'atleta i due numeri **devono** differire — è il
    # senso stesso dell'esclusione — e confrontare il raw con il derivato
    # farebbe fallire il criterio esattamente quando la correzione funziona.
    #
    # Il riferimento è `counted_swims` e non `canonical_activities`: in mare
    # l'orologio spesso non è ammesso, e le gare dei giorni che non ha
    # registrato sono nuotate a tutti gli effetti (migrazione 0016). Misurare
    # `daily_status` contro le sole attività lo farebbe fallire di 25.052 m,
    # cioè esattamente della quantità che il criterio dovrebbe difendere.
    from_swims = _scalar(
        connection, "SELECT round(sum(distance_m)) FROM counted_swims")
    from_daily = _scalar(connection,
                         "SELECT round(sum(swim_distance_m)) FROM daily_status")
    add("C6e", "Metri nuotati coerenti fra counted_swims e daily_status",
        from_swims, from_daily)

    # ── Fase 5 — serie e vasche ────────────────────────────────────────────
    # I controlli si applicano solo se la Fase 5 è stata eseguita: prima non
    # esiste niente da verificare, e un controllo fallito su una tabella vuota
    # direbbe che il progetto è rotto quando invece non è ancora arrivato lì.
    if _scalar(connection, "SELECT count(*) FROM activity_laps"):
        # C7a — il dettaglio deve raccontare la stessa seduta del riepilogo.
        # È la prova che l'aggancio FIT↔attività è quello giusto: se un file
        # finisse sulla seduta sbagliata, i metri non tornerebbero.
        agreeing, total = connection.execute("""
            SELECT count(*) FILTER (WHERE abs(a.distance_m - s.d) <= 25), count(*)
            FROM activities a
            JOIN (SELECT activity_id, sum(distance_m) AS d
                  FROM activity_laps WHERE NOT is_rest GROUP BY 1) s
              ON s.activity_id = a.activity_id
        """).fetchone()
        share = agreeing / total if total else 0
        divergent = [f"{day} — seduta {summary:,.0f} m, ripetute {detail:,.0f} m"
                     for day, summary, detail in connection.execute("""
                        SELECT a.activity_date, a.distance_m, s.d
                        FROM activities a
                        JOIN (SELECT activity_id, sum(distance_m) AS d
                              FROM activity_laps WHERE NOT is_rest GROUP BY 1) s
                          ON s.activity_id = a.activity_id
                        WHERE abs(a.distance_m - s.d) > 25
                        ORDER BY a.activity_date""").fetchall()]
        add("C7a", "I metri delle ripetute coincidono con quelli della seduta "
                   f"(almeno {MIN_DETAIL_AGREEMENT:.0%}, tolleranza una vasca)",
            f">= {MIN_DETAIL_AGREEMENT:.0%}",
            f"{share:.1%} ({agreeing:,}/{total:,})"
            + (f" — divergenti: {'; '.join(divergent)}" if divergent else ""),
            passed=share >= MIN_DETAIL_AGREEMENT)

        # C7b — nessuna riga duplicata. Le tabelle si ricostruiscono da zero,
        # ma la chiave primaria non basta a dire che l'indice del FIT è stato
        # letto correttamente.
        duplicates = _scalar(connection, """
            SELECT count(*) FROM (
                SELECT activity_id, lap_index FROM activity_laps
                GROUP BY 1, 2 HAVING count(*) > 1)""")
        add("C7b", "Nessuna ripetuta duplicata", 0, duplicates)

        # C7c — ogni vasca appartiene a una ripetuta esistente.
        orphan_lengths = _scalar(connection, """
            SELECT count(*) FROM pool_lengths l
            WHERE l.lap_index IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM activity_laps s
                WHERE s.activity_id = l.activity_id AND s.lap_index = l.lap_index)""")
        add("C7c", "Ogni vasca appartiene a una ripetuta della stessa seduta",
            0, orphan_lengths)

        # C7d — il recupero non porta stile. Attribuirgliene uno gonfierebbe i
        # totali per stile con metri mai nuotati.
        rest_with_stroke = _scalar(connection,
            "SELECT count(*) FROM activity_laps WHERE is_rest AND stroke IS NOT NULL")
        add("C7d", "Nessun recupero contrabbandato come nuotata", 0, rest_with_stroke)

        # ── D2/D5 — provenienza e verdetti ────────────────────────────────
        # Criterio 6: il 100% delle righe granulari risale a source_objects.
        # Una riga senza sorgente è un numero di cui nessuno sa rispondere
        # "da dove viene", ed è la domanda che tutta la Macro-proposta 3 esiste
        # per poter soddisfare.
        for table in ("activity_laps", "pool_lengths"):
            orphans = _scalar(connection, f"""
                SELECT count(*) FROM {table} r
                WHERE r.source_object_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM source_objects s
                    WHERE s.source_object_id = r.source_object_id)""")
            add(f"C8a.{table}", f"Ogni riga di {table} risale a una sorgente",
                0, orphans)

        # Criterio 7: sha256 contiene soltanto hash veri.
        fake_hashes = _scalar(connection,
            "SELECT count(*) FROM source_objects "
            "WHERE length(sha256) <> 64 OR sha256 !~ '^[0-9a-f]+$'")
        add("C8b", "Ogni sha256 del catalogo è un vero SHA-256", 0, fake_hashes)

        # Criterio 9: ogni mancata associazione ha un codice.
        #
        # Limitato alle sedute che `details` ha potuto vedere. Senza questo
        # limite il criterio falliva **il giorno stesso in cui l'atleta
        # nuotava**: il sync scrive la seduta di oggi, `details` non è ancora
        # passato, e nessun verdetto esiste. Peggio, l'unico rimedio era un
        # comando che si rompeva con un KeyError prima di arrivare in fondo,
        # quindi la strada per tornare verdi non esisteva.
        #
        # Un criterio che fallisce per il passare del tempo insegna a ignorarlo,
        # ed è il modo in cui muore un insieme di controlli.
        ultimo_details = _scalar(connection, """
            SELECT max(started_at) FROM ingest_runs WHERE command = 'details'
            """) if table_exists(connection, "ingest_runs") else None
        unexplained = _scalar(connection, f"""
            SELECT count(*) FROM activities a
            WHERE a.is_swim AND NOT EXISTS (
                SELECT 1 FROM activity_source_matches m
                WHERE m.activity_id = a.activity_id)
              {"AND a.imported_at <= TIMESTAMP '" + str(ultimo_details) + "'"
               if ultimo_details else ""}""")
        add("C8c", "Ogni seduta vista da 'details' ha un verdetto", 0, unexplained)

        # Un aggancio incerto non deve entrare nelle analisi come certo.
        ambiguous_with_data = _scalar(connection, """
            SELECT count(DISTINCT l.activity_id) FROM activity_laps l
            WHERE EXISTS (SELECT 1 FROM activity_source_matches m
                          WHERE m.activity_id = l.activity_id
                            AND m.verdict = 'ambiguous')""")
        add("C8d", "Nessun match ambiguo è entrato nei dati", 0, ambiguous_with_data)

        # Criterio 11: in mare le vasche non esistono, e non devono comparire.
        sea_lengths = _scalar(connection, """
            SELECT count(*) FROM pool_lengths l
            JOIN activities a ON a.activity_id = l.activity_id
            WHERE a.environment <> 'pool'""")
        add("C8e", "Nessuna vasca inventata in acque libere", 0, sea_lengths)

    # C9 — la provenienza ha due forme lecite, e nessuna terza.
    #
    # Prima della migrazione 0005, 192 righe portavano un URI dentro una colonna
    # chiamata `source_sha`. Rinominare la colonna toglie la bugia dal nome; questo
    # criterio impedisce che rientri dal contenuto. Le forme ammesse sono lo
    # SHA-256 di un file dell'export e un URI con schema dichiarato: qualunque
    # altra cosa è una sorgente che nessuno sa più risalire (Regola Aurea n.5).
    # Solo le dieci tabelle che portano la provenienza **diretta**, cioè quelle
    # rinominate dalla migrazione 0005. `activity_laps` e `pool_lengths` non
    # sono qui perché la loro provenienza è un riferimento al catalogo, e che
    # risolva davvero lo prova C8a — che è un controllo più forte di questo.
    provenance_tables = [
        "activities", "body_metrics", "daily_health", "garmin_readiness",
        "garmin_training_load", "garmin_training_status", "health_status",
        "hr_zones", "sleep", "import_log",
    ]
    malformed: dict[str, int] = {}
    for table in provenance_tables:
        if not table_exists(connection, table):
            continue
        bad = _scalar(connection, f"""
            SELECT count(*) FROM {table}
            WHERE source_object_id IS NOT NULL
              AND NOT source_object_id ~ '^[0-9a-f]{{64}}$'
              AND NOT source_object_id ~ '^(garmin-connect|fit)://.+'""")
        if bad:
            malformed[table] = bad
    add("C9", "La provenienza è uno SHA-256 o un URI riconosciuto, mai altro",
        {}, malformed)

    add("C10", "Ogni giorno catturato dal sync è ancora nel database",
        {}, _days_captured_but_missing(connection))

    # C11 — le decisioni dell'atleta sono davvero applicate.
    #
    # Un'esclusione scritta in `coach/correzioni-dati.md` e non arrivata in
    # `activity_quality` è la peggiore delle due situazioni possibili: l'atleta
    # crede di aver tolto quel record e il record continua a pesare. Meglio
    # nessuna correzione che una correzione che sembra applicata.
    add("C11", "Ogni correzione confermata dall'atleta è applicata",
        [], _corrections_not_applied(connection))

    # C12 — velocità che nessun essere umano raggiunge.
    #
    # `max_speed_ms` arriva a 100,33 m/s sul 6 km di place03 del 26/08/2023 —
    # 361 km/h — e a 45,36 il 30/07/2023. Sono picchi del GPS.
    #
    # Il picco non invalida l'attività: place03 è 6.000 m a 1:26,7, una
    # prestazione vera. Il difetto sta nel campo, non nella seduta, e annullare
    # il valore distruggerebbe il fatto che Garmin lo ha registrato.
    #
    # Oggi nessuna analisi legge questo campo, quindi non contamina niente. Ma
    # sta nel database senza nessuna segnalazione, e la prima analisi che lo
    # userà lo userà rotto. Contarlo lo tiene visibile finché qualcuno non
    # decide cosa farne.
    add("C12", "Nessuna velocità massima oltre il possibile umano", 0,
        _scalar(connection,
                "SELECT count(*) FROM activities WHERE is_swim "
                f"AND max_speed_ms > {MAX_HUMAN_SWIM_SPEED_MS}"))

    # C13 — le gare della federazione sono tutte entrate.
    #
    # La sorgente è un CSV scaricato a mano, quindi può cambiare senza che
    # nessuno lo sappia: una colonna rinominata farebbe entrare zero righe e
    # l'unico segno sarebbe una pagina Gare vuota, che assomiglia a «non hai
    # ancora gareggiato». Questo criterio conta le righe del file e le confronta
    # con quelle in archivio, tolti i due doppioni noti della sorgente.
    if table_exists(connection, "races"):
        # Il conteggio è **per sorgente**, non per ambiente. Contare le gare in
        # vasca funzionava finché la vasca era una sorgente sola; con tre
        # importatori una gara dichiarata dall'atleta in piscina finirebbe nel
        # conto della federazione, e il criterio fallirebbe segnalando un
        # guasto che non c'è. È successo il 23/08/2026 su C14.
        add("C13", "Ogni gara del file della federazione è in archivio",
            _races_in_files(), _races_from(connection, "aquatime"))

        # C14 — le gare in mare sono tutte entrate.
        #
        # Stesso ragionamento di C13 su una sorgente diversa. Serve un criterio
        # suo e non un conteggio unico: le due sorgenti si importano con codice
        # diverso, e un totale che torna può nascondere venticinque righe in
        # meno da una parte e venticinque in più dall'altra.
        add("C14", "Ogni gara in acque libere del file Icron è in archivio",
            _open_water_in_files(), _races_from(connection, "icron"))

        # C15 — ogni gara dichiara dove è stata nuotata.
        #
        # Questo criterio nasce da un guasto vero, trovato il 23/08/2026. La
        # migrazione 0009 riempie `environment` per le righe già in archivio;
        # l'importatore della federazione, che cancella e riscrive le proprie
        # righe a ogni `ingest`, le riscriveva senza. Risultato: 114 gare con
        # `environment` a NULL, la vista `pool_races` vuota, i record spariti e
        # la velocità critica «non calcolabile» — senza nessun errore.
        #
        # Una colonna che vale NULL dove il codice si aspetta due valori è il
        # tipo di guasto che non si vede: non rompe niente, cambia solo tutte
        # le risposte.
        # C17 — le gare dichiarate dall'atleta sono tutte in archivio.
        #
        # Nasce dallo stesso motivo di C13 e C14, su una sorgente che l'atleta
        # scrive a mano: una riga compilata male sparirebbe in silenzio, e su
        # una gara che si ricorda di aver nuotato il silenzio e' il modo
        # peggiore di rispondere.
        add("C17", "Ogni gara dichiarata dall'atleta e' in archivio",
            _declared_races_in_file(),
            _races_from(connection, "declared_races"))

        add("C15", "Ogni gara dichiara ambiente e origine della distanza", 0,
            _scalar(connection,
                    "SELECT count(*) FROM races WHERE environment IS NULL "
                    "OR (distance_m IS NOT NULL AND distance_source IS NULL)"))

        # C18 — il collegamento fra una gara e la nuotata che la registra
        # arriva davvero in archivio.
        #
        # Nasce da un guasto vero, trovato il 24/08/2026: la colonna «Seduta
        # Garmin» esisteva nel markdown dal 23/08, l'importatore la leggeva, la
        # metteva in `DeclaredRace.activity_id` e la **contava nel rapporto
        # finale** come `linked_to_garmin`. Poi la buttava, perché `races` non
        # aveva una colonna dove metterla.
        #
        # È il guasto più difficile da vedere di tutti: il numero stampato a
        # fine import era giusto. Diceva quante righe del file avevano un
        # collegamento, non quante ne erano arrivate nel database — e nessuno
        # aveva motivo di sospettare che fossero due domande diverse.
        #
        # Il criterio confronta perciò le due cose che quel rapporto
        # confondeva: quante il file ne dichiara, quante il database ne ha.
        add("C18", "Ogni gara collegata a una seduta Garmin ha il collegamento "
            "in archivio",
            _declared_races_linked(),
            _scalar(connection,
                    "SELECT count(*) FROM races r "
                    "JOIN source_objects s USING (source_object_id) "
                    "WHERE s.parser = 'declared_races' "
                    "  AND r.activity_id IS NOT NULL"))

        # C19 — nessuna gara in mare resta a decidersi da sola.
        #
        # Nasce dal criterio sbagliato della migrazione 0016, che deduceva dal
        # giorno: se quel giorno l'orologio aveva registrato una nuotata, la
        # gara non contava. L'atleta l'ha smontato il 25/08/2026 — la gara era a
        # place04 la mattina, l'allenamento a place03 alle [orario], cento chilometri
        # più in là — e ha mostrato anche l'errore opposto: il 19/05/2018 due
        # gare e una sola nuotata registrata, perché l'orologio era ammesso solo
        # in una. Una nuotata può essere al massimo **una** gara.
        #
        # Nessuna regola sul giorno regge. Quando una gara condivide la data con
        # una nuotata, la decisione la prende una persona guardando luogo, ora e
        # durata, e la scrive in `coach/correzioni-gare.md`.
        #
        # Questo criterio non verifica un calcolo: verifica che non ne sia stato
        # fatto uno al posto dell'atleta. Se vale più di zero, ci sono gare che
        # il programma sta contando o scartando senza saperlo.
        if table_exists(connection, "race_quality"):
            from . import race_corrections
            add("C19", "Ogni gara in mare che condivide il giorno con una "
                "nuotata ha un verdetto dell'atleta",
                0, len(race_corrections.unexamined(connection)))

            # C20 — una correzione punta a una gara che esiste davvero.
            #
            # Il race id si scrive a mano in `coach/correzioni-gare.md`, ed è
            # lungo e pieno di trattini. Sbagliarne uno non dà nessun errore:
            # la riga viene letta, applicata a una gara che non c'è, e la gara
            # vera resta com'era. L'atleta crede di aver corretto e i conti non
            # cambiano — lo stesso guasto silenzioso che ha fatto nascere C18.
            esistenti = {riga[0] for riga in connection.execute(
                "SELECT race_id FROM races").fetchall()}
            add("C20", "Ogni correzione sulle gare punta a una gara in archivio",
                0, sum(1 for una in race_corrections.declared()
                       if una.race_id not in esistenti))

    # C16 — i tempi in zona cardiaca stanno dentro la durata della seduta.
    #
    # Nasce da un guasto trovato il 23/08/2026: le colonne `hr_zone_*_s`
    # contenevano millisecondi, e la somma delle sei zone dava 992 volte la
    # durata. Era in archivio dalla Fase 1 e non se n'era accorto nessuno,
    # perché nessuna analisi leggeva quelle colonne.
    #
    # Il controllo è banale e per questo funziona: la somma del tempo passato
    # nelle zone non può superare il tempo della seduta. Un margine del 5%
    # copre gli arrotondamenti di Garmin; mille volte tanto no.
    add("C16", "Il tempo in zona cardiaca non supera la durata della seduta", 0,
        _scalar(connection, """
            SELECT count(*) FROM activities
            WHERE hr_zone_1_s IS NOT NULL AND duration_s > 0
              AND coalesce(hr_zone_0_s, 0) + coalesce(hr_zone_1_s, 0)
                + coalesce(hr_zone_2_s, 0) + coalesce(hr_zone_3_s, 0)
                + coalesce(hr_zone_4_s, 0) + coalesce(hr_zone_5_s, 0)
                > duration_s * 1.05
        """))

    return checks


def _races_from(connection: duckdb.DuckDBPyConnection, parser: str) -> int:
    """Quante gare in archivio appartengono a una sorgente.

    Le tre sorgenti di gare si contano ognuna sulle proprie righe, tramite il
    catalogo delle sorgenti. Un totale che torna può nascondere righe in meno
    da una parte e in più dall'altra, e un conteggio per ambiente confonde le
    sorgenti fra loro appena due ne condividono uno.
    """
    return _scalar(connection, """
        SELECT count(*) FROM races r
        JOIN source_objects s USING (source_object_id)
        WHERE s.parser = ?
    """, [parser])


def _races_in_files() -> int:
    """Quante gare distinte contengono i file dell'atleta, contate lì.

    Distinte e non totali: la sorgente ripete due righe identiche — stesso
    `event_id`, stesso tempo, 08/11/2015 e 14/01/2018 — e sono un artefatto di
    come è stata raccolta, non due gare. Contarle qui allo stesso modo in cui le
    conta l'importatore è ciò che rende il criterio un confronto e non una
    ripetizione della stessa funzione.
    """
    from .ingest import aquatime

    distinte = set()
    for percorso in aquatime._files(aquatime.RACES_SUFFIX):
        for riga in aquatime._rows(percorso):
            giorno = aquatime.parse_day(riga.get("data", ""))
            etichetta = (riga.get("tipo") or "").strip()
            if giorno and etichetta and aquatime.parse_pool(riga.get("vasca", "")):
                distinte.add(aquatime.race_id(
                    giorno, riga.get("event_id", ""), etichetta))
    return len(distinte)


def _open_water_in_files() -> int:
    """Quante nuotate distinte contiene il file Icron, contate lì.

    Distinte perché la sorgente espone lo stesso risultato una volta per ogni
    graduatoria in cui compare: il 12/09/2020 c'è due volte, in
    `AGONISTI_REGIONE` e in `AGONISTI`, con lo stesso tempo. È una nuotata.
    """
    from .ingest import icron

    distinte = set()
    for percorso in icron._files():
        for riga in icron._rows(percorso):
            giorno = icron.parse_day(riga.get("data", ""))
            manifestazione = (riga.get("gara") or "").strip()
            if giorno and manifestazione:
                distanza = icron.parse_distance(
                    riga.get("prova", ""), manifestazione)
                distinte.add((giorno, manifestazione.upper(),
                              icron.parse_time(riga.get("tempo_originale", "")),
                              distanza.metres))
    return len(distinte)


def _declared_races_in_file() -> int:
    """Quante gare l'atleta ha dichiarato, contate nel suo file."""
    from .ingest import declared_races

    return len(declared_races.declared())


def _declared_races_linked() -> int:
    """Quante gare dichiarate portano un collegamento a una seduta Garmin."""
    from .ingest import declared_races

    return sum(1 for una in declared_races.declared() if una.activity_id)


def _corrections_not_applied(connection: duckdb.DuckDBPyConnection) -> list:
    from . import corrections

    if not table_exists(connection, "activity_quality"):
        return ["la tabella delle correzioni non esiste in questo database"]
    applicate = {riga[0]: riga[1:] for riga in connection.execute(
        "SELECT activity_id, status, scope, reason, confirmed_on, decided_by "
        "FROM activity_quality").fetchall()}
    problemi = []
    for una in corrections.declared():
        attesa = (una.status, una.scope, una.reason, una.confirmed_on, "athlete")
        effettiva = applicate.get(una.activity_id)
        if effettiva is None:
            problemi.append(
                f"{una.activity_id} ({una.status}) non è applicata")
        elif effettiva != attesa:
            problemi.append(
                f"{una.activity_id}: decisione applicata diversa da quella dichiarata")
    return problemi


def _days_captured_but_missing(connection: duckdb.DuckDBPyConnection) -> dict:
    """I giorni che il sync ha scaricato e che il database non ha più.

    ## Perché serviva proprio questo, e non un conteggio in più

    I criteri C1-C5 contano le righe **fino al 4 luglio 2026**, il giorno in cui
    l'export si ferma. È una scelta giusta — oltre quella data i conteggi non
    sono confrontabili con un atteso — ma ha un effetto che nessuno aveva visto:
    cancellare tutto ciò che viene dopo il 4 luglio riporta l'archivio
    *esattamente* al valore atteso. Quando ``all`` ha accorciato il database di
    37 attività, ``verify`` non è rimasto cieco: è diventato verde **perché** i
    dati erano stati persi.

    Mancava un pavimento. Questo criterio lo mette senza inventare uno stato
    nuovo da mantenere: le catture in ``data/raw/garmin-connect/`` sono già la
    prova di cosa il sync ha ottenuto, sono append-only, e un giorno catturato
    che non compare più nel database è una perdita, non una differenza di
    opinioni.

    Non pretende che ogni giorno catturato abbia dei dati: un giorno senza
    orologio al polso esiste e non ha niente. Pretende che se la cattura
    contiene un riepilogo, il database abbia quel giorno.
    """
    import json

    from .ingest.source_catalog import RAW

    if not RAW.exists() or not table_exists(connection, "daily_health"):
        return {}

    mancanti: dict[str, str] = {}
    for cartella in sorted(RAW.iterdir()):
        cattura = cartella / "get_user_summary.json"
        if not cartella.is_dir() or not cattura.exists():
            continue
        try:
            payload = json.loads(cattura.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not payload:
            continue      # Garmin non aveva niente per quel giorno: legittimo
        presente = _scalar(connection,
                           "SELECT count(*) FROM daily_health "
                           f"WHERE health_date = DATE '{cartella.name}'")
        if not presente:
            mancanti[cartella.name] = "catturato dal sync, assente dal database"
    return mancanti
