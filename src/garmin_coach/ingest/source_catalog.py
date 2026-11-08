"""Il catalogo delle sorgenti: da dove viene ogni riga (D2).

## Il problema

Finora la provenienza era una stringa dentro ogni tabella, e non sempre la
stessa cosa: uno SHA-256 vero per i file dell'export, un URI
`fit://archivio.zip/file.fit` o `garmin-connect://activity/12345` per tutto il
resto — e tutti quanti dentro una colonna chiamata `source_sha`. Le vasche non
ne avevano nessuna.

Una colonna che si chiama `sha` e contiene un URI è peggio di una colonna
assente: chi la legge non ha motivo di dubitarne.

## Cosa fa

Registra **la cosa da cui si legge** — un file dell'export, un membro di uno
ZIP, una risposta salvata di Garmin Connect — con il suo SHA-256 reale. Ogni
riga granulare punta qui con `source_object_id`.

L'identificatore è `sha256[:16]` più la posizione. Deriva dal contenuto, quindi
**è stabile fra due ricostruzioni**: è ciò che rende confrontabile il digest di
due rebuild senza dipendere dall'ora in cui sono stati fatti (cancello D6).

## Cosa non fa

Non copia i contenuti dentro DuckDB. L'export resta dov'è ed è immutabile; il
catalogo lo indicizza. Duplicare 39.470 file dentro il database per poterli
tracciare sarebbe scambiare la tracciabilità per l'archiviazione.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .. import paths

# Dove finiscono le risposte live prima di essere interpretate. Append-only:
# un file scritto qui non viene più modificato, così una risposta di Garmin
# resta rigiocabile anche se il parser cambia idea su come leggerla.
RAW = paths.DATA / "raw" / "garmin-connect"

# I file originali delle attività scaricati dal sync. Stanno accanto agli
# snapshot JSON e seguono la stessa regola: append-only, mai sovrascritti.
#
# Sono la continuazione degli ZIP dell'export, non un doppione: l'export si
# ferma al 4 luglio 2026 e da lì in poi i FIT possono arrivare soltanto da qui.
RAW_FIT = paths.DATA / "raw" / "activity-files"

# Oltre questa soglia conviene comprimere e deduplicare. Oggi la cartella pesa
# decine di kilobyte: costruire quella macchina adesso significherebbe
# mantenerla per un problema che non esiste. Lo strumento lo dirà da solo.
COMPRESSION_THRESHOLD_MB = 100


@dataclass(frozen=True)
class SourceObject:
    source_object_id: str
    kind: str
    locator: str
    sha256: str
    size_bytes: int
    parser: str | None = None
    parser_version: str | None = None


def identify(sha256: str, locator: str) -> str:
    """L'identificatore di una sorgente: contenuto più posizione.

    Il contenuto da solo non basta — due file identici in due archivi diversi
    sono due sorgenti — e la posizione da sola nemmeno, perché lo stesso
    percorso può contenere cose diverse in momenti diversi.
    """
    tail = hashlib.sha256(locator.encode("utf-8")).hexdigest()[:8]
    return f"{sha256[:16]}-{tail}"


def describe(content: bytes, kind: str, locator: str,
             parser: str | None = None,
             parser_version: str | None = None) -> SourceObject:
    digest = hashlib.sha256(content).hexdigest()
    return SourceObject(identify(digest, locator), kind, locator, digest,
                        len(content), parser, parser_version)


def register(connection: duckdb.DuckDBPyConnection,
             objects: list[SourceObject]) -> int:
    """Aggiunge al catalogo le sorgenti non ancora conosciute."""
    if not objects:
        return 0
    observed = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [(o.source_object_id, o.kind, o.locator, o.sha256, o.size_bytes,
             observed, o.parser, o.parser_version) for o in objects]
    before = connection.execute("SELECT count(*) FROM source_objects").fetchone()[0]
    connection.executemany(
        "INSERT OR IGNORE INTO source_objects (source_object_id, kind, locator, "
        "sha256, size_bytes, observed_at, parser, parser_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    after = connection.execute("SELECT count(*) FROM source_objects").fetchone()[0]
    return after - before


def capture(payload: object, endpoint: str, day: str) -> SourceObject:
    """Salva una risposta di Garmin **prima** di interpretarla.

    Senza questo, una risposta esiste soltanto come riga già trasformata: se
    domani si scopre che un campo era stato letto male — è già successo con la
    lunghezza vasca in centimetri — l'unico modo di rimediare è richiedere tutto
    a Garmin. Su un account che è già stato bloccato con un 429, non è un piano.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         default=str).encode("utf-8")

    folder = RAW / day
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{endpoint}.json"
    locator = destination.relative_to(paths.ROOT).as_posix()
    described = describe(content, "garmin_connect", locator,
                         parser="sync", parser_version="1")

    # Append-only: se il file esiste già con lo stesso contenuto non si tocca,
    # se esiste con contenuto diverso si affianca invece di sovrascrivere.
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() == described.sha256:
            return described
        destination = folder / f"{endpoint}-{described.sha256[:8]}.json"
        locator = destination.relative_to(paths.ROOT).as_posix()
        described = describe(content, "garmin_connect", locator,
                             parser="sync", parser_version="1")

    destination.write_bytes(content)
    return described


