"""Che acqua e che vento c'era, il giorno di una gara in mare.

## La domanda dell'atleta

*«Non ho bisogno di una precisione millimetrica, ma almeno di avere dei
parametri chiari da poter confrontare.»*

Due nuotate in mare sulla stessa distanza dichiarata, con tempi diversi, oggi
non si possono confrontare: manca il pezzo che spiega la differenza. Un'acqua a
19 °C con mezzo metro d'onda e un'acqua a 24 °C piatta non sono la stessa gara,
e il passo da solo non lo dice.

## Da dove arrivano

**Open-Meteo**, archivio storico e modello marino. Gratuito, senza chiave,
senza account. Due chiamate per gara, e mai più: la risposta si salva come
snapshot e da lì in poi il progetto funziona senza rete, esattamente come già
fa con le risposte di Garmin.

## Cosa esce dal computer, esattamente

Una **data** e una **posizione arrotondata a un decimo di grado**, cioè circa
undici chilometri. Nient'altro: non il nome dell'atleta, non l'ora esatta di
partenza, non un identificativo, non un tempo.

L'arrotondamento non è simbolico. È la risoluzione a cui i modelli lavorano
comunque, quindi una posizione più precisa non darebbe una risposta migliore:
dice in quale tratto di costa si nuotava, non da quale spiaggia si è partiti.

Autorizzato dall'atleta il 24/08/2026.

## Cosa questi numeri non sono

**Non sono una misura di quella gara.** Sono la ricostruzione di un modello su
una griglia di chilometri. La corrente sotto costa — quella che un nuotatore
sente davvero — non ci sta dentro, e infatti questo modulo non la chiede
nemmeno: la corrente si misura dall'asimmetria per direzione della nuotata
stessa, che è un dato dell'atleta e non di un modello.

Servono a due cose oneste: dare **contesto** a un tempo, e fare da **riscontro**
a quella misura interna. Non entrano mai in una formula che corregge un tempo.

## La finestra

Si media sulle ore che la nuotata ha davvero attraversato, non sull'intera
giornata: una gara alle otto del mattino e il pomeriggio dello stesso giorno
possono avere venti opposti, e la media delle ventiquattr'ore descriverebbe una
giornata che nessuno ha nuotato.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import duckdb

from . import source_catalog

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

MODEL = "open-meteo"
TIMEOUT_S = 25

AIR_FIELDS = "temperature_2m,wind_speed_10m,wind_direction_10m"
SEA_FIELDS = "wave_height,wave_direction,sea_surface_temperature"

CONDITION_COLUMNS = [
    "activity_id", "observed_date", "from_hour_utc", "to_hour_utc",
    "air_temperature_c", "water_temperature_c", "wind_speed_kmh",
    "wind_direction_deg", "wave_height_m", "wave_direction_deg",
    "hours_covered", "model", "source_object_id", "imported_at",
]


class WeatherUnavailable(RuntimeError):
    """Il servizio non ha risposto. Non è un errore dell'archivio."""


@dataclass(frozen=True)
class WeatherReport:
    candidates: int
    fetched: int
    failed: int

    @property
    def still_missing(self) -> int:
        return self.candidates - self.fetched


def _get(url: str, parametri: dict) -> dict:
    indirizzo = f"{url}?{urllib.parse.urlencode(parametri)}"
    try:
        with urllib.request.urlopen(indirizzo, timeout=TIMEOUT_S) as risposta:
            return json.load(risposta)
    except (urllib.error.URLError, TimeoutError, ValueError) as errore:
        raise WeatherUnavailable(str(errore)) from errore


def _mean(valori: list) -> float | None:
    """La media dei valori che ci sono. Un buco non diventa uno zero."""
    presenti = [uno for uno in valori if uno is not None]
    return sum(presenti) / len(presenti) if presenti else None


def _circular_mean(gradi: list) -> float | None:
    """La media di direzioni, che non è la media dei numeri.

    Fra 350° e 10° la media aritmetica dà 180 — cioè esattamente la direzione
    opposta a quella vera. Le direzioni si mediano come vettori, e questa è la
    ragione per cui esiste una funzione invece di un `avg`.
    """
    import math

    presenti = [uno for uno in gradi if uno is not None]
    if not presenti:
        return None
    x = sum(math.cos(math.radians(uno)) for uno in presenti)
    y = sum(math.sin(math.radians(uno)) for uno in presenti)
    if x == 0 and y == 0:
        return None
    gradi = math.degrees(math.atan2(y, x)) % 360
    # `atan2` su due direzioni simmetriche rispetto al nord restituisce un
    # epsilon negativo, e `% 360` lo trasforma in **360,0**: la direzione è
    # giusta e il numero è quello che non esiste. Nord è zero.
    return 0.0 if gradi >= 360 - 1e-9 else gradi


