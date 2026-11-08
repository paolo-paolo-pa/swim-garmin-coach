"""Dove si trova ogni cosa nel progetto.

Unico posto in cui compaiono percorsi assoluti. Se il progetto viene spostato,
si cambia solo qui.
"""

from __future__ import annotations

from pathlib import Path

# La radice è due livelli sopra src/garmin_coach/
ROOT = Path(__file__).resolve().parents[2]

# Sorgente immutabile — sola lettura assoluta (Regola Aurea n.4)
EXPORT = ROOT / "garmin-export"

# Artefatti generati — mai versionati (Regola Aurea n.1 punto 5)
DATA = ROOT / "data"
DATABASE = DATA / "coach.duckdb"
STAGING = DATA / "staging"

# Memoria dell'atleta e competenza — markdown, versionati
COACH = ROOT / "coach"
KNOWLEDGE = ROOT / "knowledge"
DOCS = ROOT / "docs"


def _garmin_root() -> Path:
    """La cartella con GUID dentro l'export. Il nome cambia a ogni export Garmin,
    quindi va cercato invece che scritto a mano."""
    candidates = [p for p in EXPORT.iterdir() if p.is_dir() and (p / "DI_CONNECT").is_dir()]
    if not candidates:
        raise FileNotFoundError(
            f"Nessuna cartella DI_CONNECT trovata sotto {EXPORT}. "
            "L'export Garmin è al posto giusto?"
        )
    return candidates[0]


def connect_dir(subfolder: str) -> Path:
    """Una sottocartella di DI_CONNECT, es. 'DI-Connect-Fitness'."""
    return _garmin_root() / "DI_CONNECT" / subfolder


def ensure_data_dirs() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
