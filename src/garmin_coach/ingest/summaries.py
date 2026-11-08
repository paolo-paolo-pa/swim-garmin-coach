"""Import delle attività da ``summarizedActivities.json``.

È la spina dorsale del progetto: 1.471 attività dal 2017 al 2026, di cui 1.306
di nuoto, tutte con volume e metriche tecniche. Nessun file FIT viene aperto.

Strategia di idempotenza: si legge l'intera categoria, si deduplica per
``activityId`` e si riscrivono **le righe che l'export possiede**. Sono ~15 MB
di JSON: la semplicità di una ricostruzione completa vale più di un import
incrementale da mantenere.

Riscrivere l'intera tabella era la stessa cosa finché l'export era l'unica
sorgente. Da quando esiste il sync non lo è più: l'export è fermo al 4 luglio e
le settimane successive esistono soltanto perché il sync le ha scritte. Il
perché e il come stanno in ``source_file.replace_export_rows``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from .. import timestamps
from . import garmin_units as units
from .source_file import SourceFile, discover, replace_export_rows

SWIM_SPORTS = {"lap_swimming", "open_water_swimming"}
ENVIRONMENTS = {"lap_swimming": "pool", "open_water_swimming": "open_water"}

_COLUMNS = [
    "activity_id", "start_time_utc", "start_time_local", "activity_date",
    "timezone_id", "sport", "is_swim", "environment", "name",
    "duration_s", "elapsed_s", "moving_s", "distance_m",
    "avg_speed_ms", "max_speed_ms", "calories_kcal", "bmr_calories_kcal",
    "avg_hr_bpm", "max_hr_bpm", "min_hr_bpm",
    "hr_zone_0_s", "hr_zone_1_s", "hr_zone_2_s",
    "hr_zone_3_s", "hr_zone_4_s", "hr_zone_5_s",
    "garmin_training_load", "garmin_aerobic_te", "garmin_anaerobic_te",
    "garmin_te_label", "moderate_minutes", "vigorous_minutes",
    "pool_length_m", "avg_swolf", "avg_stroke_distance_m",
    "avg_swim_cadence_spm", "max_swim_cadence_spm", "total_strokes",
    "avg_strokes_per_length", "active_lengths", "lap_count",
    "rpe", "feel", "device_id", "is_personal_record", "is_favorite",
    "max_temperature_c", "min_temperature_c", "source_object_id", "imported_at",
]


def _human_speed(value: float | None, is_swim: bool) -> float | None:
    """La velocità di picco, se è la velocità di un nuotatore.

    Nell'archivio compaiono 100,33 m/s sul 6 km di place03 e 45,36 sul 30/07/2023
    — 361 e 163 km/h. Sono picchi del GPS, e quarantuno attività ne portano uno.

    Non entrano. È la stessa scelta che il progetto fa già altrove: gli zeri di
    Garmin non diventano zeri (``ZERO_MEANS_MISSING``) e il sync si ferma davanti
    a un valore che nessuna scala nota spiega. Un artefatto scritto in una
    colonna che si chiama «velocità massima» è un dato falso travestito da
    misura, e la prima analisi che lo userà lo userà rotto.

    Il picco non tocca l'attività: place03 resta 6.000 m a 1:26,7, che è una
    prestazione vera. Sparisce il campo, non la seduta.
    """
    from ..verification import MAX_HUMAN_SWIM_SPEED_MS

    if value is None or not is_swim:
        return value
    return None if value > MAX_HUMAN_SWIM_SPEED_MS else value


def _row(raw: dict, sha: str, imported_at: datetime) -> tuple | None:
    start_utc = timestamps.to_utc(raw.get("beginTimestamp"))
    if start_utc is None:
        return None

    start_local = timestamps.to_utc(raw.get("startTimeLocal"))
    # Il giorno di calendario è quello dell'atleta, non UTC: una seduta serale
    # in Italia non deve finire nel giorno successivo o precedente.
    activity_date = (start_local or start_utc).date()

    sport = raw.get("activityType") or "unknown"
    is_swim = sport in SWIM_SPORTS

    return (
        int(raw["activityId"]),
        start_utc.replace(tzinfo=None),
        start_local.replace(tzinfo=None) if start_local else None,
        activity_date,
        raw.get("timeZoneId"),
        sport,
        is_swim,
        ENVIRONMENTS.get(sport),
        raw.get("name"),
        units.seconds(raw, "duration"),
        units.seconds(raw, "elapsedDuration"),
        units.seconds(raw, "movingDuration"),
        units.meters(raw, "distance"),
        units.meters_per_second(raw, "avgSpeed"),
        _human_speed(units.meters_per_second(raw, "maxSpeed"), is_swim),
        units.kilocalories(raw, "calories"),
        units.kilocalories(raw, "bmrCalories"),
        units.value(raw, "avgHr"),
        units.value(raw, "maxHr"),
        units.value(raw, "minHr"),
        # Garmin espone i tempi in zona in **millisecondi**, come tutte le altre
        # durate. Qui erano letti con `value` invece che con `seconds`, e
        # finivano in colonne che si chiamano `_s` valendo mille volte tanto:
        # la somma delle sei zone dava 999 volte la durata della seduta.
        # Nessuno se n'era accorto perché nessuna analisi le leggeva ancora.
        units.seconds(raw, "hrTimeInZone_0"),
        units.seconds(raw, "hrTimeInZone_1"),
        units.seconds(raw, "hrTimeInZone_2"),
        units.seconds(raw, "hrTimeInZone_3"),
        units.seconds(raw, "hrTimeInZone_4"),
        units.seconds(raw, "hrTimeInZone_5"),
        units.value(raw, "activityTrainingLoad"),
        units.value(raw, "aerobicTrainingEffect"),
        units.value(raw, "anaerobicTrainingEffect"),
        raw.get("trainingEffectLabel"),
        units.value(raw, "moderateIntensityMinutes"),
        units.value(raw, "vigorousIntensityMinutes"),
        units.meters(raw, "poolLength"),
        units.value(raw, "avgSwolf"),
        units.meters(raw, "avgStrokeDistance"),
        units.value(raw, "avgSwimCadence"),
        units.value(raw, "maxSwimCadence"),
        units.value(raw, "strokes"),
        units.value(raw, "avgStrokes"),
        int(v) if (v := units.value(raw, "activeLengths")) else None,
        int(v) if (v := units.value(raw, "lapCount")) else None,
        units.rpe(raw),
        units.value(raw, "workoutFeel"),
        int(raw["deviceId"]) if raw.get("deviceId") else None,
        bool(raw.get("pr")) if raw.get("pr") is not None else None,
        bool(raw.get("favorite")) if raw.get("favorite") is not None else None,
        units.value(raw, "maxTemperature"),
        units.value(raw, "minTemperature"),
        sha,
        imported_at,
    )


def source_files() -> list[SourceFile]:
    return discover("DI-Connect-Fitness", "*summarizedActivities.json")


def load(connection: duckdb.DuckDBPyConnection) -> dict:
    """Importa tutte le attività. Restituisce un riepilogo per il registro."""
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
    by_activity: dict[int, tuple] = {}
    skipped: list[str] = []
    per_file: list[tuple[str, str, int]] = []

    for source in source_files():
        sha = source.sha256
        payload = source.load_json()
        # Il file è una lista con un solo oggetto contenitore.
        activities = payload[0]["summarizedActivitiesExport"]
        written = 0
        for raw in activities:
            try:
                row = _row(raw, sha, imported_at)
            except (timestamps.TimestampOutOfRange, ValueError, KeyError) as error:
                skipped.append(f"{raw.get('activityId')}: {error}")
                continue
            if row is None:
                skipped.append(f"{raw.get('activityId')}: timestamp di inizio assente")
                continue
            by_activity[row[0]] = row
            written += 1
        per_file.append((source.relative_path, sha, written))

    replace_export_rows(connection, "activities", _COLUMNS,
                        list(by_activity.values()))
    orfani = _forget_orphaned_detail(connection)

    for relative_path, sha, written in per_file:
        connection.execute(
            "INSERT OR REPLACE INTO import_log "
            "(source_path, source_object_id, target_table, rows_written, imported_at) "
            "VALUES (?, ?, 'activities', ?, ?)",
            [relative_path, sha, written, imported_at],
        )

    return {
        "table": "activities",
        "files": len(per_file),
        "rows": len(by_activity),
        "skipped": skipped,
        "orphaned_detail_removed": orfani,
    }


# Le tabelle di dettaglio che descrivono una singola attività. Se l'attività
# sparisce, le loro righe non descrivono più niente.
_DETAIL_TABLES = ("activity_laps", "pool_lengths", "activity_source_matches")


def _forget_orphaned_detail(connection: duckdb.DuckDBPyConnection) -> int:
    """Toglie il dettaglio rimasto senza la seduta che descriveva.

    Un lap orfano è peggio di un lap mancante: ogni conteggio lo trova e nessuna
    join lo mostra. Lo schema non ha chiavi esterne, quindi l'invariante la
    tiene chi la può rompere — cioè questa funzione, subito dopo aver cancellato
    delle attività.
    """
    from ..database import table_exists

    rimossi = 0
    for tabella in _DETAIL_TABLES:
        if not table_exists(connection, tabella):
            continue
        rimossi += connection.execute(f"""
            DELETE FROM {tabella}
            WHERE NOT EXISTS (SELECT 1 FROM activities a
                              WHERE a.activity_id = {tabella}.activity_id)
        """).fetchone()[0]
    return rimossi
