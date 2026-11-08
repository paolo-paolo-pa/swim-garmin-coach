"""L'aggiornamento automatico dei dati, senza dover ricordare un comando.

## La domanda dell'atleta

*"I dati che sto guardando sono di oggi?"*

Un coach che ragiona su dati di tre giorni fa non è un coach cauto: è un coach
che sbaglia con sicurezza. L'unico modo perché la risposta sia sempre sì è che
l'aggiornamento non dipenda dalla memoria di nessuno.

## Perché non uno script PowerShell

Su questo computer l'esecuzione degli script ``.ps1`` è disattivata, ed è una
protezione di Windows che non si tocca per far girare un progetto personale.
``schtasks.exe`` è un eseguibile di sistema: non è uno script, non passa da
quella policy, e fa esattamente la stessa cosa.

## Tre volte al giorno

Le decisioni di allenamento hanno granularità oraria, non di minuti. Tre
passaggi bastano e uno cade sempre dopo l'allenamento tipico. Ogni esecuzione
scrive l'esito in ``data/sync.log``: un aggiornamento fallito in silenzio è
peggio di un aggiornamento mancato, perché lascia credere che i dati siano
freschi.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from . import paths

TASK_NAME = "GarminCoach-Sync"

# Ogni otto ore a partire dalle 06:30 → 06:30, 14:30, 22:30.
FIRST_RUN = "06:30"
HOURS_BETWEEN_RUNS = 8

LOG = paths.DATA / "sync.log"

# ``pythonw.exe`` invece di ``python.exe``: l'aggiornamento non deve far
# comparire una finestra nera mentre l'atleta sta facendo altro.
PYTHON = paths.ROOT / ".venv" / "Scripts" / "pythonw.exe"


class SchedulerUnavailable(RuntimeError):
    """Windows non ha accettato il comando. Il messaggio riporta il suo, non uno
    inventato: è l'unico che dice davvero cosa è successo."""


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *arguments], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def is_installed() -> bool:
    return _run(["/Query", "/TN", TASK_NAME]).returncode == 0


def install() -> str:
    """Registra l'aggiornamento automatico. Sovrascrive quello esistente."""
    if not PYTHON.exists():
        raise SchedulerUnavailable(
            f"Ambiente Python non trovato in {PYTHON}. "
            "Va creato prima di programmare l'aggiornamento.")

    result = _run([
        "/Create", "/TN", TASK_NAME,
        # `aggiorna` e non `sync`: il sync da solo porta i riepiloghi e lascia
        # fuori tutto il dettaglio. Al 24/08/2026 questo significava 36 nuotate
        # su 36 successive all'export senza un lap — cioè l'intera preparazione
        # verso place22 invisibile a qualunque analisi che guardi dentro una
        # seduta. L'automazione che l'atleta ha chiesto è la catena intera, non
        # il primo anello.
        "/TR", f'"{PYTHON}" -m garmin_coach update',
        "/SC", "HOURLY", "/MO", str(HOURS_BETWEEN_RUNS), "/ST", FIRST_RUN,
        "/F",
    ])
    if result.returncode != 0:
        raise SchedulerUnavailable(
            (result.stderr or result.stdout).strip()
            or f"schtasks è uscito con codice {result.returncode}")

    hours = [(int(FIRST_RUN[:2]) + step * HOURS_BETWEEN_RUNS) % 24
             for step in range(24 // HOURS_BETWEEN_RUNS)]
    return ", ".join(f"{h:02d}:{FIRST_RUN[3:]}" for h in sorted(hours))


def remove() -> bool:
    """Toglie l'aggiornamento automatico. Vero se c'era qualcosa da togliere."""
    if not is_installed():
        return False
    result = _run(["/Delete", "/TN", TASK_NAME, "/F"])
    if result.returncode != 0:
        raise SchedulerUnavailable((result.stderr or result.stdout).strip())
    return True


@dataclass(frozen=True)
class LastRun:
    when: datetime
    line: str


def last_logged_run() -> LastRun | None:
    """L'ultima esecuzione registrata, per poter dire se l'automatismo gira
    davvero invece di limitarsi a essere installato."""
    if not LOG.exists():
        return None
    entries = [line for line in LOG.read_text(encoding="utf-8",
                                              errors="replace").splitlines()
               if line.startswith("[")]
    if not entries:
        return None
    last = entries[-1]
    try:
        when = datetime.fromisoformat(last[1:last.index("]")])
    except (ValueError, IndexError):
        return None
    return LastRun(when, last[last.index("]") + 1:].strip())


def append_to_log(outcome: str) -> None:
    """Registra l'esito di un aggiornamento. Vale sia per quelli automatici sia
    per quelli lanciati a mano: un solo registro, una sola storia."""
    paths.ensure_data_dirs()
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    compact = " · ".join(part.strip() for part in outcome.splitlines()
                         if part.strip())
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {compact}\n")
