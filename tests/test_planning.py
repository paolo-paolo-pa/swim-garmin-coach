"""La pianificazione verso una gara.

Il modulo non scrive allenamenti: prepara i fatti su cui il coach ragiona.
Questi test verificano che i fatti siano quelli giusti e che le lacune siano
dichiarate invece che colmate con stime.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.athlete_files import Race
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status
from garmin_coach.mcp import planning


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    # Dodici settimane di nuoto regolare, tre sedute a settimana.
    start = date(2026, 5, 1)
    activity_id = 1
    for week in range(12):
        for day_offset in (0, 2, 4):
            day = start + timedelta(weeks=week, days=day_offset)
            con.execute(
                "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
                "sport, is_swim, environment, distance_m, duration_s, avg_hr_bpm, "
                "garmin_training_load, pool_length_m, device_id, source_object_id, imported_at) "
                "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', 3000, 3600, 140, 90, "
                "25, 111, 'sha', ?)",
                [activity_id, datetime.combine(day, datetime.min.time()), day,
                 datetime(2026, 1, 1)])
            activity_id += 1
    # Una prova in acque libere sulla distanza di gara
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, environment, distance_m, duration_s, avg_hr_bpm, source_object_id, imported_at) "
        "VALUES (9001, ?, ?, 'open_water_swimming', TRUE, 'open_water', 5100, 5400, "
        "150, 'sha', ?)",
        [datetime(2026, 7, 5, 9), date(2026, 7, 5), datetime(2026, 1, 1)])
    daily_status.build(con)
    yield con
    con.close()


def make_race(days_from_today: int, distance: str = "5 km") -> Race:
    return Race(
        race_id="test-race", race_date=date.today() + timedelta(days=days_from_today),
        name="Traversata di prova", distance=distance, environment="acque libere",
        pool="—", priority="A", goal="sotto 1h20", notes="mare, muta ammessa")


def test_days_away_and_approach_window(connection):
    result = planning.readiness(connection, make_race(10))
    assert result["race"]["days_away"] == 10
    assert result["race"]["in_approach_window"] is True

    far = planning.readiness(connection, make_race(90))
    assert far["race"]["in_approach_window"] is False


def test_weekly_trend_covers_eight_weeks(connection):
    result = planning.readiness(connection, make_race(10),
                                today=date(2026, 7, 20))
    weeks = result["weekly_volume_trend"]
    assert weeks, "la tendenza settimanale non deve essere vuota"
    assert all("km" in week and "sessions" in week for week in weeks)
    # ogni settimana piena ha tre sedute da 3 km
    full_weeks = [w for w in weeks if w["sessions"] == 3]
    assert full_weeks and full_weeks[0]["km"] == pytest.approx(9.0)


def test_similar_efforts_use_the_race_distance(connection):
    result = planning.readiness(connection, make_race(10, distance="5 km"))
    efforts = result["similar_efforts"]
    assert efforts, "la prova da 5,1 km deve comparire fra gli sforzi simili"
    assert efforts[0]["distance_m"] == pytest.approx(5100)
    assert efforts[0]["pace_per_100m_s"] == pytest.approx(105.9, abs=0.5)


def test_distance_is_parsed_from_free_text():
    assert planning._target_distance(make_race(1, "5 km")) == 5000
    assert planning._target_distance(make_race(1, "1500 m")) == 1500
    assert planning._target_distance(make_race(1, "3,5 km")) == 3500
    # una distanza non riconoscibile resta ignota invece di essere indovinata
    assert planning._target_distance(make_race(1, "media distanza")) is None


def test_coverage_declares_how_old_the_data_is(connection):
    result = planning.readiness(connection, make_race(30), today=date(2026, 9, 1))
    coverage = result["coverage"]
    assert coverage["reference_day"] is not None
    assert coverage["days_behind_today"] > 0


def test_no_training_plan_is_invented(connection):
    """Il modulo prepara fatti. Se producesse una settimana di allenamenti,
    nasconderebbe in un algoritmo decisioni che vanno motivate."""
    result = planning.readiness(connection, make_race(14))
    assert "workouts" not in result
    assert "training_week" not in result
    assert "knowledge/" in result["note"]
