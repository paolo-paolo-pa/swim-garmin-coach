"""Le gare che nessun archivio cronometra, dichiarate dall'atleta.

## Perché serve una terza sorgente di gare

Aquatime copre la vasca, Icron le acque libere italiane del proprio circuito, e
fra le due resta un buco che non è teorico: **l'atleta ha nuotato almeno tre
event02 sui 10 km — place23, place05 e place21 — e in archivio ce n'era
uno.** Il coach, di conseguenza, ha scritto «il tuo unico 10 km», che era falso.

Non è un difetto dell'import. È un limite della sorgente, e un limite di
sorgente si copre aggiungendo una sorgente, non allargando le maglie di quelle
che ci sono.

## Perché una gara dichiarata non è una gara di serie B

È un fatto misurato da terzi — c'era un cronometro, c'era un'organizzazione —
che semplicemente non è finito in una piattaforma che sappiamo leggere. Entra in
`races` come le altre, conta nei conteggi, e porta con sé
`distance_source = 'athlete_declared'`: la vista `pool_races`, che alimenta
record e velocità critica, richiede `certified_pool` e quindi non la vede mai.
In mare invece entra a pieno titolo, perché lì **nessuna** distanza è misurata e
quella dichiarata dall'atleta non è meno affidabile di quella dichiarata da
Icron.

## Una gara senza tempo non è una gara non valida

Sono tre situazioni diverse e diventano tre stati diversi: `valid` quando il
tempo c'è e si legge, `time_unknown` quando la gara è successa e il risultato
ufficiale non si trova, `invalid` quando nella casella c'è scritto qualcosa che
non si legge — che è un errore da correggere, non un silenzio.

Comprimerle in due avrebbe fatto sparire dai conteggi una gara vera solo perché
nessuno ne ricorda il tempo. La Regola Aurea n.5 lo vieta esplicitamente.

## Il tempo dell'orologio non è il tempo di gara

Su place05 2019 l'orologio dice 6.975 m in 2h13'; il risultato ufficiale è
10 km in 3h00'46". Parte quando si preme e si ferma quando si preme. Per questo
il tempo si scrive a mano e `activity_id` è **solo un collegamento**: serve a
mettere accanto la distanza dichiarata e quella misurata, che è il confronto che
rende leggibile una gara in mare. Non viene mai usato per riempire un tempo
mancante.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from .. import paths
from . import source_catalog

PARSER = "declared_races"
PARSER_VERSION = "1"
KIND = "declared_races"

FILE_NAME = "gare-dichiarate.md"
EXAMPLE_MARKER = "(esempio)"

DECLARED = "athlete_declared"
DEFAULT_ENVIRONMENT = "acque libere"

# Da dove viene il tempo. Vuoto significa cronometro: è il caso normale, e
# l'atleta che scrive un risultato ufficiale non deve dover dichiarare anche
# l'ovvio.
#
# `watch_trimmed` esiste per la decisione dell'atleta del 24/08/2026, che
# ribalta esplicitamente la regola del giorno prima. Il controesempio resta:
# su place05 2019 orologio e cronometro differiscono di quarantasette minuti.
CHRONOMETER = "chronometer"
WATCH = "watch_trimmed"
WATCH_WORDS = {"orologio", "garmin", "watch"}

# Tre stati, e non due, perché tre sono le situazioni vere.
#
# `valid`        c'è un tempo e si legge.
# `time_unknown` la gara è successa e il tempo non lo si ha — perché il
#                risultato ufficiale non si trova più, o perché l'atleta non
#                l'ha ancora cercato. **Non è una gara non valida.**
# `invalid`      l'atleta ha scritto qualcosa nella casella del tempo e quel
#                qualcosa non si legge: è un errore da correggere, e va
#                distinto dal silenzio.
#
# La Regola Aurea n.5 lo chiede esplicitamente: `missing`, `insufficient_data`
# e `invalid` non sono sinonimi e non si comprimono in un'unica etichetta.
VALID = "valid"
TIME_UNKNOWN = "time_unknown"
INVALID = "invalid"


@dataclass(frozen=True)
class DeclaredRace:
    day: date
    meet: str
    venue: str | None
    distance_m: int | None
    time_s: float | None
    time_written: str
    environment: str
    overall_place: int | None
    activity_id: int | None
    notes: str
    time_source_written: str = ""

    @property
    def status(self) -> str:
        if self.time_s is not None:
            return VALID
        return INVALID if self.time_written.strip() else TIME_UNKNOWN

    @property
    def time_source(self) -> str | None:
        """Chi ha misurato il tempo. Niente tempo, niente origine."""
        if self.time_s is None:
            return None
        parola = self.time_source_written.strip().lower()
        return WATCH if parola in WATCH_WORDS else CHRONOMETER


def parse_day(text: str) -> date | None:
    trovato = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", text or "")
    if not trovato:
        return None
    anno, mese, giorno = (int(g) for g in trovato.groups())
    try:
        return date(anno, mese, giorno)
    except ValueError:
        return None


def parse_distance(text: str) -> int | None:
    """«10 km» → 10000, «5000 m» → 5000. Quello che non si legge resta assente."""
    pulito = (text or "").strip().lower().replace(",", ".")
    chilometri = re.search(r"(\d+(?:\.\d+)?)\s*km\b", pulito)
    if chilometri:
        return round(float(chilometri.group(1)) * 1000)
    metri = re.search(r"(\d{3,6})", pulito)
    return int(metri.group(1)) if metri else None


def parse_time(text: str) -> float | None:
    """«3:00:46» e «44:25» → secondi.

    Due formati perché una 10 km si scrive con le ore e un miglio no. Chiedere
    sempre le ore su una gara da venti minuti farebbe scrivere `0:22:51` a chi
    ha in mente `22:51`, e la prima cifra sbagliata diventerebbe ventidue ore.
    """
    pulito = (text or "").strip()
    con_ore = re.fullmatch(r"(\d{1,2})[:.](\d{1,2})[:.](\d{2})(?:[,.](\d{1,3}))?",
                           pulito)
    if con_ore:
        ore, minuti, secondi, frazione = con_ore.groups()
        valore = int(ore) * 3600 + int(minuti) * 60 + int(secondi)
        return valore + (int(frazione) / 10 ** len(frazione) if frazione else 0)

    solo_minuti = re.fullmatch(r"(\d{1,3})[:.](\d{2})(?:[,.](\d{1,3}))?", pulito)
    if solo_minuti:
        minuti, secondi, frazione = solo_minuti.groups()
        valore = int(minuti) * 60 + int(secondi)
        return valore + (int(frazione) / 10 ** len(frazione) if frazione else 0)
    return None


def parse_place(text: str) -> int | None:
    trovato = re.search(r"(\d+)", text or "")
    return int(trovato.group(1)) if trovato else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def race_id(day: date, meet: str) -> str:
    return f"dichiarata-{day.isoformat()}-{_slug(meet)}"


def _path() -> Path:
    return paths.COACH / FILE_NAME


def _rows(text: str) -> list[list[str]]:
    """Le righe della tabella markdown, senza intestazione né separatore."""
    righe = []
    for linea in text.splitlines():
        pulita = linea.strip()
        if not pulita.startswith("|"):
            continue
        celle = [c.strip() for c in pulita.strip("|").split("|")]
        if not celle or set("".join(celle)) <= set("-: "):
            continue
        righe.append(celle)
    return righe[1:] if righe else []


def declared() -> list[DeclaredRace]:
    """Le gare dichiarate, saltando quelle che non si leggono.

    Una riga scritta male viene ignorata e non fa cadere le altre: un file
    compilato a mano è quasi sempre un po' sbagliato, e rifiutarlo per intero
    significherebbe non usarlo mai.
    """
    percorso = _path()
    if not percorso.exists():
        return []

    trovate: list[DeclaredRace] = []
    for celle in _rows(percorso.read_text(encoding="utf-8")):
        if any(EXAMPLE_MARKER in cella for cella in celle) or len(celle) < 5:
            continue
        giorno = parse_day(celle[0])
        nome = celle[1].strip()
        if giorno is None or not nome:
            continue
        piene = celle + [""] * (10 - len(celle))
        trovate.append(DeclaredRace(
            day=giorno,
            meet=nome,
            venue=piene[2] or None,
            distance_m=parse_distance(piene[3]),
            time_s=parse_time(piene[4]),
            time_written=piene[4],
            environment=(piene[5].strip().lower() or DEFAULT_ENVIRONMENT),
            overall_place=parse_place(piene[6]),
            activity_id=(int(piene[7]) if piene[7].strip().isdigit() else None),
            notes=piene[8],
            time_source_written=piene[9]))
    return sorted(trovate, key=lambda una: una.day)


def _owned(connection: duckdb.DuckDBPyConnection) -> list[str]:
    return [riga[0] for riga in connection.execute(
        "SELECT source_object_id FROM source_objects "
        "WHERE kind = ? AND parser = ?", [KIND, PARSER]).fetchall()]


def load(connection: duckdb.DuckDBPyConnection) -> dict:
    """Importa le gare dichiarate. Idempotente: rifarlo non cambia niente."""
    percorso = _path()
    gare = declared()
    posseduti = set(_owned(connection))

    sorgenti = []
    if percorso.exists():
        sorgente = source_catalog.describe(
            percorso.read_bytes(), KIND,
            percorso.relative_to(paths.ROOT).as_posix()
            if paths.ROOT in percorso.parents else FILE_NAME,
            PARSER, PARSER_VERSION)
        sorgenti.append(sorgente)
        posseduti.add(sorgente.source_object_id)

    adesso = datetime.now()
    righe = [(
        race_id(una.day, una.meet), una.day, una.meet, "gara dichiarata",
        una.distance_m, None, False, None, None, una.time_s,
        una.status,
        None, None, None, None, None,
        sorgenti[0].source_object_id if sorgenti else "declared",
        adesso, una.environment,
        DECLARED if una.distance_m is not None else "unknown",
        una.venue, una.overall_place, None,
        # Il collegamento alla nuotata registrata. Fino alla migrazione 0011
        # questo valore veniva letto dal markdown, contato nel rapporto come
        # `linked_to_garmin` e poi buttato: non esisteva una colonna dove
        # metterlo, e il rapporto tornava lo stesso.
        una.activity_id,
        una.time_source,
    ) for una in gare]

    connection.execute("BEGIN TRANSACTION")
    try:
        if sorgenti:
            source_catalog.register(connection, sorgenti)
        if posseduti:
            segnaposto = ", ".join("?" for _ in posseduti)
            connection.execute(
                f"DELETE FROM race_splits WHERE source_object_id IN ({segnaposto})",
                list(posseduti))
            connection.execute(
                f"DELETE FROM races WHERE source_object_id IN ({segnaposto})",
                list(posseduti))
        if righe:
            connection.executemany(
                "INSERT OR REPLACE INTO races (race_id, race_date, meet, "
                " event_label, distance_m, stroke, is_relay, relay_legs, "
                " pool_length_m, time_s, status, timing, federation, category, "
                " meet_id, event_id, source_object_id, imported_at, "
                " environment, distance_source, venue, overall_place, "
                " category_place, activity_id, time_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                " ?, ?, ?, ?, ?, ?, ?)", righe)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    return {
        "races": len(righe),
        "linked_to_garmin": sum(1 for una in gare if una.activity_id),
        "without_time": sum(1 for una in gare if una.status == TIME_UNKNOWN),
        "unreadable_time": sum(1 for una in gare if una.status == INVALID),
    }
