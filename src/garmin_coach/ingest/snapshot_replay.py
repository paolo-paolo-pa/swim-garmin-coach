"""Rigiocare le risposte salvate invece di richiederle a Garmin (D2, D6).

## Perché esiste

Il criterio dice: *il database si ricostruisce senza rete da export + snapshot
già acquisiti*. Senza questo modulo la frase sarebbe mezza vera — la
ricostruzione riportava le 1.471 attività dell'export e perdeva le settimane
recenti, quelle che il coach usa davvero per rispondere a «come sto oggi».

L'ho scoperto nel modo peggiore: eseguendo due ricostruzioni per dimostrare che
producevano lo stesso risultato. Lo producevano, ed erano entrambe monche.

## Come funziona

Espone gli stessi metodi del client Garmin, leggendoli da
``data/raw/garmin-connect/``. Il codice del sync non sa la differenza e non
deve saperla: è la stessa normalizzazione, sugli stessi byte, senza rete.

Questo lo rende anche il modo di correggere un errore di interpretazione
scoperto dopo. La lunghezza vasca arrivava in centimetri e per accorgersene ci
è voluto un giorno: se fosse successo su dati vecchi, senza snapshot l'unico
rimedio sarebbe stato richiedere tutto a Garmin.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import source_catalog


class SnapshotClient:
    """Il client Garmin, servito dal disco.

    Non eredita da niente e non ha bisogno di farlo: il sync chiama metodi, e
    questi metodi ci sono. I metodi di scrittura non esistono nemmeno come
    concetto — non c'è niente su cui scrivere.
    """

    def __init__(self, folder: Path | None = None):
        self.folder = folder or source_catalog.RAW

    # ── lettura dal disco ──────────────────────────────────────────────────

    def _days(self) -> list[Path]:
        if not self.folder.exists():
            return []
        return sorted(day for day in self.folder.iterdir() if day.is_dir())

    def source_path(self, day: str, endpoint: str):
        folder = self.folder / day
        candidates = list(folder.glob(f"{endpoint}.json")) + list(folder.glob(f"{endpoint}-*.json"))
        if not candidates:
            return None
        return max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name))

    def _read(self, day: str, endpoint: str):
        target=self.source_path(day,endpoint)
        return json.loads(target.read_text(encoding="utf-8")) if target else None

    # ── la stessa superficie del client vero ───────────────────────────────

    def get_activities_by_date(self, start, end):
        """Tutte le attività catturate nell'intervallo.

        Le catture si sovrappongono di proposito — il sync riscarica sempre
        qualche giorno all'indietro perché Garmin corregge i dati del giorno
        prima. Qui si deduplica per ``activityId`` tenendo l'ultima versione
        vista, che è la più corretta.
        """
        found: dict = {}
        for day in self._days():
            if not (start <= day.name <= end):
                continue
            payload = self._read(day.name, "get_activities_by_date")
            for activity in payload or []:
                identifier = activity.get("activityId")
                if identifier is not None:
                    found[identifier] = activity
        return list(found.values())

    def get_user_summary(self, day):
        return self._read(str(day), "get_user_summary")

    def get_sleep_data(self, day):
        return self._read(str(day), "get_sleep_data")

    def get_hrv_data(self, day):
        return self._read(str(day), "get_hrv_data")

    def get_full_name(self):
        return "(dalle catture locali)"

    # ── quanto copre ───────────────────────────────────────────────────────

    def coverage(self) -> dict:
        days = self._days()
        return {
            "days": len(days),
            "first": days[0].name if days else None,
            "last": days[-1].name if days else None,
            "files": sum(1 for _ in self.folder.rglob("*.json")) if days else 0,
        }
