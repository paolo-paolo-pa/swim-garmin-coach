"""Che cosa contiene ogni tabella, e che cosa rappresenta una sua riga (D1).

## Perché è generato e non scritto

Un dizionario dati scritto a mano diverge dal database al primo cambiamento, e
da quel momento è peggio di niente: dice con sicurezza una cosa falsa. Questo
lo genera dallo schema reale e prende dalle descrizioni qui sotto solo la parte
che una macchina non può sapere — che cosa *significa* una riga.

Un test verifica che le due metà combacino: se aggiungi una tabella e non la
descrivi, il test fallisce. Se descrivi una tabella che non esiste, uguale.
È il «test che confronta schema reale e contratto dichiarato» del cancello D1.

## Le quattro classi del dato

La distinzione più importante del progetto, e quella che si perde più
facilmente quando i numeri finiscono tutti nella stessa tabella:

- ``measured`` — misurato da un sensore e conservato come arrivato;
- ``garmin_proprietary`` — calcolato da Garmin con una formula che non
  conosciamo. Si espone col nome di Garmin, senza rivendicarlo;
- ``calculated`` — calcolato qui, da una funzione deterministica e testata;
- ``inferred`` — dedotto con un metodo che può sbagliare, e che deve poter
  dire «non riconosciuto».
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class TableDoc:
    row_means: str          # che cosa rappresenta UNA riga
    key: str
    source: str
    data_class: str
    note: str = ""
    derived: bool = False
    """Vera per le tabelle che nascono da un calcolo invece che da una
    migrazione. La loro forma è definita dalla query che le costruisce:
    dichiararla anche in una migrazione creerebbe due verità sulla stessa
    tabella, ed è la seconda a mentire appena la query cambia."""


# Ordinate come si leggono, non alfabeticamente: prima i fatti, poi il derivato,
# poi la tracciabilità.
TABLES: dict[str, TableDoc] = {
    "health_samples": TableDoc(
        "un campione fisiologico intragiornaliero Garmin, con valore mancante conservato",
        "sample_date + metric + observed_at (UTC)",
        "snapshot Personal API heartRateValues/bodyBatteryValuesArray",
        "measured + garmin_proprietary",
        "Nessuna interpolazione. Valori sentinella restano NULL; Body Battery zero è valido. Sorgente nel catalogo."),
    "health_sample_imports": TableDoc(
        "lo stato dell'ultima acquisizione di un giorno e una famiglia di campioni",
        "sample_date + metric", "snapshot Personal API conservato localmente", "calculated",
        "Cache di sincronizzazione e freschezza; non è una misura della salute."),
    "activities": TableDoc(
        "una sessione registrata dall'orologio, di qualunque sport",
        "activity_id (Garmin)",
        "summarizedActivities.json dell'export, e Garmin Connect per i giorni recenti",
        "measured + garmin_proprietary",
        "Il riepilogo, non il dettaglio. Le colonne garmin_* sono di Garmin: "
        "esposte, mai ricalcolate."),

    "activity_laps": TableDoc(
        "un lap registrato dal dispositivo",
        "activity_id + lap_index",
        "messaggio FIT 'lap'",
        "measured",
        "NON è una serie di allenamento. Un lap è quello che l'orologio ha "
        "segnato; '8×100' è un'interpretazione che vive altrove."),

    "pool_lengths": TableDoc(
        "una vasca percorsa, attiva o di riposo",
        "activity_id + length_index",
        "messaggio FIT 'length'",
        "measured",
        "Solo piscina. In acque libere il concetto non esiste: assenza = "
        "not_applicable, non dato mancante."),

    "activity_track": TableDoc(
        "un punto registrato durante una nuotata in mare o una gara",
        "activity_id + point_index",
        "messaggio FIT 'record'",
        "measured",
        "Solo acque libere e gare: del martedì in vasca interessa il totale, e "
        "il dettaglio è già nelle vasche. **Nessuna coordinata**: di una "
        "posizione assoluta queste analisi non fanno niente, e servono due "
        "differenze fra punti — quanto si è percorso (`segment_m`) e in che "
        "direzione (`heading_deg`). Il segmento esiste solo fra due fix "
        "consecutivi: dopo un buco del GPS la retta fra i due estremi non è il "
        "tratto nuotato."),

    "activity_track_quality": TableDoc(
        "il verdetto su quanto la traccia di una nuotata regge una lettura a tratti",
        "activity_id",
        "calcolata da activity_track e dalla distanza dell'orologio",
        "calculated",
        "Il cancello vive in tabella e non in una funzione perché deve essere "
        "lo stesso per chiunque legga, e perché il motivo del rifiuto è "
        "un'informazione quanto il risultato: «di questa gara posso dirti il "
        "totale, non come l'hai distribuita» è una risposta, «nessun dato» no. "
        "Misurato sulle nuotate in mare oltre i 3 km: 18 su 22 passano."),

    "race_conditions": TableDoc(
        "che acqua e che vento c'era durante una nuotata in mare",
        "activity_id",
        "modello meteo Open-Meteo, archivio storico e marino",
        "garmin_proprietary",
        "**Non sono una misura di quella gara**: sono la ricostruzione di un "
        "modello su una griglia di chilometri, e la corrente sotto costa non "
        "ci sta dentro. Servono a dare contesto a un tempo e a fare da "
        "riscontro alla corrente misurata dall'asimmetria per direzione della "
        "nuotata stessa. Non entrano mai in una formula che corregge un tempo: "
        "un tempo corretto da un modello non è più un tempo. Si mediano sulle "
        "ore che la nuotata ha davvero attraversato, non sulla giornata. Sui "
        "laghi acqua e onda restano vuote perché il modello marino non li "
        "copre: è un'assenza legittima, non un guasto.",
    ),

    "counted_swims": TableDoc(
        "cosa conta come nuotata nel volume, orologio o no",
        "unit_key",
        "canonical_activities più le gare in mare non già registrate",
        "calculated",
        "In mare l'orologio spesso non è ammesso: venticinque gare in acque "
        "libere fra il 2016 e il 2026 non hanno una seduta Garmin, e sono "
        "nuotate a tutti gli effetti. Una gara resta fuori solo quando **è** "
        "una nuotata già contata, e a dirlo è una persona: nessuna regola "
        "automatica regge. Dedurlo dal giorno sbagliava in due modi opposti — "
        "il 23/08/2026 la gara era a place04 la mattina e l'allenamento a place03 "
        "alle [orario], e il 19/05/2018 c'erano due gare con una sola nuotata "
        "registrata, perché l'orologio era ammesso in una sola. I verdetti "
        "stanno in `race_quality`, e il criterio C19 pretende che nessuna gara "
        "che condivide il giorno con una nuotata ne resti priva. "
        "`origin` distingue le due metà e non è decorativo — una riga `race` "
        "porta metri e minuti **dichiarati dall'evento**, non misurati, e non "
        "ha SWOLF, bracciate, battiti né un dispositivo da nominare in un "
        "confronto pluriennale. La vista esiste perché `daily_status` e "
        "`analysis/volume.py` rispondano alla stessa domanda con la stessa "
        "regola (Regola Aurea n.8).",
    ),

    "canonical_races": TableDoc(
        "le gare con le decisioni dell'atleta già applicate",
        "race_id",
        "races più race_quality",
        "calculated",
        "Quello che `canonical_activities` è per le attività: la vista che ogni "
        "analisi interroga al posto della tabella grezza. Applica la distanza "
        "corretta, unifica in una sola colonna i due modi di collegare una gara "
        "a una nuotata — `races.activity_id` dalle gare dichiarate, "
        "`race_quality.activity_id` dalle correzioni — e toglie le gare escluse, "
        "perché una decisione dimenticata in un angolo non è una decisione. "
        "La correzione resta visibile in `declared_distance_m`, "
        "`distance_corrected` e `athlete_verdict`: senza, fra un anno qualcuno "
        "scambia il numero giusto per un difetto e lo «ripara». Esiste perché "
        "la migrazione 0017 applicava la distanza corretta al solo volume, e la "
        "pagina Gare avrebbe continuato a mostrare place04 a 2.500 m con il passo "
        "che l'atleta aveva appena dichiarato impossibile (Regola Aurea n.8).",
    ),

    "race_quality": TableDoc(
        "cosa ha deciso l'atleta su una gara che l'archivio dichiara",
        "race_id",
        "coach/correzioni-gare.md, scritto dall'atleta",
        "calculated",
        "Il gemello di `activity_quality`, per le gare invece che per le "
        "attività. Tre verdetti: `linked` — la gara è quella nuotata "
        "dell'orologio, i metri sono già contati una volta; `separate` — una "
        "nuotata a sé, anche se quel giorno l'orologio ha registrato altro; "
        "`exclude` — fuori dal volume, perché è successo qualcosa che la rende "
        "non confrontabile. Porta anche la distanza vera quando quella del "
        "nome dell'evento è sbagliata: `distance_source = 'event_field'` non è "
        "una misura del percorso, e tre gare dichiaravano un passo che nessun "
        "essere umano nuota. `distance_is_unknown` copre il caso che un numero "
        "non sa dire — «so che è sbagliata e non so quale sia» — perché "
        "l'alternativa sarebbe inventarla (R5). Sta in una tabella e non in "
        "colonne di `races` perché `races` si rifà dalla sorgente a ogni "
        "import.",
    ),

    "daily_health": TableDoc(
        "i valori di salute di un giorno di calendario",
        "health_date",
        "file UDS dell'export",
        "measured + garmin_proprietary",
        "Body Battery e stress sono algoritmi Garmin."),

    "sleep": TableDoc(
        "il sonno attribuito a una data",
        "sleep_date",
        "file sleepData dell'export",
        "measured + garmin_proprietary"),

    "health_status": TableDoc(
        "lo stato HRV di una notte",
        "status_date",
        "file healthStatusData dell'export",
        "garmin_proprietary",
        "Disponibile solo dal 19 settembre 2025: copre il 9% della storia."),

    "garmin_training_load": TableDoc(
        "carico acuto e cronico calcolati da Garmin per un giorno",
        "load_date",
        "MetricsAcuteTrainingLoad dell'export",
        "garmin_proprietary",
        "L'ACWR di Garmin non è un indicatore di rischio infortunio."),

    "garmin_training_status": TableDoc(
        "lo stato di allenamento dichiarato da Garmin per un giorno",
        "status_date", "TrainingHistory dell'export", "garmin_proprietary"),

    "garmin_readiness": TableDoc(
        "il punteggio Training Readiness di Garmin",
        "readiness_date", "TrainingReadinessDTO dell'export", "garmin_proprietary"),

    "body_metrics": TableDoc(
        "una pesata o misura corporea",
        "measured_at", "file di peso dell'export", "measured"),

    "hr_zones": TableDoc(
        "la configurazione delle zone di frequenza cardiaca",
        "sport", "impostazioni dell'export", "measured"),

    "daily_status": TableDoc(
        "lo stato dell'atleta in un giorno, con baseline e finestre mobili",
        "status_date",
        "ricalcolata da activities, daily_health, sleep, health_status",
        "calculated",
        "Interamente derivata: si può cancellare e ricostruire. Non è mai "
        "sorgente di niente. Le formule stanno in metrics/catalog.py. "
        "Non compare nelle migrazioni perché la sua forma è decisa dalla query "
        "che la genera.",
        derived=True),

    "source_objects": TableDoc(
        "un file o una risposta da cui sono state ricavate delle righe",
        "source_object_id",
        "l'export locale e le catture del sync",
        "measured",
        "Il ponte fra una riga del database e la cosa da cui viene. "
        "sha256 contiene un vero SHA-256, mai un URI."),

    "ingest_runs": TableDoc(
        "un'esecuzione di import, con il suo esito",
        "run_id", "il programma stesso", "measured",
        "Serve a dire quando una riga è entrata e con quale versione del "
        "parser, senza sporcare ogni tabella con quei campi."),

    "activity_source_matches": TableDoc(
        "il verdetto sull'associazione fra un'attività e un file sorgente",
        "activity_id + source_object_id",
        "confronto fra activities e gli header FIT",
        "inferred",
        "Conserva anche i candidati scartati e il motivo: un aggancio "
        "plausibile non deve diventare un fatto in silenzio."),

    "schema_migrations": TableDoc(
        "una migrazione dello schema effettivamente applicata a questo file",
        "migration_id", "i file di migrations/", "measured",
        "Dimostra quale schema è davvero applicato, invece di dedurlo dal codice."),

    "import_log": TableDoc(
        "un file dell'export importato in una tabella",
        "source_object_id + target_table", "l'import stesso", "measured",
        "Precede source_objects e sarà assorbito da quello."),

    "activity_quality": TableDoc(
        "una decisione dell'atleta su un'attività che i dati da soli "
        "descrivono male",
        "activity_id", "coach/correzioni-dati.md", "declared",
        "Un'attività può essere formalmente perfetta — riepilogo e FIT in "
        "accordo esatto — e non descrivere un allenamento. La decisione vive "
        "nel markdown perché è un'intenzione umana e il database si "
        "ricostruisce; qui ci arriva a ogni import."),

    "races": TableDoc(
        "un risultato ufficiale, in vasca o in acque libere",
        "race_id (giorno + evento + specialità)",
        "coach/aquatime/ per la vasca, coach/icron/ per il mare, "
        "coach/gare-dichiarate.md per quelle che nessuno dei due contiene",
        "measured",
        "Le misure di questo archivio che non vengono da un orologio al polso "
        "di chi nuota. In vasca le produce una piastra e la distanza è "
        "certificata; in mare il tempo è cronometrato e la distanza è "
        "**dichiarata dall'organizzazione**, e `distance_source` dice sempre "
        "quale dei due casi si sta guardando. Le staffette restano qui con "
        "`is_relay`, e le squalifiche senza tempo. Le gare dichiarate "
        "dall'atleta portano `distance_source = 'athlete_declared'`: sono "
        "fatti veri — c'era un cronometro e un'organizzazione — che nessuna "
        "piattaforma leggibile ha registrato."),

    "race_splits": TableDoc(
        "un passaggio cronometrato dentro una gara",
        "race_id + split_m", "la stessa sorgente delle gare", "measured",
        "`split_s` si conserva quando la federazione lo espone e resta NULL "
        "quando manca: ricostruirlo dai cumulativi sarebbe un valore derivato "
        "che assomiglia a una misura."),

    "personal_races": TableDoc(
        "una gara che descrive la prestazione di questa persona",
        "race_id", "races", "derived",
        "Toglie staffette e squalifiche. È ciò che ogni lettura di record e di "
        "passo deve interrogare al posto di `races`, per lo stesso motivo per "
        "cui le analisi interrogano `canonical_activities`: escludere a mano, "
        "ogni volta, prima o poi si dimentica.", derived=True),

    "pool_races": TableDoc(
        "una gara confrontabile senza precauzioni: vasca, distanza certificata, "
        "stile noto",
        "race_id", "personal_races", "derived",
        "È la vista che record, progressioni e velocità critica devono "
        "interrogare. Il mare non ci entra: confrontare 3.000 m dichiarati con "
        "3.000 m dichiarati altrove è confrontare due numeri che nessuno ha "
        "misurato.", derived=True),

    "open_water_races": TableDoc(
        "una gara in acque libere di questa persona",
        "race_id", "personal_races", "derived",
        "Il tempo è misurato, la distanza no. Il passo che se ne ricava porta "
        "sempre con sé da dove viene la distanza, e quando il conto darebbe un "
        "passo più veloce del miglior 100 in vasca dell'atleta il passo non "
        "viene calcolato: non è la nuotata a essere impossibile, è la distanza "
        "dichiarata a non reggere.", derived=True),

    "canonical_activities": TableDoc(
        "un'attività al netto delle correzioni confermate dall'atleta",
        "activity_id", "activities + activity_quality", "derived",
        "È ciò che ogni analisi interroga al posto di `activities`. Non è una "
        "comodità: è il punto in cui la decisione dell'atleta diventa "
        "inevitabile.", derived=True),
}


def missing_documentation(connection: duckdb.DuckDBPyConnection) -> tuple[set, set]:
    """Le tabelle non descritte e le descrizioni senza tabella."""
    real = {row[0] for row in connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'").fetchall()}
    # Le derivate possono mancare — su un database appena migrato il calcolo
    # non è ancora stato eseguito. Non possono invece essere di troppo.
    declared = {name for name, doc in TABLES.items() if not doc.derived}
    return real - set(TABLES), declared - real


def render(connection: duckdb.DuckDBPyConnection) -> str:
    """Il dizionario in markdown, dallo schema reale."""
    from datetime import date

    lines = [
        "# Dizionario dei dati",
        "",
        "> **Generato**, non scritto a mano: `garmin_coach dictionary` lo rifà",
        "> dallo schema reale. Se qui c'è scritta una colonna, quella colonna",
        "> esiste nel database. Un test lo verifica a ogni esecuzione.",
        "",
        f"**Rigenerato il:** {date.today().isoformat()}",
        "",
        "## Come si legge",
        "",
        "Ogni tabella dichiara **che cosa rappresenta una sua riga**. È la domanda",
        "che si sbaglia più spesso: `activity_laps` e `pool_lengths` contengono",
        "entrambe pezzi di una nuotata, ma una riga significa cose diverse.",
        "",
        "La **classe del dato** dice quanto puoi fidarti di un numero e di chi è:",
        "",
        "| Classe | Significa |",
        "|---|---|",
        "| `measured` | misurato da un sensore, conservato com'era |",
        "| `garmin_proprietary` | calcolato da Garmin con formula ignota: esposto col suo nome, mai rivendicato |",
        "| `calculated` | calcolato qui da una funzione deterministica e testata |",
        "| `inferred` | dedotto con un metodo che può sbagliare, e che sa dire «non riconosciuto» |",
        "",
        "Le unità sono nel nome della colonna: `_m` metri, `_s` secondi,",
        "`_ms` millisecondi, `_bpm` battiti al minuto, `_spm` bracciate al minuto,",
        "`_kcal` chilocalorie, `_c` gradi. Nessuna colonna senza suffisso porta",
        "un'unità implicita.",
        "",
        "---",
        "",
    ]

    for name, doc in TABLES.items():
        rows = connection.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position", [name]).fetchall()
        if not rows:
            if not doc.derived:
                continue
            # Una derivata non ancora calcolata va comunque descritta: chi legge
            # il dizionario deve sapere che esiste e come ottenerla.
            lines += [
                f"## `{name}`", "",
                f"**Una riga è:** {doc.row_means}", "",
                "> Non presente in questo database: è derivata e va calcolata "
                "con `garmin_coach metrics`.", "",
                f"> {doc.note}" if doc.note else "", "", "---", "",
            ]
            continue
        count = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]

        lines += [
            f"## `{name}`",
            "",
            f"**Una riga è:** {doc.row_means}",
            "",
            f"| | |",
            f"|---|---|",
            f"| Chiave | {doc.key} |",
            f"| Sorgente | {doc.source} |",
            f"| Classe | `{doc.data_class}` |",
            f"| Righe adesso | {count:,} |",
            "",
        ]
        if doc.note:
            lines += [f"> {doc.note}", ""]
        lines += ["| Colonna | Tipo | Può mancare |", "|---|---|---|"]
        for column, kind, nullable in rows:
            lines.append(f"| `{column}` | {kind} | {'sì' if nullable == 'YES' else 'no'} |")
        lines += ["", "---", ""]

    lines += [
        "## Stati del dato mancante",
        "",
        "Nel database un dato mancante è `NULL`, sempre. **Mai zero.** Negli",
        "output degli strumenti il vuoto porta con sé la sua causa, perché",
        "«non ce l'ho» e «non esiste» non sono la stessa risposta:",
        "",
        "| Stato | Significa |",
        "|---|---|",
        "| `missing` | la sorgente poteva contenerlo e non lo contiene |",
        "| `not_applicable` | il concetto non vale qui — le vasche in mare |",
        "| `insufficient_data` | i dati ci sono ma non bastano per il calcolo |",
        "| `invalid` | il valore non ha superato i controlli di plausibilità |",
        "| `stale` | esiste ma è troppo vecchio per la domanda di adesso |",
        "",
    ]
    return "\n".join(lines)
