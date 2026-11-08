"""Le regole di calcolo di ``daily_status``, su dati costruiti a mano.

Servono a dimostrare che le formule fanno quello che il catalogo dichiara,
indipendentemente dai dati reali dell'atleta. Un database in memoria, dieci
righe, nessuna sorpresa.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_swim(con, day: str, distance_m: float, load: float | None = None,
             pool_length: float | None = 25.0, hr: float | None = None,
             swolf: float | None = None, activity_id: int | None = None):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, environment, distance_m, duration_s, garmin_training_load, "
        "pool_length_m, avg_hr_bpm, avg_swolf, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', ?, 3600, ?, ?, ?, ?, 'sha', ?)",
        [activity_id or abs(hash(day + str(distance_m))) % 10**9,
         datetime.fromisoformat(day + "T08:00:00"), date.fromisoformat(day),
         distance_m, load, pool_length, hr, swolf, datetime(2026, 1, 1)],
    )


def add_health(con, day: str, resting_hr: float | None = None):
    con.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, source_object_id, imported_at) "
        "VALUES (?, ?, 'sha', ?)",
        [date.fromisoformat(day), resting_hr, datetime(2026, 1, 1)],
    )


def add_open_water_race(con, day: str, distance_m: float | None,
                        time_s: float = 3600.0, meet: str = "Gara in mare"):
    """Una gara in acque libere, come la porta il file della federazione."""
    con.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'fondo', ?, FALSE, ?, 'valid', 'acque libere', 'sha', ?)",
        [f"{day}-{meet}-{distance_m}", date.fromisoformat(day), meet,
         distance_m, time_s, datetime(2026, 1, 1)],
    )


def declare_same_swim(con, race_id: str, activity_id: int):
    """L'atleta dichiara che quella gara È quella nuotata dell'orologio."""
    con.execute(
        "INSERT INTO race_quality (race_id, verdict, activity_id, reason, "
        " decided_by, applied_at) "
        "VALUES (?, 'linked', ?, 'stessa nuotata', 'athlete', ?)",
        [race_id, activity_id, datetime(2026, 8, 25)],
    )


def read(con, day: str, column: str):
    return con.execute(
        f"SELECT {column} FROM daily_status WHERE status_date = ?",
        [date.fromisoformat(day)],
    ).fetchone()[0]


def test_volume_windows_count_calendar_days_not_rows(connection):
    # Due nuotate a otto giorni di distanza: la finestra a 7 giorni deve vedere
    # solo la seconda, anche se in mezzo non esiste nessuna riga di attività.
    add_swim(connection, "2026-01-01", 2000)
    add_swim(connection, "2026-01-09", 3000)
    add_health(connection, "2026-01-01")
    add_health(connection, "2026-01-09")
    daily_status.build(connection)

    assert read(connection, "2026-01-09", "swim_km_7d") == pytest.approx(3.0)
    assert read(connection, "2026-01-09", "swim_km_28d") == pytest.approx(5.0)


def test_rest_days_appear_in_the_spine(connection):
    add_swim(connection, "2026-01-01", 2000)
    add_swim(connection, "2026-01-05", 2000)
    add_health(connection, "2026-01-01")
    add_health(connection, "2026-01-05")
    daily_status.build(connection)

    # Il 3 gennaio non ha attività ma deve esistere: un giorno di riposo è
    # un'informazione, non un buco.
    assert read(connection, "2026-01-03", "sessions_count") == 0
    assert read(connection, "2026-01-03", "days_since_last_swim") == 2


def test_baseline_stays_null_without_enough_history(connection):
    # Con meno di 14 giorni di dati la risposta corretta è "non lo so ancora"
    for offset in range(5):
        add_health(connection, f"2026-01-0{offset + 1}", resting_hr=50 + offset)
    add_swim(connection, "2026-01-01", 1000)
    daily_status.build(connection)

    assert read(connection, "2026-01-05", "resting_hr_baseline_28") is None


def test_baseline_excludes_the_current_day(connection):
    # 20 giorni a 50 bpm, poi un giorno a 70: la baseline del giorno 21 deve
    # restare 50, altrimenti il valore di oggi sposterebbe il proprio riferimento.
    for offset in range(20):
        add_health(connection, f"2026-01-{offset + 1:02d}", resting_hr=50)
    add_health(connection, "2026-01-21", resting_hr=70)
    add_swim(connection, "2026-01-01", 1000)
    daily_status.build(connection)

    assert read(connection, "2026-01-21", "resting_hr_baseline_28") == pytest.approx(50.0)
    assert read(connection, "2026-01-21", "resting_hr_delta") == pytest.approx(20.0)


def test_acwr_needs_three_weeks_of_load(connection):
    # Con pochi giorni di carico il denominatore è instabile: niente ACWR.
    add_swim(connection, "2026-01-01", 2000, load=100)
    add_swim(connection, "2026-01-02", 2000, load=100)
    daily_status.build(connection)
    assert read(connection, "2026-01-02", "acwr") is None


def test_acwr_is_acute_over_weekly_chronic(connection):
    # 28 giorni a carico costante 100: acuto = 700, cronico = 2800/4 = 700,
    # quindi ACWR = 1. È la definizione dichiarata nel catalogo.
    for offset in range(28):
        day = date(2026, 1, 1).toordinal() + offset
        add_swim(connection, date.fromordinal(day).isoformat(), 2000, load=100)
    daily_status.build(connection)

    last = date(2026, 1, 28).isoformat()
    assert read(connection, last, "load_acute_7") == pytest.approx(700.0)
    assert read(connection, last, "load_chronic_28") == pytest.approx(700.0)
    assert read(connection, last, "acwr") == pytest.approx(1.0)


def test_monotony_is_null_when_load_never_varies(connection):
    # Deviazione standard zero: la monotonia non è definita, non è infinita.
    for offset in range(10):
        day = date(2026, 1, 1).toordinal() + offset
        add_swim(connection, date.fromordinal(day).isoformat(), 2000, load=100)
    daily_status.build(connection)
    assert read(connection, "2026-01-10", "monotony_7") is None


def test_swolf_is_never_mixed_between_pool_lengths(connection):
    # Lo SWOLF si confronta solo a parità di vasca: due colonne separate,
    # mai una media che le mescoli.
    add_swim(connection, "2026-01-01", 2000, pool_length=25.0, swolf=30.0)
    add_swim(connection, "2026-01-02", 2000, pool_length=50.0, swolf=60.0)
    daily_status.build(connection)

    assert read(connection, "2026-01-02", "swolf_28d_pool25") == pytest.approx(30.0)
    assert read(connection, "2026-01-02", "swolf_28d_pool50") == pytest.approx(60.0)


def test_coverage_flags_tell_the_truth_about_intensity(connection):
    # Una seduta senza frequenza cardiaca (come tutte quelle 2017-2020) deve
    # dichiararlo, non lasciare intendere che il dato ci sia.
    add_swim(connection, "2026-01-01", 2000, hr=None)
    add_swim(connection, "2026-01-02", 2000, hr=140)
    daily_status.build(connection)

    assert read(connection, "2026-01-01", "has_intensity") is False
    assert read(connection, "2026-01-02", "has_intensity") is True


# ── Le gare che l'orologio non ha registrato ───────────────────────────────
#
# «Le gare di Icron sono da contare all'interno delle nuotate anche quando non
# conteggiate, perché spesso non è consentito l'uso dell'orologio nelle gare in
# mare, ma sono nuotate a tutti gli effetti» — l'atleta, 24/08/2026.

def test_a_race_without_a_watch_is_a_swim_in_the_volume(connection):
    add_swim(connection, "2026-05-01", 2000)
    add_open_water_race(connection, "2026-05-10", 3000, time_s=2700)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 1
    assert read(connection, "2026-05-10", "swim_distance_m") == 3000
    assert read(connection, "2026-05-10", "session_duration_s") == 2700


def test_a_race_the_watch_did_record_is_not_counted_twice(connection):
    """Quando la gara **è** quella nuotata, i suoi metri sono già contati una
    volta: la riga di gara non ne aggiunge."""
    add_swim(connection, "2026-05-10", 4068, pool_length=None, activity_id=77)
    add_open_water_race(connection, "2026-05-10", 2500, meet="gara")
    declare_same_swim(connection, "2026-05-10-gara-2500", 77)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 1
    assert read(connection, "2026-05-10", "swim_distance_m") == 4068


def test_two_swims_in_a_day_are_not_one_because_they_share_the_date(connection):
    """Il caso che ha smontato il criterio per giorno: il 23/08/2026 la gara era
    a place04 la mattina e l'allenamento a place03 alle [orario], cento chilometri più
    in là. Dedurre dal solo giorno ne contava una sola."""
    add_swim(connection, "2026-05-10", 4068, pool_length=None)
    add_open_water_race(connection, "2026-05-10", 1900)   # nessun verdetto: distinte
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 2
    assert read(connection, "2026-05-10", "swim_distance_m") == 5968


def test_only_one_race_can_be_the_recorded_swim(connection):
    """Il 19/05/2018 ci sono due gare e una sola nuotata registrata, perché
    «l'orologio era consentito solo in una di queste». Le altre restano nuotate
    a sé: il criterio per giorno le azzerava tutte."""
    add_swim(connection, "2026-05-10", 5000, pool_length=None, activity_id=77)
    add_open_water_race(connection, "2026-05-10", 5000, meet="corsa-lunga")
    add_open_water_race(connection, "2026-05-10", 1500, meet="corsa-corta")
    declare_same_swim(connection, "2026-05-10-corsa-lunga-5000", 77)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 2
    assert read(connection, "2026-05-10", "swim_distance_m") == 6500


def test_an_excluded_race_leaves_the_volume_alone(connection):
    """«Non la considerare come gara, avevano ridotto il giro, ci sono stati
    problemi, il mare era agitato. Lasciala tra i dati ma non considerarla.»"""
    # Due nuotate intorno alla gara, perché il calendario copra quel giorno:
    # una gara esclusa non allunga da sola la spina temporale.
    add_swim(connection, "2026-05-01", 2000)
    add_swim(connection, "2026-05-20", 2000)
    add_open_water_race(connection, "2026-05-10", 2000, meet="event05")
    connection.execute(
        "INSERT INTO race_quality (race_id, verdict, reason, decided_by, "
        " applied_at) VALUES (?, 'exclude', 'giro ridotto', 'athlete', ?)",
        ["2026-05-10-event05-2000", datetime(2026, 8, 25)])
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 0
    assert read(connection, "2026-05-10", "swim_distance_m") == 0


def test_a_partly_unknown_day_sums_what_it_knows(connection):
    """Il 19/05/2018: tre nuotate, una gara di cui la distanza dichiarata era
    falsa. Il giorno somma i metri che conosce e dichiara su quante nuotate,
    invece di annullarsi tutto."""
    add_swim(connection, "2026-05-10", 3634, pool_length=None)
    connection.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, source_object_id, imported_at) "
        "VALUES ('senza-metri', ?, 'gara', 'fondo', NULL, FALSE, 835, 'valid', "
        "'acque libere', 'sha', ?)",
        [date(2026, 5, 10), datetime(2026, 1, 1)])
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 2
    assert read(connection, "2026-05-10", "swim_distance_m") == 3634
    assert read(connection, "2026-05-10", "swim_distance_known_n") == 1


def test_two_races_in_a_day_are_two_sessions(connection):
    """Il 28/05/2016 e il 07/09/2019 hanno due gare: due prove con partenza e
    arrivo propri (decisione dell'atleta, 25/08/2026)."""
    add_open_water_race(connection, "2026-05-10", 1500, meet="mattina")
    add_open_water_race(connection, "2026-05-10", 3000, meet="pomeriggio")
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 2
    assert read(connection, "2026-05-10", "swim_distance_m") == 4500


def test_a_race_without_a_declared_distance_leaves_the_day_unknown(connection):
    """Tre gare dell'archivio non dichiarano i metri. Il giorno resta
    sconosciuto, non a zero (R5), e la seduta si conta lo stesso."""
    add_open_water_race(connection, "2026-05-10", None)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "swim_sessions_count") == 1
    assert read(connection, "2026-05-10", "swim_distance_m") is None
    assert read(connection, "2026-05-10", "swim_distance_known_n") == 0


