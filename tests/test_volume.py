"""Il volume di un periodo e di una settimana, su dati costruiti a mano.

``analysis/volume.py`` è l'unica definizione di «quanto ha nuotato»: la usano il
confronto, la review settimanale, la preparazione gara e l'MCP. Qui si verifica
che conti le stesse nuotate che conta ``daily_status``, gare in mare comprese.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import volume
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_swim(con, day: str, distance_m: float, duration_s: float = 3600,
             environment: str = "pool", pool_length: float | None = 25.0,
             hr: float | None = None, swolf: float | None = None):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, environment, distance_m, duration_s, pool_length_m, avg_hr_bpm, "
        "avg_swolf, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, ?, ?, ?, ?, ?, ?, 'sha', ?)",
        [abs(hash(day + str(distance_m))) % 10**9,
         datetime.fromisoformat(day + "T08:00:00"), date.fromisoformat(day),
         environment, distance_m, duration_s, pool_length, hr, swolf,
         datetime(2026, 1, 1)],
    )


def add_open_water_race(con, day: str, distance_m: float | None,
                        time_s: float = 3600.0, meet: str = "Gara in mare"):
    con.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'fondo', ?, FALSE, ?, 'valid', 'acque libere', 'sha', ?)",
        [f"{day}-{meet}-{distance_m}", date.fromisoformat(day), meet,
         distance_m, time_s, datetime(2026, 1, 1)],
    )


# ── La vista che decide cosa conta ─────────────────────────────────────────

def test_the_view_holds_both_kinds_and_says_which_is_which(connection):
    add_swim(connection, "2026-05-01", 2000)
    add_open_water_race(connection, "2026-05-10", 3000)

    righe = connection.execute(
        "SELECT origin, distance_m, environment FROM counted_swims "
        "ORDER BY swim_date").fetchall()

    assert righe == [("garmin", 2000.0, "pool"),
                     ("race", 3000.0, "open_water")]


def test_the_view_speaks_english_about_the_sea(connection):
    """`races` dice «acque libere», le attività dicono «open_water». Nel codice
    si parla inglese: la vista normalizza una volta invece di lasciare a ogni
    filtro due nomi per la stessa cosa."""
    add_open_water_race(connection, "2026-05-10", 3000)

    assert connection.execute(
        "SELECT environment FROM counted_swims").fetchone()[0] == "open_water"


def test_a_race_declared_to_be_that_swim_stays_out_of_the_view(connection):
    add_swim(connection, "2026-05-10", 4068, environment="open_water",
             pool_length=None)
    add_open_water_race(connection, "2026-05-10", 2500)
    connection.execute(
        "INSERT INTO race_quality (race_id, verdict, activity_id, reason, "
        " decided_by, applied_at) "
        "VALUES ('2026-05-10-Gara in mare-2500', 'linked', 1, 'stessa "
        "nuotata', 'athlete', ?)", [datetime(2026, 8, 25)])

    assert connection.execute(
        "SELECT count(*) FROM counted_swims WHERE origin = 'race'").fetchone()[0] == 0


def test_sharing_a_date_does_not_make_two_swims_one(connection):
    """place04 la mattina, place03 alle [orario]: la data in comune non basta."""
    add_swim(connection, "2026-05-10", 4068, environment="open_water",
             pool_length=None)
    add_open_water_race(connection, "2026-05-10", 1900)

    assert connection.execute(
        "SELECT count(*) FROM counted_swims").fetchone()[0] == 2


def test_the_athlete_distance_wins_over_the_event_name(connection):
    """2.500 m in 25:35 darebbe 1:01,4 per 100, che nessuno nuota: la distanza
    viene dal nome dell'evento, non da una misura del percorso."""
    add_open_water_race(connection, "2026-05-10", 2500)
    connection.execute(
        "INSERT INTO race_quality (race_id, verdict, counted_distance_m, "
        " reason, decided_by, applied_at) "
        "VALUES ('2026-05-10-Gara in mare-2500', 'separate', 1900, 'percorso "
        "ridotto', 'athlete', ?)", [datetime(2026, 8, 25)])

    assert connection.execute(
        "SELECT distance_m FROM counted_swims WHERE origin = 'race'"
    ).fetchone()[0] == 1900


