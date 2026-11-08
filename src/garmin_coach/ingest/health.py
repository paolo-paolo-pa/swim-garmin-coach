"""Import di salute, sonno, HRV, carico e peso dai JSON originali dell'export.

Tutte le sorgenti stanno in ``garmin-export/``. Il vecchio database non viene
letto: serve solo a confrontare i conteggi finali (criterio C6d).

A differenza dei riepiloghi delle attività, questi file usano già unità SI
(secondi, metri, kcal, bpm): nessun fattore di scala.

| Tabella                  | Sorgente                              | Copertura |
|--------------------------|---------------------------------------|-----------|
| ``daily_health``         | ``UDSFile_*.json``                    | dal 2017  |
| ``sleep``                | ``*_sleepData.json``                  | dal 2017  |
| ``health_status``        | ``*_healthStatusData.json``           | dal 2025-09 |
| ``garmin_training_load`` | ``MetricsAcuteTrainingLoad_*.json``   | dal 2022-08 |
| ``garmin_training_status``| ``TrainingHistory_*.json``           | dal 2021-07 |
| ``garmin_readiness``     | ``TrainingReadinessDTO_*.json``       | dal 2024-06 |
| ``body_metrics``         | ``00000000_userBioMetrics.json``      | dal 2017  |
| ``hr_zones``             | ``00000000_heartRateZones.json``      | corrente  |
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable

import duckdb

from .. import timestamps
from .source_file import SourceFile, discover, replace_export_rows

# La sottocartella dell'export per ciascuna categoria.
AGGREGATOR = "DI-Connect-Aggregator"
WELLNESS = "DI-Connect-Wellness"
METRICS = "DI-Connect-Metrics"


def _number(value: object) -> float | None:
    """Numero o niente. Lo zero è conservato: qui, a differenza dei riepiloghi
    delle attività, zero passi o zero calorie sono valori legittimi."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    result = _number(value)
    return None if result is None else int(result)


def _stress_total(record: dict) -> dict:
    """Il blocco stress della giornata intera, se presente."""
    block = record.get("allDayStress") or {}
    for aggregate in block.get("aggregatorList") or []:
        if aggregate.get("type") == "TOTAL":
            return aggregate
    return {}


def _body_battery(record: dict) -> tuple[float | None, float | None]:
    """(minimo, massimo) della batteria corporea nella giornata."""
    block = record.get("bodyBattery") or {}
    values: dict[str, float | None] = {}
    for stat in block.get("bodyBatteryStatList") or []:
        values[stat.get("bodyBatteryStatType")] = _number(stat.get("statsValue"))
    return values.get("LOWEST"), values.get("HIGHEST")


# ─────────────────────────────────────────────────────────────────────────────
# Un caricatore per sorgente. Ognuno restituisce {chiave_naturale: riga}.
# ─────────────────────────────────────────────────────────────────────────────

def _daily_health_rows(record: dict) -> tuple | None:
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    stress = _stress_total(record)
    battery_low, battery_high = _body_battery(record)
    respiration = record.get("respiration") or {}
    return (
        day,
        _number(record.get("restingHeartRate")),
        _number(record.get("minHeartRate")),
        _number(record.get("maxHeartRate")),
        _integer(record.get("totalSteps")),
        _number(record.get("totalDistanceMeters")),
        _number(record.get("activeKilocalories")),
        _number(record.get("totalKilocalories")),
        _number(record.get("activeSeconds")),
        _number(record.get("highlyActiveSeconds")),
        _number(record.get("moderateIntensityMinutes")),
        _number(record.get("vigorousIntensityMinutes")),
        _number(stress.get("averageStressLevel")),
        _number(stress.get("maxStressLevel")),
        _number(stress.get("restDuration")),
        battery_low,
        battery_high,
        _number(respiration.get("avgWakingRespirationValue")),
        _number(record.get("averageSpo2Value")),
        _number(record.get("lowestSpo2Value")),
    )


