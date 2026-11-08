"""Le migrazioni dello schema, applicate una volta sola e verificabili (D1).

## Il problema che risolve

Lo schema nasceva da ``CREATE TABLE IF NOT EXISTS``. Sembra prudente e invece
mente: **una colonna aggiunta oggi non comparirà mai in un database creato
ieri**. Il codice la usa, il file non ce l'ha, e l'errore arriva a runtime su
una query, lontano dalla causa.

È già successo in questo progetto: le tabelle del dettaglio FIT sono comparse
solo perché il database veniva ricostruito da zero. Su un database preesistente
sarebbero mancate in silenzio.

## Come funziona

Ogni cambiamento è un file ``NNNN-nome-descrittivo.sql`` in ``migrations/``.
Si applicano in ordine di nome, una volta sola, e ognuna lascia una riga in
``schema_migrations`` con il proprio SHA-256.

I file sono numerati perché l'ordine **è** il significato: la 0003 presuppone
che la 0002 sia passata. È l'unica numerazione ammessa dalla Regola Aurea n.1
oltre a ``knowledge/``, e per la stessa ragione: qui l'indice non decora, indica.

## Perché il checksum

Una migrazione già applicata è storia. Modificarne il testo dopo significa che
il database reale e il file non descrivono più la stessa cosa, e nessuno se ne
accorge finché non si ricostruisce da zero e i due mondi divergono.

Se il testo cambia, l'applicazione si ferma con un errore leggibile invece di
proseguire su una bugia (criterio 20 della Macro-proposta 3).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import duckdb

FOLDER = Path(__file__).resolve().parent / "migrations"

REGISTRY = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id   VARCHAR PRIMARY KEY,   -- il nome del file, senza estensione
    sha256         VARCHAR NOT NULL,      -- impronta del testo applicato
    applied_at     TIMESTAMP NOT NULL,
    statements     INTEGER NOT NULL
);
"""


class MigrationChanged(RuntimeError):
    """Una migrazione già applicata ha un testo diverso da quello registrato."""


@dataclass(frozen=True)
class Migration:
    identifier: str
    sql: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover() -> list[Migration]:
    """Le migrazioni sul disco, in ordine di applicazione."""
    return [Migration(path.stem, path.read_text(encoding="utf-8"))
            for path in sorted(FOLDER.glob("*.sql"))]


def _statements(sql: str) -> list[str]:
    """Le istruzioni di un file, senza i commenti che le separano.

    DuckDB esegue più istruzioni in una volta, ma così l'errore indica il file
    invece dell'istruzione: separarle costa poco e dice dove si è rotto.
    """
    cleaned = "\n".join(line for line in sql.splitlines()
                        if not line.lstrip().startswith("--"))
    return [piece.strip() for piece in cleaned.split(";") if piece.strip()]


def applied(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    connection.execute(REGISTRY)
    return dict(connection.execute(
        "SELECT migration_id, sha256 FROM schema_migrations").fetchall())


def apply(connection: duckdb.DuckDBPyConnection) -> list[str]:
    """Porta il database allo schema descritto dai file. Restituisce le nuove.

    Idempotente: rieseguirla non applica niente e non è un errore.
    """
    from datetime import datetime

    already = applied(connection)
    fresh: list[str] = []

    for migration in discover():
        known = already.get(migration.identifier)
        if known is not None:
            if known != migration.sha256:
                raise MigrationChanged(
                    f"La migrazione {migration.identifier} è già stata applicata "
                    f"il database, ma il file è cambiato da allora.\n"
                    f"  registrato: {known[:16]}…\n"
                    f"  sul disco:  {migration.sha256[:16]}…\n"
                    "Una migrazione applicata è storia: per cambiare lo schema "
                    "si aggiunge un file nuovo, non si riscrive quello vecchio.")
            continue

        pieces = _statements(migration.sql)
        for statement in pieces:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (migration_id, sha256, applied_at, "
            "statements) VALUES (?, ?, ?, ?)",
            [migration.identifier, migration.sha256, datetime.now(), len(pieces)])
        fresh.append(migration.identifier)

    return fresh


def combined_sql() -> str:
    """Tutte le migrazioni in fila, per costruire un database di prova.

    Applicarle in sequenza a un database vuoto è per definizione lo stesso
    risultato di applicarle una per volta: è ciò che rende il cancello D1
    ("database nuovo e database esistente arrivano allo stesso schema")
    verificabile invece che dichiarato.
    """
    return REGISTRY + "\n" + "\n".join(m.sql for m in discover())