def capture_file(content: bytes, activity_id: int,
                 suffix: str = ".fit") -> SourceObject:
    """Salva il file originale di un'attività, così com'è arrivato.

    Non passa da `capture` perché quella serializza in JSON: un FIT è binario, e
    un binario dentro un JSON è il modo di conservare un file rendendolo
    illeggibile a chiunque lo apra.

    Append-only come gli snapshot. Se il file esiste già identico non si tocca;
    se esiste diverso si affianca, perché Garmin può aver ricalcolato
    un'attività e le due versioni sono due fatti, non un errore.
    """
    RAW_FIT.mkdir(parents=True, exist_ok=True)
    destination = RAW_FIT / f"{activity_id}{suffix}"
    impronta = hashlib.sha256(content).hexdigest()

    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() == impronta:
            return describe(content, "fit", _fit_locator(destination),
                            parser="fit-download", parser_version="1")
        destination = RAW_FIT / f"{activity_id}-{impronta[:8]}{suffix}"

    destination.write_bytes(content)
    return describe(content, "fit", _fit_locator(destination),
                    parser="fit-download", parser_version="1")


def _fit_locator(destination: Path) -> str:
    return destination.relative_to(paths.ROOT).as_posix()


def raw_size_mb() -> float:
    if not RAW.exists():
        return 0.0
    return sum(f.stat().st_size for f in RAW.rglob("*") if f.is_file()) / 1024 / 1024


def compression_advice() -> str | None:
    """Dice quando è il momento di comprimere, invece di deciderlo in anticipo."""
    size = raw_size_mb()
    if size < COMPRESSION_THRESHOLD_MB:
        return None
    return (f"Le catture in data/raw/ pesano {size:.0f} MB, oltre la soglia di "
            f"{COMPRESSION_THRESHOLD_MB} MB. È il momento di comprimerle e "
            "deduplicarle per contenuto.")


def start_run(connection: duckdb.DuckDBPyConnection, command: str) -> str:
    """Apre un'esecuzione di import. L'identificatore serve a chiuderla."""
    run_id = datetime.now().strftime("%Y%m%d%H%M%S-") + command
    connection.execute(
        "INSERT OR REPLACE INTO ingest_runs (run_id, started_at, command, "
        "code_version, outcome) VALUES (?, ?, ?, ?, 'running')",
        [run_id, datetime.now(), command, _code_version()])
    return run_id


def finish_run(connection: duckdb.DuckDBPyConnection, run_id: str, outcome: str,
               rows: int = 0, sources: int = 0, note: str = "") -> None:
    connection.execute(
        "UPDATE ingest_runs SET finished_at = ?, outcome = ?, rows_written = ?, "
        "sources_read = ?, note = ? WHERE run_id = ?",
        [datetime.now(), outcome, rows, sources, note or None, run_id])


def _code_version() -> str | None:
    """Il commit da cui gira questo codice, se il progetto è in git.

    Serve a rispondere «con quale versione del parser è entrata questa riga»
    senza doverlo scrivere a mano da nessuna parte.
    """
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=paths.ROOT, capture_output=True, text=True,
                                timeout=5)
        return result.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None