def _sleep_rows(record: dict) -> tuple | None:
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    scores = record.get("sleepScores") or {}
    deep = _number(record.get("deepSleepSeconds"))
    light = _number(record.get("lightSleepSeconds"))
    rem = _number(record.get("remSleepSeconds"))
    stages = [value for value in (deep, light, rem) if value is not None]
    total = sum(stages) if stages else None

    start = timestamps.to_utc(record.get("sleepStartTimestampGMT"))
    end = timestamps.to_utc(record.get("sleepEndTimestampGMT"))
    return (
        day,
        start.replace(tzinfo=None) if start else None,
        end.replace(tzinfo=None) if end else None,
        total, deep, light, rem,
        _number(record.get("awakeSleepSeconds")),
        _number(record.get("unmeasurableSeconds")),
        _number(scores.get("overallScore") if scores.get("overallScore") is not None
                else (scores.get("overall") or {}).get("value")),
        _number(record.get("averageRespiration")),
        _number(record.get("avgSleepStress")),
        _integer(record.get("restlessMomentCount")),
        _integer(record.get("awakeCount")),
    )


def _health_status_rows(record: dict) -> tuple | None:
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    metrics = {m.get("type"): m for m in record.get("metrics") or []}
    hrv = metrics.get("HRV", {})
    heart = metrics.get("HR", {})
    spo2 = metrics.get("SPO2", {})
    respiration = metrics.get("RESPIRATION", {})
    return (
        day,
        _number(hrv.get("value")),
        _number(hrv.get("baselineLowerLimit")),
        _number(hrv.get("baselineUpperLimit")),
        hrv.get("status"),
        _number(heart.get("value")),
        _number(heart.get("baselineLowerLimit")),
        _number(heart.get("baselineUpperLimit")),
        heart.get("status"),
        _number(spo2.get("value")),
        _number(respiration.get("value")),
    )


def _training_load_rows(record: dict) -> tuple | None:
    # calendarDate qui è un epoch in millisecondi, non una data ISO.
    # È l'errore che ha lasciato 15 file non importati nel progetto precedente.
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    return (
        day,
        _number(record.get("dailyTrainingLoadAcute")),
        _number(record.get("dailyTrainingLoadChronic")),
        _number(record.get("dailyAcuteChronicWorkloadRatio")),
        _number(record.get("acwrPercent")),
        record.get("acwrStatus"),
        _integer(record.get("deviceId")),
    )


def _training_status_rows(record: dict) -> tuple | None:
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    return (
        day,
        record.get("trainingStatus"),
        record.get("fitnessLevelTrend"),
        _integer(record.get("deviceId")),
    )


def _readiness_rows(record: dict) -> tuple | None:
    day = timestamps.to_date(record.get("calendarDate"))
    if day is None:
        return None
    return (
        day,
        _number(record.get("score")),
        record.get("level"),
        _number(record.get("recoveryTime")),
        _number(record.get("hrvWeeklyAverage")),
        _number(record.get("sleepScoreFactorPercent")),
        _number(record.get("sleepHistoryFactorPercent")),
        _number(record.get("stressHistoryFactorPercent")),
        _number(record.get("hrvFactorPercent")),
        _number(record.get("acwrFactorPercent")),
        _number(record.get("recoveryTimeFactorPercent")),
    )


def _body_metrics_rows(record: dict) -> tuple | None:
    meta = record.get("metaData") or {}
    day = timestamps.to_date(meta.get("calendarDate"))
    if day is None:
        return None
    weight_block = record.get("weight") or {}
    grams = _number(weight_block.get("weight"))
    return (
        day,
        grams / 1000 if grams else None,   # Garmin registra il peso in grammi
        _number(record.get("height")),
    )


def _hr_zone_rows(record: dict) -> tuple | None:
    sport = record.get("sport")
    if not sport:
        return None
    return (
        sport,
        record.get("trainingMethod"),
        _number(record.get("maxHeartRateUsed")),
        _number(record.get("restingHeartRateUsed")),
        _number(record.get("zone1Floor")),
        _number(record.get("zone2Floor")),
        _number(record.get("zone3Floor")),
        _number(record.get("zone4Floor")),
        _number(record.get("zone5Floor")),
    )


# ─────────────────────────────────────────────────────────────────────────────

