"""Unico percorso di scrittura verso il database.

Nessun altro modulo scrive in ``data/coach.duckdb``. Le sorgenti in
``garmin-export/`` non vengono mai modificate (Regola Aurea n.4).
"""

from . import health, summaries

__all__ = ["health", "summaries"]
