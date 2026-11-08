"""I fattori di scala dei riepiloghi Garmin.

I campi di ``summarizedActivities.json`` **non** sono in unità SI. Le scale sono
state calibrate confrontando 422 attività con i valori letti dai file FIT
(mediana del rapporto, dispersione nulla su tutte e 422):

| Campo grezzo                            | Rapporto misurato | Unità reale |
|-----------------------------------------|-------------------|-------------|
| ``distance``                            | 100,0000          | centimetri  |
| ``duration`` / ``elapsedDuration`` / …  | 1000,0000         | millisecondi|
| ``calories`` / ``bmrCalories``          | 4,1900            | kilojoule   |
| ``avgHr`` / ``maxHr`` / ``minHr``       | 1,0000            | bpm, già SI |

``poolLength`` e ``avgStrokeDistance`` non erano confrontabili con i FIT, ma la
verifica interna ``distance == activeLengths × poolLength`` torna su 1203/1203
sedute di piscina: condividono la scala di ``distance``, quindi centimetri.
I valori distinti sono 2500 e 5000, cioè vasche da 25 m e 50 m.

``avgSpeed`` è stato verificato contro ``distance / movingDuration``: il valore
grezzo va moltiplicato per 10 per ottenere m/s.
"""

from __future__ import annotations

CENTIMETERS_PER_METER = 100.0
MILLISECONDS_PER_SECOND = 1000.0
KILOJOULES_PER_KILOCALORIE = 4.19
RAW_SPEED_TO_METERS_PER_SECOND = 10.0

# Garmin registra la fatica percepita come CR10 moltiplicata per dieci: i valori
# osservati sono 10, 30, 40, 50, 60, 70, 80, 90, 100 — nessun valore intermedio.
# Risponde alla domanda aperta sulla scala RPE dell'atleta.
RPE_SCALE = 10.0

# Campi in cui lo zero non è un valore possibile ma un "non misurato" scritto da
# Garmin. Trattarlo come zero falserebbe ogni media (Regola Aurea n.5).
# Nota: ``avgStrokeDistance`` è zero su 735 sedute di nuoto su 1.306 — la
# copertura reale è del 43%, non del 99% suggerito dal semplice conteggio dei
# non-nulli.
ZERO_MEANS_MISSING = frozenset({
    "distance", "duration", "elapsedDuration", "movingDuration",
    "avgSpeed", "maxSpeed", "avgHr", "maxHr", "minHr",
    "avgSwolf", "avgStrokeDistance", "avgSwimCadence", "maxSwimCadence",
    "strokes", "avgStrokes", "activeLengths", "lapCount",
    "poolLength", "calories", "activityTrainingLoad",
})


def value(raw: dict, field: str) -> float | None:
    """Legge un campo trattando lo zero come mancante dove lo zero è impossibile."""
    result = raw.get(field)
    if result is None:
        return None
    if result == 0 and field in ZERO_MEANS_MISSING:
        return None
    return float(result)


def _scaled(raw: dict, field: str, divisor: float) -> float | None:
    result = value(raw, field)
    return None if result is None else result / divisor


def meters(raw: dict, field: str) -> float | None:
    return _scaled(raw, field, CENTIMETERS_PER_METER)


def seconds(raw: dict, field: str) -> float | None:
    return _scaled(raw, field, MILLISECONDS_PER_SECOND)


def kilocalories(raw: dict, field: str) -> float | None:
    return _scaled(raw, field, KILOJOULES_PER_KILOCALORIE)


def meters_per_second(raw: dict, field: str) -> float | None:
    result = value(raw, field)
    return None if result is None else result * RAW_SPEED_TO_METERS_PER_SECOND


def rpe(raw: dict, field: str = "workoutRpe") -> float | None:
    """Fatica percepita sulla scala CR10 (1-10)."""
    return _scaled(raw, field, RPE_SCALE)
