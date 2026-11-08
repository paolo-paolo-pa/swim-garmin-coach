"""I punti registrati durante una nuotata in mare, e quanto reggono (5.3).

## La domanda dell'atleta

*«Questa gara come l'ho distribuita? Dove è cambiata? Quanto mi ha aiutato o
frenato l'acqua?»*

Nessuna di queste ha risposta dai lap. place21 2024, dieci chilometri, ne ha
**quattro**; place23 **uno**; ventiquattro nuotate in mare **zero**. In vasca
il problema non esiste — le vasche sono 173.864 righe — ma in mare le vasche
non esistono e i lap sono quelli che l'atleta ha premuto a mano.

## Cosa entra e cosa no

Entrano le nuotate in **acque libere** e le attività collegate a una **gara**.
Non entra il resto: importare i campioni al secondo di tutte le 1.341 sedute
moltiplicherebbe l'archivio per rispondere a domande che nessuno fa.

Si legge da `activities` e non da `canonical_activities`: la traccia è un fatto
sulla **registrazione**, e resta vera anche di una registrazione che l'atleta ha
escluso dalle proprie statistiche. A filtrare sono le analisi, come sempre.

## Nessuna coordinata, e non è una rinuncia

Di una posizione assoluta queste analisi non fanno niente. Servono due
differenze fra punti consecutivi — quanto si è percorso e in che direzione — e
da quelle si ottengono lunghezza vera del percorso, andamento a tratti e
asimmetria per direzione. Il divieto sulle coordinate diventa così una proprietà
dello schema invece di una regola da ricordare. Vedi la migrazione 0012.

## Il segmento si calcola solo fra due fix consecutivi

Quando il GPS perde il segnale e lo riprende dieci punti dopo, la retta fra i
due fix non è il tratto che è stato nuotato. Attribuirla a un punto solo
gonfierebbe quel tratto e falserebbe l'andamento.

Perciò il segmento esiste **solo** se anche il punto precedente aveva un fix.
La conseguenza è voluta: dove il GPS manca, la somma dei segmenti resta più
corta della distanza dell'orologio, e quel divario è esattamente ciò che fa
scattare il cancello. Su lake01 2026 vale il −25%, con copertura al 65%.

## Il cancello, e da dove vengono le sue due soglie

Misurato sulle 22 nuotate in mare oltre i 3 km con un file agganciato:
**18 passano**. Le quattro che non passano hanno copertura fra 12% e 65% e
scarto di distanza fra −13% e −67%; le diciotto che passano stanno fra −0,8% e
−3,3% con copertura sopra il 93%. Fra i due gruppi c'è un vuoto largo, e le
soglie ci stanno dentro senza doverle limare.
"""

from __future__ import annotations

import io
import math
import statistics
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .. import paths
from . import source_catalog, swim_details

PARSER = "fit-track"
PARSER_VERSION = "1"

# Quota minima di punti con un fix GPS perché i tratti si possano leggere.
MIN_GPS_COVERAGE = 0.90

# Quanto può discostarsi la distanza ricalcolata dal GPS da quella
# dell'orologio. Sopra questo, uno dei due sta descrivendo un'altra nuotata.
MAX_DISTANCE_GAP = 0.05

# I gradi di un semicerchio FIT. Garmin memorizza le coordinate come interi a
# 32 bit su mezzo giro: qui servono solo a calcolare differenze, e nessuna
# posizione assoluta sopravvive a questa funzione.
SEMICIRCLE = 180 / 2 ** 31

# Metri per grado. La Terra non è una sfera perfetta e su segmenti di decine di
# metri la differenza è sotto il centimetro: una formula sferica completa qui
# darebbe la stessa risposta con più codice da leggere.
M_PER_DEG_LAT = 110540
M_PER_DEG_LON = 111320

TRACK_COLUMNS = [
    "activity_id", "point_index", "timestamp_utc", "elapsed_s", "distance_m",
    "segment_m", "heading_deg", "speed_ms", "heart_rate_bpm", "cadence_spm",
    "temperature_c", "source_object_id", "imported_at",
]

QUALITY_COLUMNS = [
    "activity_id", "points", "gps_points", "gps_coverage", "gps_distance_m",
    "device_distance_m", "distance_gap", "median_interval_s", "has_heart_rate",
    "segments_ok", "gate_reason", "source_object_id", "imported_at",
    "start_lat_rounded", "start_lon_rounded",
]

