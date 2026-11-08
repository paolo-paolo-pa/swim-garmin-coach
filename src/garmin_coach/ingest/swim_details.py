"""I lap e le vasche di una seduta, dai file FIT (D4 e D5).

## La domanda dell'atleta

*"Cosa ho fatto davvero, dentro quella seduta?"*

I riepiloghi dicono 3.700 metri in 68 minuti. Non dicono se erano 2.000 continui
o 12×250 a ritmo gara, e non dicono se il passo è calato dalla quarta ripetuta
in poi — che è l'unica cosa che distingue una serie retta da una subìta.

## Cosa NON è questa tabella

``activity_laps`` contiene **lap**, non serie. Un lap è quello che l'orologio ha
segnato; «8×100» è un'interpretazione che richiede un metodo e può sbagliare.
La tabella si chiamava ``swim_sets`` e prometteva la seconda cosa contenendo la
prima: sopra un nome così si costruiscono analisi sbagliate senza accorgersene.

## Come si trova il file giusto

Il numero nel nome del file FIT è quello del **caricamento**, non dell'attività.
L'aggancio si fa sul tempo: ``file_id.time_created`` coincide con l'inizio della
sessione a meno di pochi secondi.

Due passate:

1. si legge **solo** l'header di tutti i FIT (0,3 ms l'uno) tenendo i soli
   ``file_id.type == 'activity'``;
2. si aprono per intero soltanto quelli agganciati a una seduta.

**Il filtro sul tipo non è un dettaglio.** Misurato sull'archivio reale: dei
39.472 file appena 1.471 sono attività — lo stesso numero delle attività della
baseline, corrispondenza uno a uno. Gli altri 38.001 sono monitoraggio e formati
non documentati. Una prima versione indicizzava tutto e teneva il primo file per
istante: quando un file di monitoraggio condivideva l'istante con un'attività
vinceva il monitoraggio, e la seduta restava senza dettaglio. Costava 36 sedute.

## Piscina e acque libere

In mare le vasche non esistono. Non è un dato mancante: è un concetto che non si
applica, e segnarlo come lacuna sarebbe un errore di modello. I lap in acque
libere si importano lo stesso — sono quelli che l'atleta ha premuto a mano e
dicono comunque come è andata — ma senza inventare vasche.

## Quando non si sceglie

Se due file sono indistinguibili entro la tolleranza, nessuno dei due viene
scelto: il verdetto è ``ambiguous`` e la seduta resta senza dettaglio, con il
motivo scritto in ``activity_source_matches``. Proprio perché sono poche non
vale la pena indovinare.

## Quando invece non c'è niente da scegliere

L'orario è un indizio; il nome di un file scaricato è un'identità. Un FIT
chiesto a Garmin per un'attività precisa arriva in ``data/raw/activity-files``
con quel numero addosso, e agganciarlo per orario significherebbe buttare una
certezza per rimpiazzarla con una coincidenza. Questi file vengono agganciati
per nome, escono dal mucchio dei candidati per orario, e il loro verdetto porta
``method = 'activity_id'`` invece di ``'timestamp'``.

Misurato sull'archivio vero: le sedute ``ambiguous`` erano 4 — tre del 2018 e
una del 2023 — e lo scaricamento non le aveva salvate, anzi le peggiorava,
perché aggiungeva alla finestra un terzo file identico a uno dei due già
presenti. Lette per nome scendono a 0, e con loro le nuotate senza un lap.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .. import paths
from . import source_catalog

# Scarto massimo fra il ``time_created`` del FIT e l'inizio dell'attività.
# Misurato: la differenza tipica è di 1-2 secondi, ma l'orologio scrive il file
# alla chiusura e su alcune sedute anticipa.
MATCH_TOLERANCE = timedelta(seconds=60)

# Oltre questi scarti il riepilogo e il file non dicono la stessa cosa.
#
# La soglia sulla distanza era 0,25, e non era calibrata su niente. Misurato sui
# 1.302 agganci riusciti dell'archivio: **1.294 concordano esattamente**,
# mediana dello scarto 0,0 m. Gli unici due scarti non nulli sono place03
# 26/08/2023 — 6.000 m dichiarati contro 7.446 nel file, il 24,1% — e uno al
# −7,7%. Una tolleranza del 25% su una popolazione che concorda al metro non
# tollera il rumore: accetta l'unico caso che avrebbe dovuto far alzare la mano.
MAX_DISTANCE_MISMATCH = 0.10     # 10% della distanza dichiarata
MAX_DURATION_MISMATCH = 0.15     # 15% della durata dichiarata

# I verdetti dell'aggancio, e quali di questi portano dentro il dettaglio.
#
# ``discordant`` è nuovo e serve a una situazione che gli altri non descrivono:
# il file è **proprio questa** nuotata — il timestamp coincide al secondo — e
# sono le due distanze a non coincidere. ``incompatible`` significa un'altra
# cosa, cioè «il file descrive un'altra seduta», e usarlo qui butterebbe lap
# veri: sono l'unica cosa che permette di capire il disaccordo.
VERDICTS = ("matched", "discordant", "incompatible", "ambiguous", "unmatched")

_WITH_DETAIL = {"matched", "discordant"}


def keeps_detail(verdict: str) -> bool:
    """Se questo verdetto porta dentro lap e vasche."""
    return verdict in _WITH_DETAIL


def agreement(distance: float | None, distance_gap: float | None,
              duration: float | None, duration_gap: float | None) -> str | None:
    """Come i due numeri non concordano, se non concordano.

    ``None`` quando concordano: è il caso di 1.294 sedute su 1.302, e non deve
    lasciare nessuna nota addosso a una seduta che sta bene.
    """
    if distance and distance_gap is not None:
        quota = abs(distance_gap) / distance
        if quota > MAX_DISTANCE_MISMATCH:
            return (f"la distanza del file differisce del {quota:.0%} "
                    f"({distance_gap:+,.0f} m su {distance:,.0f})")
    if duration and duration_gap is not None:
        quota = abs(duration_gap) / duration
        if quota > MAX_DURATION_MISMATCH:
            return (f"la durata del file differisce del {quota:.0%} "
                    f"({duration_gap:+,.0f} s su {duration:,.0f})")
    return None

FIT_ARCHIVES = ("DI-Connect-Uploaded-Files", "UploadedFiles_*.zip")

PARSER = "fitdecode"
PARSER_VERSION = "2"      # 1 = prototipo senza filtro sul tipo

LAP_COLUMNS = [
    "activity_id", "lap_index", "start_time_utc", "duration_s", "distance_m",
    "lengths_count", "active_lengths_count", "stroke", "total_strokes",
    "avg_hr_bpm", "max_hr_bpm", "avg_cadence_spm", "pace_per_100m_s", "swolf",
    "lap_trigger", "is_rest", "environment", "source_object_id", "imported_at",
]

LENGTH_COLUMNS = [
    "activity_id", "length_index", "lap_index", "start_time_utc", "duration_s",
    "stroke", "total_strokes", "avg_speed_ms", "cadence_spm", "is_active",
    "source_object_id", "imported_at",
]

MATCH_COLUMNS = [
    "activity_id", "source_object_id", "verdict", "method", "time_gap_s",
    "duration_gap_s", "distance_gap_m", "reason", "decided_at",
]

NO_CANDIDATE = "—"     # segnaposto quando non c'è nessuna sorgente da citare

# Un header agganciato per nome non usa il proprio orario per niente: questo
# valore esiste solo perché ``FitHeader`` ne pretende uno, e non deve poter
# finire per sbaglio in una finestra di tolleranza.
_FILENAME_IDENTITY = datetime.min


@dataclass(frozen=True)
class FitHeader:
    """Quel poco che serve a sapere se vale la pena aprire un file."""
    created: datetime
    archive: str
    member: str


@dataclass(frozen=True)
class DetailReport:
    """Cosa ha fatto l'import del dettaglio FIT.

    Era un dizionario, e la riga di comando ne leggeva cinque chiavi che non
    esistevano — ``fit_files_indexed``, ``sessions_matched``, ``pool_swims``,
    ``sets``, ``unmatched``. Il comando ``details`` moriva con un ``KeyError``
    **dopo** aver scritto tutto: l'import riusciva e l'atleta vedeva una traccia
    Python. Non è mai arrivato in fondo nemmeno una volta.

    Un dizionario è un contratto che nessuno firma: chi legge può inventarsi una
    chiave e scoprirlo solo quando il comando gira davvero. Qui i nomi stanno in
    un posto solo, e sbagliarne uno è un errore di attributo che si vede subito.
    """

    fit_files_scanned: int
    fit_activities: int
    census: dict
    swims: int
    verdicts: dict
    laps: int
    lengths: int
    sources_registered: int

    @property
    def matched(self) -> int:
        """Sedute che hanno il loro file FIT, agganciato e compatibile."""
        return self.verdicts.get("matched", 0)

    @property
    def without_detail(self) -> int:
        """Sedute rimaste senza dettaglio, per qualunque motivo.

        Sono i verdetti che non portano dentro lap e vasche: nessun candidato,
        più candidati indistinguibili, file agganciato ma incompatibile. Sono
        tre cose diverse e restano leggibili in ``verdicts``; questo numero
        serve solo a dire quante sedute il coach non potrà raccontare dentro.

        Era ``swims - matched``, e contava fra le mancanti anche le
        ``discordant`` — sedute che il dettaglio ce l'hanno eccome, solo con i
        due totali che non si accordano. Il comando dichiarava una seduta senza
        dettaglio mentre i suoi lap erano nel database. Chi decide se un
        verdetto porta dentro il dettaglio è ``keeps_detail``, in un posto solo.
        """
        return sum(quante for verdetto, quante in self.verdicts.items()
                   if not keeps_detail(verdetto))


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _naive_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


# Il nome che prende il posto dell'archivio per i file scaricati dal sync.
# Non è uno ZIP e non deve fingere di esserlo: chi legge un `locator` che
# comincia così sa che il file sta su disco per conto proprio.
DOWNLOADED = "data/raw/activity-files"


def _archives() -> list[Path]:
    folder, pattern = FIT_ARCHIVES
    return sorted(paths.connect_dir(folder).glob(pattern))


def _downloaded_headers() -> list[FitHeader]:
    """Gli header dei FIT scaricati dal sync, che l'export non contiene.

    L'export si ferma al 4 luglio 2026: da lì in poi questi file sono l'unica
    sorgente di dettaglio esistente. Entrano nello stesso elenco degli altri e
    passano per la stessa riconciliazione, perché sono la stessa cosa arrivata
    per un'altra strada.
    """
    import fitdecode

    cartella = source_catalog.RAW_FIT
    if not cartella.exists():
        return []

    trovati: list[FitHeader] = []
    for percorso in sorted(cartella.glob("*.fit")):
        try:
            with fitdecode.FitReader(io.BytesIO(percorso.read_bytes())) as fit:
                for frame in fit:
                    if (frame.frame_type != fitdecode.FIT_FRAME_DATA
                            or frame.name != "file_id"):
                        continue
                    created = _naive_utc(
                        frame.get_value("time_created", fallback=None))
                    if str(frame.get_value("type", fallback="")) == "activity" \
                            and created:
                        trovati.append(FitHeader(created, DOWNLOADED,
                                                 percorso.name))
                    break
        except Exception:  # noqa: BLE001
            continue
    return trovati


def _downloaded_by_activity() -> dict[int, FitHeader]:
    """I FIT scaricati dal sync, indicizzati per l'attività che dichiarano.

    Un file scaricato si chiama con il numero dell'attività per cui è stato
    chiesto: quel nome non è una coincidenza da verificare, è l'identità del
    file. Agganciarlo per orario sarebbe buttare una certezza e rimpiazzarla
    con un indizio.

    Misurato: quattro nuotate del 2018 e del 2023 restavano senza dettaglio
    perché nell'export esistono due file plausibili entro la tolleranza e
    nessuno dei due viene scelto. Lo scaricamento non le aveva salvate — anzi,
    aggiungeva un terzo candidato identico a uno dei due e rendeva l'ambiguità
    peggiore. Letto per nome, invece, lo stesso file la scioglie.

    Se per una stessa attività esistono più file — succede quando il contenuto
    cambia e il nome prende in coda l'impronta — l'identità non basta più a
    scegliere e la decisione torna alla riconciliazione per orario.
    """
    cartella = source_catalog.RAW_FIT
    if not cartella.exists():
        return {}

    per_attivita: dict[int, list[Path]] = defaultdict(list)
    for percorso in sorted(cartella.glob("*.fit")):
        numero = percorso.stem.split("-")[0]
        if numero.isdigit():
            per_attivita[int(numero)].append(percorso)

    return {activity_id: FitHeader(_FILENAME_IDENTITY, DOWNLOADED,
                                   percorsi[0].name)
            for activity_id, percorsi in per_attivita.items()
            if len(percorsi) == 1}


def read_member(header: FitHeader, handles: dict) -> bytes:
    """Il contenuto di un FIT, da uno ZIP o dal disco.

    Un solo punto in cui si decide da dove arriva il file: senza, ogni chiamante
    dovrebbe ricordarsi del caso «scaricato», e prima o poi uno se ne dimentica.
    """
    if header.archive == DOWNLOADED:
        return (source_catalog.RAW_FIT / header.member).read_bytes()
    return handles[header.archive].read(header.member)


def scan_headers() -> tuple[list[FitHeader], Counter]:
    """Gli header di tutti i FIT: le sole attività, più il censimento dei tipi.

    Il censimento non serve al programma. Serve a poter dimostrare che la
    scansione è esaustiva e che nessun file di attività è stato saltato.
    """
    import fitdecode

    activities: list[FitHeader] = []
    census: Counter = Counter()

    for archive in _archives():
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.lower().endswith(".fit"):
                    census["non-fit"] += 1
                    continue
                try:
                    with fitdecode.FitReader(io.BytesIO(bundle.read(name))) as fit:
                        for frame in fit:
                            if (frame.frame_type != fitdecode.FIT_FRAME_DATA
                                    or frame.name != "file_id"):
                                continue
                            kind = str(frame.get_value("type", fallback="sconosciuto"))
                            census[kind] += 1
                            created = _naive_utc(
                                frame.get_value("time_created", fallback=None))
                            if kind == "activity" and created:
                                activities.append(FitHeader(created, archive.name, name))
                            break
                        else:
                            census["senza file_id"] += 1
                except Exception:  # noqa: BLE001
                    # Un FIT illeggibile è un file in meno, non un import fallito.
                    census["illeggibile"] += 1

    scaricati = _downloaded_headers()
    census["scaricati dal sync"] = len(scaricati)
    activities.extend(scaricati)
    return activities, census


def candidates_for(start: datetime, headers: list[FitHeader],
                   times: list[datetime]) -> list[FitHeader]:
    """Tutti i file plausibili per una seduta, non solo il migliore.

    Restituirne uno solo nasconderebbe l'unica informazione che conta quando la
    scelta non è ovvia: che c'era una scelta.
    """
    import bisect

    position = bisect.bisect_left(times, start)
    window = range(max(0, position - 4), min(len(headers), position + 4))
    return [headers[i] for i in window if abs(times[i] - start) <= MATCH_TOLERANCE]


def _parse(data: bytes, activity_id: int, environment: str | None,
           source_object_id: str, imported_at: datetime) -> tuple[list, list, dict]:
    """Un FIT in righe di ``activity_laps`` e ``pool_lengths``, più la sessione.

    Le vasche si leggono soltanto in piscina: in mare i messaggi ``length`` non
    esistono e cercarli sarebbe cercare un'assenza.
    """
    import fitdecode

    laps: list[dict] = []
    lengths: list[dict] = []
    session: dict = {}
    with fitdecode.FitReader(io.BytesIO(data)) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if frame.name == "lap":
                laps.append({f.name: f.value for f in frame.fields})
            elif frame.name == "length":
                lengths.append({f.name: f.value for f in frame.fields})
            elif frame.name == "session" and not session:
                session = {f.name: f.value for f in frame.fields}

    is_pool = environment == "pool"
    if not is_pool:
        lengths = []

    # Ogni vasca appartiene al lap che la contiene: il lap dichiara da quale
    # indice parte e quante ne comprende.
    owner: dict[int, int] = {}
    for lap in laps:
        first = lap.get("first_length_index")
        count = lap.get("num_lengths")
        lap_index = lap.get("message_index")
        if first is None or count is None or lap_index is None:
            continue
        for offset in range(int(count)):
            owner[int(first) + offset] = int(lap_index)

    # Lo SWOLF appartiene alla vasca. Si aggrega per lap solo come media delle
    # sue vasche attive, mai come somma diviso il numero di vasche.
    swolf_by_lap: dict[int, list[float]] = defaultdict(list)
    length_rows: list[tuple] = []
    for length in lengths:
        index = length.get("message_index")
        if index is None:
            continue
        index = int(index)
        lap_index = owner.get(index)
        active = length.get("length_type") == "active"
        seconds = _number(length.get("total_timer_time"))
        strokes = _number(length.get("total_strokes"))
        if active and lap_index is not None and seconds and strokes:
            swolf_by_lap[lap_index].append(seconds + strokes)

        length_rows.append((
            activity_id, index, lap_index,
            _naive_utc(length.get("start_time")), seconds,
            length.get("swim_stroke") if active else None,
            strokes,
            _number(length.get("avg_speed")),
            _number(length.get("avg_swimming_cadence")),
            active, source_object_id, imported_at,
        ))

    lap_rows: list[tuple] = []
    for lap in laps:
        lap_index = lap.get("message_index")
        if lap_index is None:
            continue
        lap_index = int(lap_index)
        distance = _number(lap.get("total_distance"))
        seconds = _number(lap.get("total_timer_time"))
        active_lengths = lap.get("num_active_lengths")
        # In mare non ci sono vasche: un lap è di riposo solo se non ha percorso
        # distanza, non perché gli mancano le vasche.
        is_rest = (not distance) if not is_pool else (not active_lengths or not distance)
        swolf = swolf_by_lap.get(lap_index)

        lap_rows.append((
            activity_id, lap_index,
            _naive_utc(lap.get("start_time")), seconds, distance,
            int(lap["num_lengths"]) if lap.get("num_lengths") is not None else None,
            int(active_lengths) if active_lengths is not None else None,
            lap.get("swim_stroke") if not is_rest else None,
            _number(lap.get("total_strokes")),
            _number(lap.get("avg_heart_rate")),
            _number(lap.get("max_heart_rate")),
            _number(lap.get("avg_cadence")),
            (seconds / distance * 100) if (seconds and distance) else None,
            (sum(swolf) / len(swolf)) if swolf else None,
            lap.get("lap_trigger"), is_rest, environment,
            source_object_id, imported_at,
        ))

    return lap_rows, length_rows, session


def _types(connection: duckdb.DuckDBPyConnection, table: str) -> str:
    """I tipi della tabella, per non lasciarli indovinare al lettore CSV.

    Senza, una colonna tutta vuota diventerebbe testo: il tipo lo decide lo
    schema, non il contenuto del file.
    """
    rows = connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ?", [table]).fetchall()
    return "{" + ", ".join(f"'{n}': '{k}'" for n, k in rows) + "}"


def _bulk_insert(connection: duckdb.DuckDBPyConnection, table: str,
                 columns: list[str], rows: list[tuple]) -> None:
    """Scrive molte righe in una volta, passando da un CSV di appoggio.

    Non è un vezzo. Misurato su questo database: inserire riga per riga costa
    più di due minuti ogni 50.000 righe, e una seduta ne produce un centinaio —
    l'import non finiva. Lo stesso contenuto letto da CSV entra in meno di un
    secondo, perché DuckDB carica per colonne invece che per righe.
    """
    if not rows:
        return

    paths.ensure_data_dirs()
    staging = paths.STAGING / f"{table}.csv"
    try:
        with staging.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)
        connection.execute(f"""
            INSERT INTO {table} ({', '.join(columns)})
            SELECT {', '.join(columns)}
            FROM read_csv(?, header = true, nullstr = '',
                          types = {_types(connection, table)})
        """, [str(staging)])
    finally:
        staging.unlink(missing_ok=True)


def load_downloaded(connection: duckdb.DuckDBPyConnection) -> dict:
    """Elabora solo i FIT acquisiti senza lap: nessuna scansione dell'export.

    Domanda: «Posso aprire subito le vasche delle ultime sedute?»
    Riusa lo stesso parser e contratto di riconciliazione dello storico.
    """
    swims = connection.execute("""
        SELECT a.activity_id, a.environment, a.distance_m, a.duration_s
        FROM activities a WHERE a.is_swim AND NOT EXISTS
        (SELECT 1 FROM activity_laps l WHERE l.activity_id=a.activity_id)
        ORDER BY a.activity_date DESC
    """).fetchall()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    written = 0
    errors = []
    for identifier, environment, distance, duration in swims:
        file = source_catalog.RAW_FIT / f"{identifier}.fit"
        if not file.exists():
            continue
        try:
            content = file.read_bytes()
            source = source_catalog.describe(content, "fit", f"{DOWNLOADED}/{file.name}", PARSER, PARSER_VERSION)
            laps, lengths, session = _parse(content, identifier, environment, source.source_object_id, now)
            if not laps:
                continue
            fit_distance = _number(session.get("total_distance"))
            fit_duration = _number(session.get("total_timer_time"))
            distance_gap = fit_distance - distance if fit_distance is not None and distance is not None else None
            duration_gap = fit_duration - duration if fit_duration is not None and duration is not None else None
            mismatch = agreement(distance, distance_gap, duration, duration_gap)
            verdict = "discordant" if mismatch else "matched"
            connection.execute("BEGIN TRANSACTION")
            try:
                _bulk_insert(connection, "activity_laps", LAP_COLUMNS, laps)
                _bulk_insert(connection, "pool_lengths", LENGTH_COLUMNS, lengths)
                connection.execute("DELETE FROM activity_source_matches WHERE activity_id=?", [identifier])
                _bulk_insert(connection, "activity_source_matches", MATCH_COLUMNS,
                    [(identifier, source.source_object_id, verdict, "activity_id", None,
                      duration_gap, distance_gap, mismatch, now)])
                source_catalog.register(connection, [source])
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            written += 1
        except Exception as error:
            errors.append({"activity_id": identifier, "error": type(error).__name__})
    return {"activities_parsed": written, "errors": errors}


def load(connection: duckdb.DuckDBPyConnection,
         limit: int | None = None) -> DetailReport:
    """Popola lap, vasche e verdetti di riconciliazione per tutte le nuotate.

    Ricostruisce da zero: sono poche centinaia di migliaia di righe e la
    semplicità di una riscrittura completa vale più di un import incrementale
    da mantenere.
    """
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run_id = source_catalog.start_run(connection, "details")

    swims = connection.execute("""
        SELECT activity_id, start_time_utc, environment, distance_m, duration_s
        FROM activities WHERE is_swim ORDER BY start_time_utc DESC
    """).fetchall()
    if limit:
        swims = swims[:limit]

    headers, census = scan_headers()

    # I file scaricati per un'attività precisa escono dal mucchio degli
    # agganci per orario: sono già assegnati, e lasciarli lì li farebbe
    # competere come candidati per la seduta del vicino. È successo davvero —
    # il file di place10 2018 rendeva ambigua place05 2018 e viceversa.
    per_nome = _downloaded_by_activity()
    assegnati = {header.member for header in per_nome.values()}
    census["agganciati per nome"] = len(per_nome)
    headers = [header for header in headers
               if not (header.archive == DOWNLOADED and header.member in assegnati)]

    headers.sort(key=lambda header: header.created)
    times = [header.created for header in headers]

    lap_rows: list[tuple] = []
    length_rows: list[tuple] = []
    match_rows: list[tuple] = []
    sources: list[source_catalog.SourceObject] = []
    verdicts: Counter = Counter()

    handles = {archive.name: zipfile.ZipFile(archive) for archive in _archives()}
    try:
        for activity_id, start, environment, distance, duration in swims:
            # Il file che porta in nome il numero di questa attività vince su
            # qualsiasi coincidenza di orario: è l'attività stessa, chiesta per
            # id e ricevuta. Lo scarto di orario resta vuoto perché nessun
            # orario è stato confrontato.
            scelto = per_nome.get(activity_id)
            metodo = "activity_id" if scelto else "timestamp"
            found = [] if scelto else candidates_for(start, headers, times)

            if not scelto and not found:
                verdicts["unmatched"] += 1
                match_rows.append((
                    activity_id, NO_CANDIDATE, "unmatched", "timestamp",
                    None, None, None,
                    "nessun FIT di attività entro "
                    f"{int(MATCH_TOLERANCE.total_seconds())} s", imported_at))
                continue

            if len(found) > 1:
                # Non si sceglie. Tutti i candidati restano registrati col
                # motivo: una seduta senza dettaglio spiegato è meglio di una
                # con il dettaglio di un'altra seduta.
                verdicts["ambiguous"] += 1
                for header in found:
                    described = source_catalog.describe(
                        read_member(header, handles), "fit",
                        f"{header.archive}/{header.member}", PARSER, PARSER_VERSION)
                    sources.append(described)
                    match_rows.append((
                        activity_id, described.source_object_id, "ambiguous",
                        "timestamp", (header.created - start).total_seconds(),
                        None, None,
                        f"{len(found)} file di attività entro la tolleranza: "
                        "nessuno viene scelto", imported_at))
                continue

            header = scelto or found[0]
            scarto_orario = (None if scelto
                             else (header.created - start).total_seconds())
            content = read_member(header, handles)
            described = source_catalog.describe(
                content, "fit", f"{header.archive}/{header.member}",
                PARSER, PARSER_VERSION)
            sources.append(described)
            laps, lengths, session = _parse(
                content, int(activity_id), environment,
                described.source_object_id, imported_at)

            fit_distance = _number(session.get("total_distance"))
            fit_duration = _number(session.get("total_timer_time"))
            distance_gap = (fit_distance - distance) if (fit_distance and distance) else None
            duration_gap = (fit_duration - duration) if (fit_duration and duration) else None
            disaccordo = agreement(distance, distance_gap,
                                   duration, duration_gap)

            if not laps:
                verdicts["unmatched"] += 1
                match_rows.append((
                    activity_id, described.source_object_id, "unmatched",
                    metodo, scarto_orario,
                    duration_gap, distance_gap,
                    "il file è agganciato ma non contiene lap", imported_at))
                continue

            # Il file è questa nuotata — il timestamp coincide — e i lap sono
            # veri. Se i due totali non concordano, il verdetto lo dice e il
            # dettaglio entra lo stesso: è l'unica cosa che permette di capire
            # da dove viene la differenza.
            verdetto = "discordant" if disaccordo else "matched"
            verdicts[verdetto] += 1
            lap_rows.extend(laps)
            length_rows.extend(lengths)
            match_rows.append((
                activity_id, described.source_object_id, verdetto, metodo,
                scarto_orario, duration_gap,
                distance_gap, disaccordo, imported_at))
    finally:
        for handle in handles.values():
            handle.close()

    # La riscrittura è una sola operazione: o ci sono le tabelle di prima, o
    # ci sono quelle nuove. Prima erano tre DELETE seguiti da tre inserimenti,
    # ognuno confermato per conto suo: un guasto in mezzo lasciava l'archivio
    # del dettaglio svuotato, e il rimedio era rieseguire il comando che si era
    # appena rotto.
    #
    # Il perimetro dipende da `limit`. Senza, si riscrive tutto. Con, si tocca
    # **solo** ciò che è stato guardato: `limit` è una modalità diagnostica, e
    # cancellare nove anni di dettaglio per guardare cinque sedute non era
    # quello che chiedeva chi lo scriveva.
    viste = [int(activity_id) for activity_id, *_ in swims]
    perimetro = ("" if limit is None else
                 " WHERE activity_id IN (" + ", ".join(str(a) for a in viste) + ")"
                 if viste else " WHERE FALSE")

    connection.execute("BEGIN TRANSACTION")
    try:
        for tabella in ("activity_laps", "pool_lengths",
                        "activity_source_matches"):
            connection.execute(f"DELETE FROM {tabella}{perimetro}")
        _bulk_insert(connection, "activity_laps", LAP_COLUMNS, lap_rows)
        _bulk_insert(connection, "pool_lengths", LENGTH_COLUMNS, length_rows)
        _bulk_insert(connection, "activity_source_matches", MATCH_COLUMNS,
                     match_rows)
        registered = source_catalog.register(connection, sources)
        source_catalog.finish_run(connection, run_id, "ok",
                                  rows=len(lap_rows) + len(length_rows),
                                  sources=registered)
    except BaseException as errore:
        connection.execute("ROLLBACK")
        # Fuori dalla transazione, altrimenti il verdetto di fallimento
        # tornerebbe indietro insieme a ciò che descrive: un'esecuzione che
        # resta `running` per sempre è una bugia sul proprio stato.
        source_catalog.finish_run(connection, run_id, "failed",
                                  note=f"{type(errore).__name__}: {errore}")
        raise
    connection.execute("COMMIT")

    return DetailReport(
        fit_files_scanned=sum(census.values()),
        fit_activities=len(headers),
        census=dict(census.most_common()),
        swims=len(swims),
        verdicts=dict(verdicts),
        laps=len(lap_rows),
        lengths=len(length_rows),
        sources_registered=registered,
    )