def test_a_distance_known_to_be_wrong_becomes_missing_not_invented(connection):
    """«So che quel numero è sbagliato e non so quale sia» non è un numero: il
    valore resta mancante (R5)."""
    add_open_water_race(connection, "2026-05-10", 1500)
    connection.execute(
        "INSERT INTO race_quality (race_id, verdict, distance_is_unknown, "
        " reason, decided_by, applied_at) "
        "VALUES ('2026-05-10-Gara in mare-1500', 'separate', TRUE, 'il nome "
        "dell''evento non descrive il percorso', 'athlete', ?)",
        [datetime(2026, 8, 25)])

    assert connection.execute(
        "SELECT distance_m FROM counted_swims WHERE origin = 'race'"
    ).fetchone()[0] is None


# ── Il volume di un periodo ────────────────────────────────────────────────

def test_a_race_without_a_watch_is_in_the_period_volume(connection):
    add_swim(connection, "2026-05-01", 2000)
    add_open_water_race(connection, "2026-05-10", 3000, time_s=2700)

    periodo = volume.of_period(connection, date(2026, 5, 1), date(2026, 5, 31))

    assert periodo.sessions == 2
    assert periodo.distance_m == 5000
    assert periodo.duration_s == 6300
    assert periodo.declared_sessions == 1


def test_declared_metres_are_declared_not_hidden(connection):
    """I metri di una gara li dichiara l'evento, non li misura l'orologio: chi
    legge il volume deve poterlo sapere senza chiederlo altrove."""
    add_swim(connection, "2026-05-01", 2000)

    periodo = volume.of_period(connection, date(2026, 5, 1), date(2026, 5, 31))

    assert periodo.declared_sessions == 0


def test_a_race_moves_no_technique_average(connection):
    """Una gara non ha SWOLF, bracciate, battiti né un dispositivo: entra nei
    metri e nei minuti, e lascia stare le medie tecniche."""
    add_swim(connection, "2026-05-01", 2000, swolf=30.0, hr=140.0)
    add_open_water_race(connection, "2026-05-10", 3000)

    periodo = volume.of_period(connection, date(2026, 5, 1), date(2026, 5, 31))

    assert periodo.swolf_avg == 30.0
    assert periodo.swolf_n == 1
    assert periodo.hr_avg == 140.0
    assert periodo.hr_n == 1
    assert periodo.devices == ()


def test_a_pool_filter_leaves_the_sea_out(connection):
    add_swim(connection, "2026-05-01", 2000)
    add_open_water_race(connection, "2026-05-10", 3000)

    in_vasca = volume.of_period(connection, date(2026, 5, 1), date(2026, 5, 31),
                                pool_length_m=25.0)

    assert in_vasca.sessions == 1
    assert in_vasca.distance_m == 2000


def test_an_open_water_filter_finds_the_race(connection):
    add_swim(connection, "2026-05-01", 2000)
    add_open_water_race(connection, "2026-05-10", 3000)

    in_mare = volume.of_period(connection, date(2026, 5, 1), date(2026, 5, 31),
                               environment="open_water")

    assert in_mare.sessions == 1
    assert in_mare.distance_m == 3000


# ── Le settimane ───────────────────────────────────────────────────────────

def test_a_week_of_racing_is_not_an_empty_week(connection):
    """Era il difetto vero: nelle settimane in cui l'atleta ha gareggiato e
    basta, la review diceva zero."""
    add_open_water_race(connection, "2026-05-13", 3000, time_s=2700)

    settimane = volume.weeks_until(connection, date(2026, 5, 17), weeks=1)

    assert len(settimane) == 1
    assert settimane[0].sessions == 1
    assert settimane[0].distance_m == 3000
    assert settimane[0].declared_sessions == 1
    assert settimane[0].as_dict()["declared_sessions"] == 1
