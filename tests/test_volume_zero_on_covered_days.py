"""Una settimana senza nuotate è 0 km se l'orologio era in uso, un'interruzione se non c'è nessun dato."""
from datetime import date

import duckdb
import pytest

from garmin_coach.analysis import dashboard
from garmin_coach.database import SCHEMA
from garmin_coach.metrics.daily_status import build


@pytest.fixture
def connection():
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        yield c


def _swim(connection, identifier, day, metres):
    connection.execute(
        "INSERT INTO activities(activity_id,activity_date,start_time_utc,sport,is_swim,environment,distance_m,source_object_id,imported_at) "
        "VALUES (?,?,?,'lap_swimming',true,'pool',?,'fixture',current_timestamp)", [identifier, day, day, metres])


def _health(connection, day):
    connection.execute(
        "INSERT INTO daily_health(health_date,resting_hr_bpm,source_object_id,imported_at) VALUES (?,50,'fixture',current_timestamp)", [day])


def test_week_without_swims_is_zero_when_other_garmin_data_exist(connection):
    _swim(connection, 1, '2026-10-05', 2000)
    for d in ('2026-10-13', '2026-10-14', '2026-10-15'):
        _health(connection, d)
    _swim(connection, 2, '2026-10-21', 3000)
    build(connection)
    r = dashboard.overview(connection, 30, until=date(2026, 10, 25), resolution='week')
    weeks = {row['date']: row['km'] for row in r['volume_history']['rows']}
    assert weeks['2026-10-12'] == 0.0
    assert weeks['2026-10-05'] == 2.0 and weeks['2026-10-19'] == 3.0


def test_period_with_no_garmin_data_stays_a_gap(connection):
    _swim(connection, 1, '2026-08-03', 1000)
    _swim(connection, 2, '2026-10-05', 2000)
    build(connection)
    r = dashboard.overview(connection, 90, until=date(2026, 10, 11), resolution='week')
    weeks = {row['date']: row['km'] for row in r['volume_history']['rows']}
    assert weeks['2026-09-14'] is None
    assert weeks['2026-08-03'] == 1.0


def test_watch_models_come_from_the_id_table_and_unknown_ones_stay_apart(tmp_path, monkeypatch):
    from garmin_coach import athlete_files, paths
    (tmp_path / "orologi.md").write_text(
        "| identificativo | modello |\n|---|---|\n| 11 | Fenix 6X |\n| 12 | Fenix 6X |\n\n"
        "| dal | al | modello |\n|---|---|---|\n| 2026-01-01 | | Fenix 8 |\n", encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", tmp_path)
    labeler = athlete_files.WatchLabeler()
    assert labeler.label(date(2022, 5, 1), 11) == labeler.label(date(2023, 5, 1), 12) == "Fenix 6X"
    assert labeler.label(date(2026, 2, 1), 99) == "Fenix 8"
    a, b = labeler.label(date(2020, 1, 1), 31), labeler.label(date(2020, 1, 2), 32)
    assert a != b and a.startswith(athlete_files.UNKNOWN_WATCH) and "31" not in a