# A quanti decimali di grado si conserva la posizione di partenza. Un decimo di
# grado è circa **undici chilometri**: dice in quale tratto di costa si nuotava,
# non da quale spiaggia si è partiti.
#
# Non è una precauzione simbolica: è la risoluzione a cui i modelli meteo
# lavorano comunque, quindi un valore più preciso non darebbe una risposta
# migliore. Serve solo a sapere dove chiedere che tempo faceva.
POSITION_DECIMALS = 1


@dataclass(frozen=True)
class TrackReport:
    eligible: int
    imported: int
    without_source: int
    without_points: int
    points: int
    passing_gate: int

    @property
    def failing_gate(self) -> int:
        return self.imported - self.passing_gate


def _bearing_and_distance(prima: tuple[float, float],
                          dopo: tuple[float, float]) -> tuple[float, float]:
    """Quanti metri e in che direzione, fra due fix consecutivi.

    La direzione è in gradi da nord, in senso orario, come una bussola: è la
    forma in cui «andata» e «ritorno» differiscono di 180 e il confronto per
    direzione diventa leggibile.
    """
    lat1, lon1 = prima
    lat2, lon2 = dopo
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    dx = (lon2 - lon1) * M_PER_DEG_LON * math.cos(math.radians(lat1))
    return math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360


