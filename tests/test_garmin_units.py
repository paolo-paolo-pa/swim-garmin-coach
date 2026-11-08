"""I fattori di scala dei riepiloghi, calibrati su 422 attività contro i FIT.

Una seduta reale del 2017: 5 vasche da 25 m, 125 m totali, 95,495 secondi.
"""

import pytest

from garmin_coach.ingest import garmin_units as units

REAL_SESSION = {
    "distance": 12500.0,          # centimetri
    "duration": 95495.00274658203,  # millisecondi
    "poolLength": 2500.0,         # centimetri
    "avgSpeed": 0.1340999960899353,
    "calories": 138.27066,        # kilojoule
    "avgStrokeDistance": 313.0000114440918,
    "avgSwolf": 27.0,
    "workoutRpe": 70,
    "avgHr": None,
}


def test_distance_is_centimeters():
    assert units.meters(REAL_SESSION, "distance") == pytest.approx(125.0)


def test_pool_length_25_meters():
    assert units.meters(REAL_SESSION, "poolLength") == pytest.approx(25.0)


def test_duration_is_milliseconds():
    assert units.seconds(REAL_SESSION, "duration") == pytest.approx(95.495, abs=1e-3)


def test_speed_matches_distance_over_duration():
    distance = units.meters(REAL_SESSION, "distance")
    duration = units.seconds(REAL_SESSION, "duration")
    declared = units.meters_per_second(REAL_SESSION, "avgSpeed")
    # avgSpeed è calcolata da Garmin sul tempo in movimento, quindi è appena
    # superiore al rapporto sul tempo totale, ma dello stesso ordine.
    assert declared == pytest.approx(1.341, abs=1e-3)
    assert distance / duration == pytest.approx(1.309, abs=1e-3)


def test_calories_are_kilojoules():
    assert units.kilocalories(REAL_SESSION, "calories") == pytest.approx(33.0, abs=0.1)


def test_rpe_is_cr10():
    # Garmin registra la CR10 moltiplicata per dieci: 70 significa 7/10
    assert units.rpe(REAL_SESSION) == pytest.approx(7.0)


def test_zero_means_missing_where_zero_is_impossible():
    # Garmin scrive 0 al posto del dato mancante: su avgStrokeDistance succede
    # in 735 sedute di nuoto su 1.306. Trattarlo come zero falserebbe le medie.
    assert units.value({"avgStrokeDistance": 0}, "avgStrokeDistance") is None
    assert units.meters({"distance": 0}, "distance") is None


def test_zero_is_kept_where_zero_is_legitimate():
    # Fuori dall'elenco dei campi "zero = mancante", lo zero resta un valore.
    assert units.value({"restingCalories": 0}, "restingCalories") == 0.0


def test_absent_field_returns_none():
    assert units.meters({}, "distance") is None
    assert units.rpe({}) is None
