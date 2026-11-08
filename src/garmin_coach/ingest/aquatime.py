"""Lo storico gare ufficiale, dalla federazione e non dall'orologio.

## La domanda a cui risponde

*«Qual è il mio tempo vero sulla distanza, e come è cambiato negli anni?»*

`coach/riferimenti.md` dichiara bloccate tre cose finché non esiste almeno un
tempo prestativo confermato: la velocità critica, gli intervalli di passo di una
serie, e qualunque previsione di gara. Qui arrivano 116 righe sorgente, che
diventano 114 risultati distinti dopo due duplicati, cronometrati da una piastra
fra il 2014 e il 2026.

## Dove sta la sorgente, e perché lì

In `coach/aquatime/atleta/`, dove l'atleta l'ha messa. Non è `garmin-export/`
e non è `data/raw/`: è un terzo tipo di sorgente — un export che l'atleta ha
scaricato da sé — e spostarla per farla somigliare alle altre due sarebbe
riordinare le cose di una persona per comodità di un programma. È sola lettura
come tutte le sorgenti.

## Le tre cose che questo importatore non fa

**Non attribuisce le staffette all'atleta.** Otto risultati su 114 sono
staffette: il tempo è della squadra e i passaggi descrivono quattro frazioni
senza dire quale sia la sua. Entrano con `is_relay` vero, e la vista
`personal_races` le lascia fuori da ogni lettura di prestazione. Anche potendo
riconoscere la frazione, resterebbe non confrontabile: chi parte dal secondo
cambio parte lanciato, e nuota qualche decimo più veloce di quanto sappia fare.

**Non trasforma una squalifica in un tempo.** `time_s` resta NULL e `status`
dice `disqualified`.

**Non ricalcola i parziali dai cumulativi.** Quando la federazione espone il
parziale lo si conserva; quando manca, resta NULL. Un parziale ricostruito è un
valore derivato che assomiglia a una misura, ed è esattamente ciò che la Regola
Aurea n.5 tiene separato.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from .. import paths
from . import source_catalog

PARSER = "aquatime"
PARSER_VERSION = "2"

FOLDER = "aquatime"
RACES_SUFFIX = "_gare_complete.csv"
SPLITS_SUFFIX = "_passaggi.csv"

# Come la federazione scrive gli stili, e come li scrive il resto del progetto.
STROKES = {
    "stile libero": "stile",
    "dorso": "dorso",
    "rana": "rana",
    "farfalla": "delfino",
    "misti": "misti",
}

DISQUALIFIED = "disqualified"
INVALID = "invalid"
VALID = "valid"

# Cosa sono queste gare, detto dall'importatore invece che lasciato dedurre.
#
# La migrazione 0009 riempie le due colonne per le righe già in archivio, e non
# basta: questo importatore cancella e riscrive le proprie righe a ogni
# `ingest`, e senza queste costanti le riscriverebbe vuote — la migrazione è
# già passata e non torna indietro. È successo davvero, al primo `ingest` in
# cui le due sorgenti di gare hanno convissuto: le 114 gare in vasca sono
# tornate con `environment` a NULL e la vista `pool_races` si è svuotata.
ENVIRONMENT = "piscina"
CERTIFIED_POOL = "certified_pool"


@dataclass(frozen=True)
class Event:
    """Che gara è, letta dall'etichetta della federazione."""

    distance_m: int | None
    stroke: str | None
    is_relay: bool
    relay_legs: int | None


def parse_event(label: str) -> Event:
    """«4x100 Stile Libero» → una frazione da 100 a stile, in staffetta.

    ``distance_m`` è la **frazione**, non il totale: in una 4x100 il numero che
    serve per confrontare è 100, perché è quello che l'atleta ha nuotato. Il
    totale si ricava da `relay_legs` e nessuna lettura lo usa come distanza
    personale.
    """
    testo = (label or "").strip().lower()
    staffetta = re.search(r"(\d+)\s*x\s*(\d+)", testo)
    if staffetta:
        frazioni, metri = int(staffetta.group(1)), int(staffetta.group(2))
        return Event(metri, _stroke(testo), True, frazioni)

    distanza = re.search(r"(\d+)", testo)
    return Event(int(distanza.group(1)) if distanza else None,
                 _stroke(testo), False, None)


def _stroke(testo: str) -> str | None:
    for federale, nostro in STROKES.items():
        if federale in testo:
            return nostro
    return None


def parse_time(text: str) -> float | None:
    """«01'00''21» → 60.21 secondi. «Squalificato» → niente.

    Il formato della federazione usa apostrofi e non due punti, e i centesimi
    sono sempre due cifre. Una stringa che non ha quella forma non viene
    indovinata: restituisce ``None``, e chi chiama decide cosa significa.
    """
    trovato = re.fullmatch(r"\s*(\d+)'(\d+)''(\d+)\s*", text or "")
    if not trovato:
        return None
    minuti, secondi, centesimi = (int(g) for g in trovato.groups())
    return minuti * 60 + secondi + centesimi / 100