def _eligible(connection: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Le attività che meritano il dettaglio al secondo, senza duplicati."""
    return connection.execute("""
        SELECT a.activity_id, a.distance_m
        FROM activities a
        WHERE a.is_swim AND a.pool_length_m IS NULL
           OR a.activity_id IN (SELECT activity_id FROM races
                                WHERE activity_id IS NOT NULL)
        ORDER BY a.activity_id
    """).fetchall()


def _sources(connection: duckdb.DuckDBPyConnection) -> dict[int, str]:
    """Il file FIT già agganciato a ciascuna attività, dai verdetti esistenti.

    Non si riscansionano gli archivi: `details` ha già deciso quale file è di
    quale seduta, e rifare quel lavoro qui vorrebbe dire poterlo fare in modo
    diverso — cioè avere due verità sullo stesso aggancio.
    """
    righe = connection.execute("""
        SELECT m.activity_id, s.locator
        FROM activity_source_matches m
        JOIN source_objects s ON s.source_object_id = m.source_object_id
        WHERE m.verdict IN ('matched', 'discordant')
    """).fetchall()
    return {int(activity_id): locator for activity_id, locator in righe}


def _archives() -> dict[str, zipfile.ZipFile]:
    cartella, motivo = swim_details.FIT_ARCHIVES
    percorsi: list[Path] = sorted(paths.connect_dir(cartella).glob(motivo))
    return {percorso.name: zipfile.ZipFile(percorso) for percorso in percorsi}


def _content(locator: str, archivi: dict) -> bytes | None:
    """Il file di un'attività, da uno ZIP dell'export o dai file scaricati.

    Due strade e un solo punto in cui si sceglie. L'export si ferma al 4 luglio
    2026: da lì in poi i FIT esistono soltanto in `data/raw/activity-files/`, e
    dimenticarsene qui vorrebbe dire che la traccia funziona su nove anni di
    storia e non sulla settimana scorsa.
    """
    percorso = paths.ROOT / locator
    if locator.startswith("data/raw/") and percorso.exists():
        return percorso.read_bytes()

    nome_zip, _, interno = locator.partition("/")
    if nome_zip not in archivi:
        return None
    try:
        return archivi[nome_zip].read(interno)
    except KeyError:
        return None


def _points(data: bytes) -> list[dict]:
    """I messaggi `record` di un FIT, nell'ordine in cui sono stati scritti."""
    import fitdecode

    trovati: list[dict] = []
    with fitdecode.FitReader(io.BytesIO(data)) as fit:
        for frame in fit:
            if (frame.frame_type == fitdecode.FIT_FRAME_DATA
                    and frame.name == "record"):
                trovati.append({f.name: f.value for f in frame.fields})
    return trovati


def _rows(activity_id: int, punti: list[dict], source_object_id: str,
          imported_at: datetime) -> tuple[list[tuple], dict]:
    """I punti in righe, più quello che serve a giudicarli."""
    inizio = None
    precedente: tuple[float, float] | None = None
    # Il primo fix della nuotata, e l'unico che sopravvive a questa funzione —
    # arrotondato, e solo per sapere dove chiedere che tempo faceva.
    prima_posizione: tuple[float, float] | None = None
    righe: list[tuple] = []
    con_fix = 0
    con_battito = 0
    somma_segmenti = 0.0
    istanti: list[datetime] = []

    for indice, punto in enumerate(punti):
        istante = swim_details._naive_utc(punto.get("timestamp"))
        if istante is not None:
            istanti.append(istante)
            inizio = inizio if inizio is not None else istante

        grezza_lat = punto.get("position_lat")
        grezza_lon = punto.get("position_long")
        posizione = None
        if grezza_lat is not None and grezza_lon is not None:
            posizione = (grezza_lat * SEMICIRCLE, grezza_lon * SEMICIRCLE)
            con_fix += 1
            if prima_posizione is None:
                prima_posizione = posizione

        segmento = direzione = None
        if posizione is not None and precedente is not None:
            segmento, direzione = _bearing_and_distance(precedente, posizione)
            somma_segmenti += segmento

        battito = swim_details._number(punto.get("heart_rate"))
        if battito:
            con_battito += 1

        righe.append((
            activity_id, indice, istante,
            (istante - inizio).total_seconds()
            if (istante is not None and inizio is not None) else None,
            swim_details._number(punto.get("distance")),
            segmento, direzione,
            swim_details._number(punto.get("enhanced_speed"))
            or swim_details._number(punto.get("speed")),
            battito,
            swim_details._number(punto.get("cadence")),
            swim_details._number(punto.get("temperature")),
            source_object_id, imported_at,
        ))
        # Il precedente è sempre l'ultimo punto guardato, con o senza fix: così
        # dopo un buco il segmento resta assente invece di diventare una retta
        # lunga quanto il buco.
        precedente = posizione

    intervalli = [(b - a).total_seconds()
                  for a, b in zip(istanti, istanti[1:]) if b > a]
    return righe, {
        "points": len(righe),
        "gps_points": con_fix,
        "gps_distance_m": somma_segmenti,
        "has_heart_rate": con_battito > 0,
        "median_interval_s": statistics.median(intervalli) if intervalli else None,
        "start_lat_rounded": (round(prima_posizione[0], POSITION_DECIMALS)
                              if prima_posizione else None),
        "start_lon_rounded": (round(prima_posizione[1], POSITION_DECIMALS)
                              if prima_posizione else None),
    }


def judge(misure: dict, device_distance_m: float | None) -> tuple[bool, str | None]:
    """Se questa registrazione regge una lettura a tratti, e se no perché.

    Il motivo non è cortesia: «di questa gara posso dirti il totale, non come
    l'hai distribuita» è una risposta, «nessun dato» non lo è.
    """
    punti = misure["points"]
    if punti < 2:
        return False, "La registrazione non contiene abbastanza punti."

    copertura = misure["gps_points"] / punti
    if copertura < MIN_GPS_COVERAGE:
        return False, (
            f"Il GPS ha un punto valido sul {copertura:.0%} della "
            f"registrazione: sotto il {MIN_GPS_COVERAGE:.0%} i tratti "
            "mancanti sono troppi per leggere come è stata distribuita.")

    scarto = misure.get("distance_gap")
    if scarto is not None and abs(scarto) > MAX_DISTANCE_GAP:
        return False, (
            f"La distanza ricalcolata dal GPS differisce del {scarto:+.0%} da "
            "quella dell'orologio: i due numeri non descrivono la stessa "
            "nuotata, e da qui non si sa quale dei due sbagli.")
    return True, None


def load_downloaded(connection):
    """Aggiunge le sole tracce FIT locali mancanti, senza riscrivere lo storico."""
    candidates=connection.execute("""SELECT activity_id,distance_m FROM canonical_activities a
        WHERE environment='open_water' AND NOT EXISTS
        (SELECT 1 FROM activity_track t WHERE t.activity_id=a.activity_id)""").fetchall()
    imported=0
    errors=[]
    for identifier,distance in candidates:
        path=source_catalog.RAW_FIT/f'{identifier}.fit'
        if not path.exists():continue
        try:
            content=path.read_bytes()
            points=_points(content)
            if not points:continue
            source=source_catalog.describe(content,'fit',path.relative_to(paths.ROOT).as_posix(),PARSER,PARSER_VERSION)
            now=datetime.now(timezone.utc).replace(tzinfo=None)
            track_rows,measures=_rows(identifier,points,source.source_object_id,now)
            # Stesso criterio dell'import storico, senza nuove soglie.
            gap=(measures['gps_distance_m']/distance-1) if distance else None
            measures['distance_gap']=gap
            passed,reason=judge(measures,distance)
            quality=(identifier,measures['points'],measures['gps_points'],
                measures['gps_points']/measures['points'] if measures['points'] else None,
                measures['gps_distance_m'],distance,gap,measures['median_interval_s'],
                measures['has_heart_rate'],passed,reason,source.source_object_id,now,
                measures['start_lat_rounded'],measures['start_lon_rounded'])
            connection.execute('BEGIN')
            try:
                swim_details._bulk_insert(connection,'activity_track',TRACK_COLUMNS,track_rows)
                connection.execute('DELETE FROM activity_track_quality WHERE activity_id=?',[identifier])
                swim_details._bulk_insert(connection,'activity_track_quality',QUALITY_COLUMNS,[quality])
                source_catalog.register(connection,[source])
                connection.execute('COMMIT')
            except Exception:
                connection.execute('ROLLBACK');raise
            imported+=1
        except Exception as error:
            errors.append({'activity_id':identifier,'error':type(error).__name__})
    return {'activities_parsed':imported,'errors':errors}


def load(connection: duckdb.DuckDBPyConnection,
         limit: int | None = None) -> TrackReport:
    """Importa la traccia delle nuotate in mare e delle gare collegate."""
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run_id = source_catalog.start_run(connection, "track")

    candidate = _eligible(connection)
    if limit:
        candidate = candidate[:limit]
    sorgenti_per_attivita = _sources(connection)

    righe_traccia: list[tuple] = []
    righe_qualita: list[tuple] = []
    descritte: list[source_catalog.SourceObject] = []
    senza_sorgente = senza_punti = passati = 0

    archivi = _archives()
    try:
        for activity_id, distanza in candidate:
            locator = sorgenti_per_attivita.get(int(activity_id))
            if not locator or "/" not in locator:
                senza_sorgente += 1
                continue
            contenuto = _content(locator, archivi)
            if contenuto is None:
                senza_sorgente += 1
                continue

            punti = _points(contenuto)
            if not punti:
                senza_punti += 1
                continue

            descritta = source_catalog.describe(
                contenuto, "fit", locator, PARSER, PARSER_VERSION)
            descritte.append(descritta)

            righe, misure = _rows(int(activity_id), punti,
                                  descritta.source_object_id, imported_at)
            misure["distance_gap"] = (
                (misure["gps_distance_m"] / distanza - 1)
                if distanza else None)
            regge, motivo = judge(misure, distanza)
            passati += regge

            righe_traccia.extend(righe)
            righe_qualita.append((
                int(activity_id), misure["points"], misure["gps_points"],
                misure["gps_points"] / misure["points"] if misure["points"] else None,
                misure["gps_distance_m"], distanza, misure["distance_gap"],
                misure["median_interval_s"], misure["has_heart_rate"],
                regge, motivo, descritta.source_object_id, imported_at,
                misure["start_lat_rounded"], misure["start_lon_rounded"]))
    finally:
        for archivio in archivi.values():
            archivio.close()

    connection.execute("BEGIN TRANSACTION")
    try:
        for tabella in ("activity_track", "activity_track_quality"):
            connection.execute(f"DELETE FROM {tabella}")
        swim_details._bulk_insert(connection, "activity_track",
                                  TRACK_COLUMNS, righe_traccia)
        swim_details._bulk_insert(connection, "activity_track_quality",
                                  QUALITY_COLUMNS, righe_qualita)
        registrate = source_catalog.register(connection, descritte)
        source_catalog.finish_run(connection, run_id, "ok",
                                  rows=len(righe_traccia), sources=registrate)
    except BaseException as errore:
        connection.execute("ROLLBACK")
        source_catalog.finish_run(connection, run_id, "failed",
                                  note=f"{type(errore).__name__}: {errore}")
        raise
    connection.execute("COMMIT")

    return TrackReport(
        eligible=len(candidate),
        imported=len(righe_qualita),
        without_source=senza_sorgente,
        without_points=senza_punti,
        points=len(righe_traccia),
        passing_gate=passati,
    )
