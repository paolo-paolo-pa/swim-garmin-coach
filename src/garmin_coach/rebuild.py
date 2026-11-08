"""Cancellare il database e riottenerlo identico (D6).

## Perché è la prova che conta

Tutte le altre garanzie di questo progetto sono affermazioni sul codice. Questa
è una prova sul risultato: se il database si ricostruisce dalle sorgenti e due
ricostruzioni producono lo stesso contenuto, allora **nessun dato vive soltanto
lì dentro**. Un file corrotto, un disco perso, un errore di migrazione: si
rifà.

Se invece le due ricostruzioni divergono, qualcosa dipende dall'ordine, dal
caso o dall'orologio — e quel qualcosa sta già sporcando le analisi senza che
si veda.

## Il digest canonico

Somma il contenuto di ogni tabella escludendo ciò che **deve** cambiare fra due
esecuzioni: il momento dell'import, l'identificativo dell'esecuzione, l'ora di
applicazione di una migrazione. Sono metadati sull'atto di importare, non sui
dati importati; includerli farebbe fallire il confronto per il motivo sbagliato.

## Un solo scrittore

DuckDB accetta un solo scrittore per volta. Senza un lock, un sync automatico
che parte mentre è in corso una ricostruzione produce un errore illeggibile —
è già successo in questo progetto, con il server MCP che teneva il file aperto.
Qui il secondo arrivato riceve una frase che dice chi ha il file e cosa fare.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timedelta

import duckdb

from . import paths

LOCK = paths.DATA / "scrittura.lock"

# Oltre questa età un lock è considerato dimenticato da un processo morto.
# Nessuna operazione di scrittura di questo progetto dura così a lungo:
# la più lenta, la ricostruzione completa, sta sotto i quindici minuti.
STALE_LOCK_AFTER = timedelta(hours=2)

# Colonne che raccontano *quando* è avvenuto un import, non *cosa* è stato
# importato. Devono cambiare fra due esecuzioni: includerle nel digest
# significherebbe far fallire il confronto per il motivo sbagliato.
VOLATILE_COLUMNS = {
    "imported_at", "observed_at", "applied_at", "decided_at", "fetched_at",
    "started_at", "finished_at", "run_id",
}

# ingest_runs è per intero un registro di esecuzioni: due ricostruzioni ne
# hanno per forza di righe diverse, ed è giusto così.
VOLATILE_TABLES = {"ingest_runs"}


class DatabaseBusy(RuntimeError):
    """Un'altra scrittura è in corso."""


@contextmanager
def single_writer(what: str):
    """Garantisce che una sola scrittura per volta tocchi il database."""
    paths.ensure_data_dirs()
    now = datetime.now()

    if LOCK.exists():
        age = now - datetime.fromtimestamp(LOCK.stat().st_mtime)
        holder = LOCK.read_text(encoding="utf-8", errors="replace").strip()
        if age < STALE_LOCK_AFTER:
            raise DatabaseBusy(
                f"Il database è già in scrittura: {holder}\n"
                f"  iniziata {int(age.total_seconds() // 60)} minuti fa.\n"
                "Attendere che finisca. Se quel processo non esiste più, il file "
                f"da rimuovere è {LOCK}")
        LOCK.unlink(missing_ok=True)   # lock dimenticato da un processo morto

    LOCK.write_text(f"{what} (processo {os.getpid()}, avviato {now:%H:%M:%S})",
                    encoding="utf-8")
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def _stable_columns(connection: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [name for (name,) in connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY column_name",
        [table]).fetchall() if name not in VOLATILE_COLUMNS
        or (table=='health_samples' and name=='observed_at')]


def canonical_digest(connection: duckdb.DuckDBPyConnection) -> dict:
    """L'impronta del contenuto, tabella per tabella e complessiva.

    Ordinata per colonne e per righe, così due database con lo stesso contenuto
    scritto in ordine diverso danno la stessa impronta.
    """
    # Solo le tabelle vere. Una vista non ha contenuto proprio: è una lettura
    # di ciò che c'è già, e includerla farebbe pesare due volte le stesse righe
    # — una riga cancellata da `activities` sposterebbe due impronte invece di
    # una, e la diagnosi indicherebbe due tabelle diverse per un fatto solo.
    tables = sorted(name for (name,) in connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'").fetchall()
        if name not in VOLATILE_TABLES)

    per_table: dict[str, str] = {}
    overall = hashlib.sha256()
    for table in tables:
        columns = _stable_columns(connection, table)
        if not columns:
            continue
        selected = ", ".join(f'"{c}"' for c in columns)
        digest = connection.execute(f"""
            SELECT md5(string_agg(riga, '|' ORDER BY riga))
            FROM (SELECT to_json(({selected}))::VARCHAR AS riga FROM "{table}")
        """).fetchone()[0] or "vuota"
        count = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        per_table[table] = f"{digest}:{count}"
        overall.update(f"{table}={per_table[table]};".encode())

    return {"overall": overall.hexdigest(), "tables": per_table}


