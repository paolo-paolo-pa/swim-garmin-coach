"""La copertura dichiarata deve dire la verità.

Distinguere "oggi non c'è il dato" da "il dato non esiste in questo periodo" è
la differenza fra un coach che tace un limite e uno che ne inventa uno.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status
from garmin_coach.mcp import queries


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_swim(con, activity_id, day, load=None, hr=None):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, environment, distance_m, duration_s, avg_hr_bpm, "
        "garmin_training_load, pool_length_m, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', 3000, 3600, ?, ?, 25, 'sha', ?)",
        [activity_id, datetime.combine(day, datetime.min.time()), day, hr, load,
         datetime(2026, 1, 1)])


def test_rest_day_does_not_hide_available_load_metrics(connection):
    # 28 giorni di allenamento con carico, poi un giorno di riposo.
    # Il giorno di riposo non ha carico, ma le metriche di carico restano valide.
    start = date(2026, 1, 1)
    for offset in range(28):
        add_swim(connection, offset + 1, start + timedelta(days=offset),
                 load=90, hr=140)
    rest_day = start + timedelta(days=28)
    connection.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, source_object_id, imported_at) "
        "VALUES (?, 52, 'sha', ?)", [rest_day, datetime(2026, 1, 1)])
    daily_status.build(connection)

    result = queries.briefing(connection, rest_day)
    coverage = result["coverage"]

    assert coverage["load_measured_today"] is False, "quel giorno non c'è stata attività"
    assert coverage["load_metrics_usable"] is True, "ma il carico dei 7 giorni esiste"
    assert coverage["acwr_usable"] is True


def test_period_without_load_declares_metrics_unusable(connection):
    # Come gli anni 2017-2020: nessun carico registrato da Garmin.
    start = date(2018, 3, 1)
    for offset in range(0, 28, 2):
        add_swim(connection, offset + 1, start + timedelta(days=offset),
                 load=None, hr=None)
    daily_status.build(connection)

    result = queries.briefing(connection, start + timedelta(days=26))
    coverage = result["coverage"]

    assert coverage["load_metrics_usable"] is False
    assert coverage["acwr_usable"] is False
    assert coverage["intensity_measured_today"] is False