def _window(hourly: dict, campo: str, da: int, a: int) -> list:
    """I valori di un campo nelle ore che la nuotata ha attraversato."""
    valori = hourly.get(campo) or []
    return [valori[ora] for ora in range(da, min(a + 1, len(valori)))]


def candidates(connection: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Le nuotate in mare con una posizione e senza condizioni già scaricate.

    Tutte quelle registrate da Garmin in acque libere, qualunque distanza —
    per decisione dell'atleta del 24/08/2026: «prendi tutti i dati meteo che
    hai a disposizione». Prima si chiedeva solo per le gare collegate o le
    uscite oltre i 3 km; il filtro escludeva proprio le uscite corte che poi
    servono da confronto per le gare lunghe.
    """
    return connection.execute("""
        SELECT q.activity_id, a.activity_date, a.start_time_utc, a.duration_s,
               q.start_lat_rounded, q.start_lon_rounded
        FROM activity_track_quality q
        JOIN canonical_activities a ON a.activity_id = q.activity_id
        WHERE q.start_lat_rounded IS NOT NULL
          AND a.pool_length_m IS NULL
          AND NOT EXISTS (SELECT 1 FROM race_conditions c
                          WHERE c.activity_id = q.activity_id)
        ORDER BY a.activity_date DESC
    """).fetchall()


def _hours_of(start, duration_s) -> tuple[int, int]:
    """Le ore UTC che la nuotata attraversa, estremi compresi."""
    prima = start.hour
    fine = start.hour + int((duration_s or 0) // 3600)
    return prima, min(fine, 23)


def fetch_one(activity_id: int, giorno, start, duration_s,
              lat: float, lon: float) -> tuple[tuple, list]:
    """Le condizioni di una nuotata, e gli snapshot delle due risposte."""
    da, a = _hours_of(start, duration_s)
    comune = {"latitude": lat, "longitude": lon,
              "start_date": giorno.isoformat(), "end_date": giorno.isoformat(),
              "timezone": "UTC"}

    aria = _get(ARCHIVE_URL, {**comune, "hourly": AIR_FIELDS})
    snapshot = [source_catalog.capture(aria, "open-meteo-archive",
                                       giorno.isoformat())]

    # Il modello marino non copre i laghi. Un'assenza non è un errore: è la
    # risposta giusta per una traversata del lake01, e va distinta da un
    # guasto di rete.
    try:
        mare = _get(MARINE_URL, {**comune, "hourly": SEA_FIELDS})
        snapshot.append(source_catalog.capture(mare, "open-meteo-marine",
                                               giorno.isoformat()))
        ore_mare = mare.get("hourly") or {}
    except WeatherUnavailable:
        ore_mare = {}

    ore_aria = aria.get("hourly") or {}
    riga = (
        activity_id, giorno, da, a,
        _mean(_window(ore_aria, "temperature_2m", da, a)),
        _mean(_window(ore_mare, "sea_surface_temperature", da, a)),
        _mean(_window(ore_aria, "wind_speed_10m", da, a)),
        _circular_mean(_window(ore_aria, "wind_direction_10m", da, a)),
        _mean(_window(ore_mare, "wave_height", da, a)),
        _circular_mean(_window(ore_mare, "wave_direction", da, a)),
        a - da + 1, MODEL, snapshot[0].source_object_id,
        datetime.now(timezone.utc).replace(tzinfo=None),
    )
    return riga, snapshot


def pull(connection: duckdb.DuckDBPyConnection,
         limit: int | None = None) -> WeatherReport:
    """Scarica le condizioni mancanti. Idempotente: chiede solo ciò che manca."""
    da_fare = candidates(connection)
    if limit:
        da_fare = da_fare[:limit]

    righe: list[tuple] = []
    descritte: list[source_catalog.SourceObject] = []
    falliti = 0

    for activity_id, giorno, start, durata, lat, lon in da_fare:
        try:
            riga, snapshot = fetch_one(int(activity_id), giorno, start,
                                       durata, lat, lon)
        except WeatherUnavailable:
            # Una gara senza meteo è una gara senza meteo, non un import
            # fallito: al passaggio successivo ci si riprova.
            falliti += 1
            continue
        righe.append(riga)
        descritte.extend(snapshot)

    if righe:
        connection.execute("BEGIN TRANSACTION")
        try:
            source_catalog.register(connection, descritte)
            connection.executemany(
                f"INSERT OR REPLACE INTO race_conditions "
                f"({', '.join(CONDITION_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in CONDITION_COLUMNS)})", righe)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    return WeatherReport(candidates=len(da_fare), fetched=len(righe),
                         failed=falliti)