def differences(before: dict, after: dict) -> list[str]:
    """Che cosa è cambiato fra due impronte, in parole."""
    names = sorted(set(before["tables"]) | set(after["tables"]))
    changed = []
    for name in names:
        old = before["tables"].get(name)
        new = after["tables"].get(name)
        if old == new:
            continue
        if old is None:
            changed.append(f"{name}: comparsa ({new.split(':')[1]} righe)")
        elif new is None:
            changed.append(f"{name}: sparita (aveva {old.split(':')[1]} righe)")
        else:
            old_rows, new_rows = old.split(":")[1], new.split(":")[1]
            if old_rows != new_rows:
                changed.append(f"{name}: da {old_rows} a {new_rows} righe")
            else:
                changed.append(f"{name}: stesse {new_rows} righe, contenuto diverso")
    return changed


def rebuild(with_details: bool = True) -> dict:
    """Ricostruisce tutto dalle sorgenti locali, senza rete.

    L'ordine è obbligato: prima l'export, poi le catture del sync che lo
    prolungano, poi ciò che si deriva da entrambi.

    ## Perché su un candidato e non in loco

    Prima si cancellava ``coach.duckdb`` e lo si rifaceva al suo posto. Se la
    ricostruzione si fermava a metà — un FIT illeggibile, un ``Ctrl+C``, il
    computer che si spegne — quello che restava non era il database di prima e
    non era quello nuovo. La copia di sicurezza c'era, ma rimetterla a posto è
    un gesto manuale da fare nel momento in cui si è appena persa la fiducia
    nello strumento.

    Ora il database nuovo nasce accanto a quello vero e prende il suo posto in
    un colpo solo, quando è finito e ha superato i controlli. Se qualcosa si
    rompe, il file vivo non è mai stato toccato e del tentativo non resta
    niente. Il candidato sta nella stessa cartella perché ``os.replace`` sia una
    sostituzione e non una copia fra dischi.
    """
    from . import paths as percorsi

    candidato = percorsi.DATABASE.with_name(percorsi.DATABASE.name + ".candidato")
    _forget(candidato)

    try:
        report = _build_into(candidato, with_details)
    except BaseException:
        _forget(candidato)
        raise

    _promote(candidato, percorsi.DATABASE)
    return report


def _forget(percorso) -> None:
    """Cancella un database candidato e il suo giornale, se ci sono."""
    for suffisso in (".wal", ""):
        percorso.with_name(percorso.name + suffisso).unlink(missing_ok=True)


def _promote(candidato, vivo) -> None:
    """Mette il candidato al posto del database vivo, in un colpo solo."""
    import os

    if not candidato.exists():
        raise RuntimeError(
            "La ricostruzione non ha prodotto nessun database: il file vivo "
            "non è stato toccato.")
    # Il giornale del candidato è già stato riversato alla chiusura della
    # connessione; quello del vivo descrive un file che sta per non esserci più.
    vivo.with_name(vivo.name + ".wal").unlink(missing_ok=True)
    os.replace(candidato, vivo)


def _build_into(percorso, with_details: bool) -> dict:
    from . import corrections, database, race_corrections
    from .ingest import (health, health_samples, snapshot_replay, summaries, swim_details,
                         sync, track)
    from .metrics import daily_status

    report: dict = {}
    with database.connect(path=percorso) as connection:
        report["activities"] = summaries.load(connection)["rows"]
        report["health"] = sum(entry["rows"] for entry in health.load(connection))

        # L'export si ferma a una data. Le settimane successive esistono solo
        # nelle catture del sync: senza rigiocarle la ricostruzione sarebbe
        # completa e monca insieme — e sono proprio i giorni che il coach usa
        # per rispondere a "come sto oggi".
        replay = snapshot_replay.SnapshotClient()
        report["snapshots"] = replay.coverage()
        if report["snapshots"]["days"]:
            replayed = sync.pull(connection, client=replay)
            report["replayed_activities"] = replayed.activities_written
            report["replayed_health_days"] = replayed.health_days_written
            if replayed.errors:
                report["replay_errors"] = replayed.errors

        report['intraday_replay']=health_samples.replay_all(connection)

        # Le correzioni prima del calcolo, sempre: `daily_status` aggrega, e
        # un'attività esclusa che entra nell'aggregato non esce più — il suo
        # carico resta dentro le finestre a 28 giorni per quattro settimane.
        report["corrections"] = corrections.apply(connection)
        report["race_corrections"] = race_corrections.apply(connection)
        report["daily_status"] = daily_status.build(connection)["rows"]
        if with_details:
            detail = swim_details.load(connection)
            report["laps"] = detail.laps
            report["lengths"] = detail.lengths
            report["verdicts"] = detail.verdicts
            # La traccia viene dopo il dettaglio e non prima: legge gli agganci
            # che `swim_details` ha appena deciso, invece di rifare quel lavoro
            # e poterlo fare in modo diverso.
            traccia = track.load(connection)
            report["track_points"] = traccia.points
            report["track_gate_ok"] = traccia.passing_gate
        report["digest"] = canonical_digest(connection)["overall"]
    return report
