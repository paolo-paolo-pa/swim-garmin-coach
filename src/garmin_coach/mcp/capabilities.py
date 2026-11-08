"""Che cosa il coach sa fare oggi, e cosa non sa ancora fare.

Il progetto cresce per fasi, ma i nomi degli strumenti non cambiano mai: uno
strumento che dipende da una fase non completata non deve rompersi né inventare.
Restituisce una risposta chiara che dice *cosa* manca e *quale fase* lo porterà.

È il criterio C10c: nessuna query verso una tabella che non esiste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from ..database import table_exists

# Quanti giorni di ritardo sono ancora accettabili perché i dati siano "di oggi".
# Oltre questa soglia il coach deve dirlo, non tacere (rischio dichiarato in §16).
FRESHNESS_TOLERANCE_DAYS = 3


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    phase: int
    explanation: str


def _table_has_rows(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    if not table_exists(connection, table):
        return False
    return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0


def survey(connection: duckdb.DuckDBPyConnection,
           races_defined: bool = False) -> dict[str, Capability]:
    """Fotografa le capacità disponibili adesso."""
    history = _table_has_rows(connection, "activities")
    status = _table_has_rows(connection, "daily_status")
    sets = _table_has_rows(connection, "activity_laps")

    last_day = None
    if status:
        last_day = connection.execute(
            "SELECT max(status_date) FROM daily_status").fetchone()[0]
    fresh = bool(last_day and
                 (date.today() - last_day) <= timedelta(days=FRESHNESS_TOLERANCE_DAYS))

    return {
        "history": Capability(
            "history", history and status, 1,
            "Storia completa delle attività e stato giornaliero."),
        "session_detail": Capability(
            "session_detail", sets, 5,
            "Serie, vasche e analisi per stile. Richiedono i file FIT, che "
            "vengono elaborati nella Fase 5. Fino ad allora una seduta è "
            "leggibile solo nei suoi totali."),
        "fresh_data": Capability(
            "fresh_data", fresh, 3,
            "Sincronizzazione con Garmin Connect. Senza, i dati si fermano "
            "all'ultimo export."),
        "race_planning": Capability(
            "race_planning", races_defined, 4,
            "Pianificazione verso una gara. Richiede almeno una gara con data "
            "in coach/gare.md."),
    }


def unavailable(capability: Capability, detail: str = "") -> dict:
    """La risposta standard quando una capacità non c'è ancora."""
    return {
        "error": "CAPABILITY_NOT_AVAILABLE",
        "capability": capability.name,
        "requires_phase": capability.phase,
        "message": capability.explanation + (f" {detail}" if detail else ""),
    }