def parse_clock(text: str) -> float | None:
    """«1:08.46» o «33.77» → secondi. Il formato dei passaggi, diverso da sopra."""
    pulito = (text or "").strip().strip("()[]").strip()
    if not pulito:
        return None
    trovato = re.fullmatch(r"(?:(\d+):)?(\d+)(?:\.(\d+))?", pulito)
    if not trovato:
        return None
    minuti, secondi, decimali = trovato.groups()
    valore = (int(minuti) * 60 if minuti else 0) + int(secondi)
    if decimali:
        valore += float(f"0.{decimali}")
    return valore


def parse_day(text: str) -> date | None:
    trovato = re.fullmatch(r"\s*(\d{2})/(\d{2})/(\d{4})\s*", text or "")
    if not trovato:
        return None
    giorno, mese, anno = (int(g) for g in trovato.groups())
    return date(anno, mese, giorno)


def parse_pool(text: str) -> int | None:
    trovato = re.search(r"(\d+)", text or "")
    return int(trovato.group(1)) if trovato else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def race_id(day: date, event_id: str, label: str) -> str:
    """L'identificatore di una gara: giorno, evento della federazione, specialità.

    Deterministico di proposito. La sorgente contiene **due righe identiche
    ripetute** — 08/11/2015 e 14/01/2018, stesso `event_id`, stesso tempo: un
    artefatto di come è stata raccolta, non due gare. Con una chiave costruita
    dal contenuto la seconda sovrascrive la prima invece di diventare un
    doppione che poi conta due volte in ogni media.
    """
    return f"{day.isoformat()}-{event_id or 'na'}-{_slug(label)}"


def _folder() -> Path:
    return paths.COACH / FOLDER


def _files(suffix: str) -> list[Path]:
    """I file dell'atleta, e soltanto i suoi.

    `coach/compagni_squadra/` contiene gli stessi export per altre cinque
    persone. Sono dati di terzi: non entrano in questo archivio, e la ricerca
    parte da `coach/aquatime/` proprio per non poterli raggiungere per sbaglio.
    """
    cartella = _folder()
    if not cartella.exists():
        return []
    return sorted(uno for uno in cartella.rglob(f"*{suffix}") if uno.is_file())