_SOURCES: list[dict] = [
    {"table": "daily_health", "folder": AGGREGATOR, "pattern": "UDSFile_*.json",
     "builder": _daily_health_rows, "columns": [
         "health_date", "resting_hr_bpm", "min_hr_bpm", "max_hr_bpm", "steps",
         "distance_m", "active_kcal", "total_kcal", "active_s", "highly_active_s",
         "moderate_minutes", "vigorous_minutes", "stress_avg", "stress_max",
         "stress_rest_s", "body_battery_min", "body_battery_max",
         "respiration_avg", "spo2_avg", "spo2_lowest"]},
    {"table": "sleep", "folder": WELLNESS, "pattern": "*_sleepData.json",
     "builder": _sleep_rows, "columns": [
         "sleep_date", "sleep_start_utc", "sleep_end_utc", "total_sleep_s",
         "deep_s", "light_s", "rem_s", "awake_s", "unmeasurable_s",
         "sleep_score", "avg_respiration", "avg_sleep_stress",
         "restless_count", "awake_count"]},
    {"table": "health_status", "folder": WELLNESS, "pattern": "*_healthStatusData.json",
     "builder": _health_status_rows, "columns": [
         "status_date", "hrv_ms", "hrv_baseline_low", "hrv_baseline_high",
         "hrv_status", "hr_bpm", "hr_baseline_low", "hr_baseline_high",
         "hr_status", "spo2_pct", "respiration"]},
    {"table": "garmin_training_load", "folder": METRICS,
     "pattern": "MetricsAcuteTrainingLoad_*.json", "builder": _training_load_rows,
     "columns": ["load_date", "acute_load", "chronic_load", "acwr",
                 "acwr_percent", "acwr_status", "device_id"]},
    {"table": "garmin_training_status", "folder": METRICS,
     "pattern": "TrainingHistory_*.json", "builder": _training_status_rows,
     "columns": ["status_date", "training_status", "fitness_trend", "device_id"]},
    {"table": "garmin_readiness", "folder": METRICS,
     "pattern": "TrainingReadinessDTO_*.json", "builder": _readiness_rows,
     "columns": ["readiness_date", "score", "level", "recovery_time_h",
                 "hrv_weekly_avg", "sleep_score_pct", "sleep_history_pct",
                 "stress_history_pct", "hrv_factor_pct", "acwr_factor_pct",
                 "recovery_factor_pct"]},
    {"table": "body_metrics", "folder": WELLNESS, "pattern": "*_userBioMetrics.json",
     "builder": _body_metrics_rows,
     "columns": ["measure_date", "weight_kg", "height_cm"]},
    {"table": "hr_zones", "folder": WELLNESS, "pattern": "*_heartRateZones.json",
     "builder": _hr_zone_rows,
     "columns": ["sport", "method", "max_hr_used", "resting_hr_used",
                 "zone1_floor", "zone2_floor", "zone3_floor", "zone4_floor",
                 "zone5_floor"]},
]


def _records(source: SourceFile) -> Iterable[dict]:
    """I file di salute sono liste di record. Alcuni sono racchiusi in un
    contenitore con una sola chiave: si scende di un livello."""
    payload = source.load_json()
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                payload = value
                break
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, dict):
            yield item


def _load_one(connection: duckdb.DuckDBPyConnection, spec: dict,
              imported_at: datetime) -> dict:
    builder: Callable[[dict], tuple | None] = spec["builder"]
    by_key: dict[object, tuple] = {}
    skipped: list[str] = []
    per_file: list[tuple[str, str, int]] = []

    for source in discover(spec["folder"], spec["pattern"]):
        sha = source.sha256
        written = 0
        for record in _records(source):
            try:
                row = builder(record)
            except (timestamps.TimestampOutOfRange, ValueError, TypeError) as error:
                skipped.append(f"{spec['table']}: {error}")
                continue
            if row is None:
                continue
            # Gli intervalli dei file Garmin si toccano agli estremi: l'ultimo
            # file letto è il più recente e vince sul giorno condiviso.
            by_key[row[0]] = row + (sha, imported_at)
            written += 1
        per_file.append((source.relative_path, sha, written))

    columns = spec["columns"] + ["source_object_id", "imported_at"]
    replace_export_rows(connection, spec["table"], columns,
                        list(by_key.values()))

    for relative_path, sha, written in per_file:
        connection.execute(
            "INSERT OR REPLACE INTO import_log "
            "(source_path, source_object_id, target_table, rows_written, imported_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [relative_path, sha, spec["table"], written, imported_at],
        )

    return {"table": spec["table"], "files": len(per_file),
            "rows": len(by_key), "skipped": skipped}


def load(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    """Importa tutte le sorgenti di salute. Un riepilogo per tabella."""
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return [_load_one(connection, spec, imported_at) for spec in _SOURCES]