def test_a_race_brings_metres_but_never_heartbeats(connection):
    add_open_water_race(connection, "2026-05-10", 3000)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "has_intensity") is False
    assert read(connection, "2026-05-10", "has_load") is False


def test_a_race_before_the_first_activity_still_has_its_day(connection):
    """La spina nasceva dalle attività: le gare del 28/05/2016 e del 27/05/2017
    cadevano fuori dal calendario e sparivano senza dire niente."""
    add_open_water_race(connection, "2016-05-28", 4500)
    add_swim(connection, "2026-05-01", 2000)
    daily_status.build(connection)

    assert read(connection, "2016-05-28", "swim_distance_m") == 4500


def test_a_race_day_with_a_run_counts_both(connection):
    """`sessions_count` somma anche dove `swim_sessions_count` non somma."""
    connection.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        "sport, is_swim, distance_m, duration_s, source_object_id, imported_at) "
        "VALUES (99, ?, ?, 'running', FALSE, 10000, 3000, 'sha', ?)",
        [datetime(2026, 5, 10, 8), date(2026, 5, 10), datetime(2026, 1, 1)])
    add_open_water_race(connection, "2026-05-10", 3000)
    daily_status.build(connection)

    assert read(connection, "2026-05-10", "sessions_count") == 2
    assert read(connection, "2026-05-10", "swim_sessions_count") == 1