def _locator(path: Path) -> str:
    """Dove sta il file, detto in modo che si possa mostrare a chiunque.

    Relativo alla radice del progetto, come ogni altra provenienza. Se il file
    finisce fuori dalla radice — succede solo quando qualcuno la sposta sotto ai
    piedi del programma — resta il nome, **non** il percorso assoluto: quello
    contiene il nome utente e finirebbe dentro qualunque copia del database.
    """
    try:
        return path.relative_to(paths.ROOT).as_posix()
    except ValueError:
        return f"{FOLDER}/{path.name}"


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load(connection: duckdb.DuckDBPyConnection) -> dict:
    """Importa gare e passaggi. Idempotente: rifarlo non cambia niente.

    Riscrive **solo** le righe che questa sorgente possiede. Non c'è ancora una
    seconda sorgente di gare, e proprio per questo la cancellazione è mirata:
    quando arriverà, il difetto che ne nascerebbe è già stato commesso una volta
    in questo progetto — `all` che arretrava il database — e non si ripete.
    """
    file_gare = _files(RACES_SUFFIX)
    file_passaggi = _files(SPLITS_SUFFIX)
    if not file_gare:
        posseduti = [riga[0] for riga in connection.execute(
            "SELECT source_object_id FROM source_objects "
            "WHERE kind = 'aquatime' AND parser = ?", [PARSER]).fetchall()]
        if posseduti:
            segnaposto = ", ".join("?" for _ in posseduti)
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(
                    f"DELETE FROM race_splits WHERE source_object_id IN ({segnaposto})",
                    posseduti)
                connection.execute(
                    f"DELETE FROM races WHERE source_object_id IN ({segnaposto})",
                    posseduti)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return {"races": 0, "splits": 0, "files": 0, "skipped": [],
                "duplicates": 0, "relays": 0, "disqualified": 0}

    adesso = datetime.now()
    sorgenti, gare, scartate = [], {}, []

    for percorso in file_gare:
        contenuto = percorso.read_bytes()
        sorgente = source_catalog.describe(
            contenuto, "aquatime", _locator(percorso),
            PARSER, PARSER_VERSION)
        sorgenti.append(sorgente)

        for riga in _rows(percorso):
            giorno = parse_day(riga.get("data", ""))
            vasca = parse_pool(riga.get("vasca", ""))
            etichetta = (riga.get("tipo") or "").strip()
            if giorno is None or vasca is None or not etichetta:
                scartate.append(
                    f"{riga.get('data', '?')} {etichetta or 'senza specialità'}: "
                    "manca la data, la vasca o la specialità")
                continue

            gara = parse_event(etichetta)
            tempo = parse_time(riga.get("tempo", ""))
            grezzo = (riga.get("tempo") or "").strip()
            squalificata = grezzo.lower().startswith("squalif")
            stato = (VALID if tempo is not None else
                     DISQUALIFIED if squalificata else INVALID)
            if tempo is None and not squalificata:
                scartate.append(f"{giorno} {etichetta}: tempo «{grezzo}» "
                                "in un formato che non riconosco")

            identificativo = race_id(giorno, riga.get("event_id", ""), etichetta)
            gare[identificativo] = (
                identificativo, giorno, (riga.get("gara") or "").strip(),
                etichetta, gara.distance_m, gara.stroke, gara.is_relay,
                gara.relay_legs, vasca, tempo, stato,
                (riga.get("crono") or "").strip() or None,
                (riga.get("federazione") or "").strip() or None,
                (riga.get("categoria") or "").strip() or None,
                (riga.get("meet_id") or "").strip() or None,
                (riga.get("event_id") or "").strip() or None,
                sorgente.source_object_id, adesso,
                ENVIRONMENT, CERTIFIED_POOL)

    passaggi = {}
    for percorso in file_passaggi:
        contenuto = percorso.read_bytes()
        sorgente = source_catalog.describe(
            contenuto, "aquatime", _locator(percorso),
            PARSER, PARSER_VERSION)
        sorgenti.append(sorgente)

        for riga in _rows(percorso):
            giorno = parse_day(riga.get("data", ""))
            etichetta = (riga.get("tipo") or "").strip()
            metri = parse_pool(riga.get("distanza", ""))
            if giorno is None or metri is None:
                continue
            identificativo = race_id(giorno, "", etichetta)
            # Il file dei passaggi non porta `event_id`: la gara si ritrova per
            # giorno e specialità. Se quella coppia non è una sola gara, il
            # passaggio non si sa a quale appartiene e non entra.
            candidate = [chiave for chiave in gare
                         if chiave.startswith(f"{giorno.isoformat()}-")
                         and chiave.endswith(f"-{_slug(etichetta)}")]
            if len(candidate) != 1:
                scartate.append(
                    f"{giorno} {etichetta}: passaggio a {metri} m che "
                    f"corrisponde a {len(candidate)} gare, non a una")
                continue
            passaggi[(candidate[0], metri)] = (
                candidate[0], metri, parse_clock(riga.get("cumulativo", "")),
                parse_clock(riga.get("parziale", "")),
                parse_clock(riga.get("staffetta", "")),
                sorgente.source_object_id, adesso)

    precedenti = {riga[0] for riga in connection.execute(
        "SELECT source_object_id FROM source_objects "
        "WHERE kind = 'aquatime' AND parser = ?", [PARSER]).fetchall()}
    posseduti = precedenti | {
        sorgente.source_object_id for sorgente in sorgenti}
    segnaposto = ", ".join("?" * len(posseduti))

    connection.execute("BEGIN TRANSACTION")
    try:
        source_catalog.register(connection, sorgenti)
        connection.execute(
            f"DELETE FROM race_splits WHERE source_object_id IN ({segnaposto})",
            list(posseduti))
        connection.execute(
            f"DELETE FROM races WHERE source_object_id IN ({segnaposto})",
            list(posseduti))
        if gare:
            connection.executemany(
                "INSERT OR REPLACE INTO races (race_id, race_date, meet, event_label, "
                " distance_m, stroke, is_relay, relay_legs, pool_length_m, time_s, "
                " status, timing, federation, category, meet_id, event_id, "
                " source_object_id, imported_at, environment, distance_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                " ?, ?)",
                list(gare.values()))
        if passaggi:
            connection.executemany(
                "INSERT OR REPLACE INTO race_splits (race_id, split_m, cumulative_s, "
                " split_s, leg_s, source_object_id, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", list(passaggi.values()))
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    lette = sum(len(_rows(uno)) for uno in file_gare)
    return {
        "races": len(gare),
        "splits": len(passaggi),
        "files": len(file_gare) + len(file_passaggi),
        "duplicates": lette - len(gare) - len(
            [nota for nota in scartate if "manca la data" in nota]),
        "relays": sum(1 for riga in gare.values() if riga[6]),
        "disqualified": sum(1 for riga in gare.values() if riga[10] == DISQUALIFIED),
        "skipped": scartate,
    }
