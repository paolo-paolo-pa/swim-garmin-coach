"""Adapter ufficiale: aggiorna lo stesso archivio, senza password o secondo DB.

Domanda: «Come aggiorno i miei dati con la chiave Personal API?»
Le risposte originali vengono catturate prima di normalizzarle. Gli errori
pubblici contengono solo stato HTTP e tipo; mai corpi HTTP o credenziali.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import paths
from . import source_catalog

STORE = paths.DATA / "garmin_personal"


class PersonalApiFailure(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.stop_sync = status in (401, 403, 429)


class PersonalGarmin:
    def __init__(self, client=None):
        self.auth = None
        if client is None:
            from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator
            key = os.environ.get("GARMIN_PERSONAL_API_KEY")
            if not key:
                key = (STORE / "api-key").read_text(encoding="utf-8").strip()
            self.auth = PersonalApiAuthenticator(bearer_token_cache_file=STORE / "bearer.json")
            try:
                token = self.auth.obtain_token(key)
            except Exception as error:
                raise PersonalApiFailure("Autenticazione Personal API non riuscita") from None
            client = GarminPersonalApiClient(token.access_token)
        self.client = client

    def _call(self, method, *args, **kwargs):
        for attempt in range(3):
            try:
                result = getattr(self.client, method)(*args, **kwargs)
                if result is not None and not isinstance(result, bytes):
                    source_catalog.capture(result, "personal_" + method, str(args[0] if args else "activities")[:10])
                return result
            except Exception as error:
                status = getattr(error, "status_code", None)
                if status in (500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                # 429 and auth failures stop immediately; no repeated login loop.
                raise PersonalApiFailure(f"Personal API: HTTP {status or 'rete'} ({type(error).__name__})", status) from None

    def get_activities_by_date(self, start, end):
        rows = []
        offset = 0
        while True:
            page = self._call("search_activities", start=offset, limit=100,
                              start_date=start, end_date=end) or []
            rows.extend(page)
            if len(page) < 100:
                source_catalog.capture(rows, "get_activities_by_date", start)
                return rows
            offset += len(page)
            if offset >= 10000:
                raise PersonalApiFailure("Paginazione oltre il limite di sicurezza")

    def get_user_summary(self, day):
        result = self._call("get_daily_summaries", day, day) or {}
        rows = result.get("data", []) if isinstance(result, dict) else result
        normalized = normalize_summary(rows[0]) if rows else None
        if normalized:
            source_catalog.capture(normalized, "get_user_summary", day)
        return normalized

    def get_sleep_data(self, day):
        result = self._call("get_daily_sleep", day)
        if result and "dailySleepDTO" not in result:
            result = {"dailySleepDTO": result}
        if result:
            source_catalog.capture(result, "get_sleep_data", day)
        return result

    def get_hrv_data(self, day):
        result = self._call("get_daily_hrv", day)
        if result:
            source_catalog.capture(result, "get_hrv_data", day)
        return result

    def download_activity(self, activity_id, **ignored):
        return self._call("download_activity", int(activity_id))

    def close(self):
        self.client.close()
        if self.auth:
            self.auth.close()


def update(download_limit=20):
    """Usa pipeline, lock, correzioni e parser già esistenti; report senza segreti."""
    import json
    from dataclasses import asdict
    from datetime import datetime
    from .. import database, rebuild, corrections
    from ..metrics import daily_status
    from . import sync, fit_download, swim_details, track

    with rebuild.single_writer("personal-api-sync"):
        client = PersonalGarmin()
        try:
            with database.connect() as connection:
                report = sync.pull(connection, client=client)
                downloads = (fit_download.pull(connection, client, limit=download_limit)
                             if report.outcome != sync.FAILED else fit_download.DownloadReport(0,0,0,0))
                details = swim_details.load_downloaded(connection)
                tracks = track.load_downloaded(connection)
                corrections.apply(connection)
                daily_status.build(connection)
            outcome = report.outcome
            if outcome == sync.OK and (downloads.failed or details["errors"] or tracks["errors"]):
                outcome = sync.PARTIAL
            result = {"at": datetime.now().isoformat(), "provider": "Garmin Personal API",
                      "sync": asdict(report), "outcome": outcome,
                      "files": asdict(downloads), "details": details,"tracks":tracks}
            (paths.DATA / "personal-sync-status.json").write_text(
                json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            client.close()


def normalize_summary(row):
    """Schema v2 ufficiale → contratto storico. Unità millisecondi esplicite."""
    def value(section, key):
        return (row.get(section) or {}).get(key)
    rest = value("stress", "restDurationInMillis")
    return {
        "restingHeartRate": value("heartRate", "restingValue"),
        "minHeartRate": value("heartRate", "minValue"),
        "maxHeartRate": value("heartRate", "maxValue"),
        "totalSteps": ((row.get("movement") or {}).get("steps") or {}).get("value"),
        "totalDistanceMeters": ((row.get("movement") or {}).get("steps") or {}).get("distanceInMeters"),
        "activeKilocalories": value("calories", "burnedActive"),
        "totalKilocalories": value("calories", "burnedTotal"),
        "averageStressLevel": value("stress", "avgLevel"),
        "maxStressLevel": value("stress", "maxLevel"),
        "restStressDuration": rest / 1000 if rest is not None else None,
        "bodyBatteryLowestValue": value("bodyBattery", "minValue"),
        "bodyBatteryHighestValue": value("bodyBattery", "maxValue"),
        "avgWakingRespirationValue": value("respiration", "avgValue"),
        "averageSpo2": value("pulseOx", "avgValue"),
        "lowestSpo2": value("pulseOx", "minValue"),
        "moderateIntensityMinutes": value("intensityMinutes", "moderate"),
        "vigorousIntensityMinutes": value("intensityMinutes", "vigorous"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(update(), default=str, ensure_ascii=False))
