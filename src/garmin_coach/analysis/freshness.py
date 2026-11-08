"""Fino a quando arrivano i dati, e quanto è vecchio quel «fino a».

## Perché è una domanda dell'atleta

«Come sto oggi?» ha una risposta diversa se i dati si fermano a tre giorni fa.
Una pagina che scrive «oggi» in cima e mostra numeri di martedì non è
imprecisa: sta rispondendo a una domanda diversa da quella che è stata fatta.

L'app deve mostrare **la data reale dei dati**, non la data del calendario. È un
vincolo misurabile del §10 della Macro-proposta 4, ed è anche ciò che rende
onesta la modalità offline: senza rete i dati restano quelli dell'ultimo sync
riuscito, e va detto invece che nascosto.
"""

from __future__ import annotations

from datetime import date, datetime

import duckdb

from ..database import table_exists
from .insight import Freshness


def of_database(connection: duckdb.DuckDBPyConnection,
                today: date | None = None) -> Freshness:
    """La freschezza dello stato giornaliero, che è il dato più recente che c'è."""
    today = today or date.today()
    last_day = None
    if table_exists(connection, "daily_status"):
        last_day = connection.execute(
            "SELECT max(status_date) FROM daily_status").fetchone()[0]
    return Freshness(
        data_through=last_day,
        generated_at=datetime.now(),
        days_behind=(today - last_day).days if last_day else None,
    )
