"""Il sync da Garmin Connect, provato con un client finto.

Nessuna chiamata reale è mai stata eseguita: servono le credenziali dell'atleta.
Questi test verificano ciò che si può verificare senza rete — la mappatura dei
campi e, soprattutto, il blocco che impedisce di scrivere dati implausibili se
Garmin cambia le unità di misura.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.ingest import sync


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    # Il sync riparte dall'ultimo giorno noto: serve almeno una riga.
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, distance_m, duration_s, source_object_id, imported_at) "
        "VALUES (1, ?, ?, 'lap_swimming', TRUE, 3000, 3600, 'sha', ?)",
        [datetime(2026, 8, 10, 8), date(2026, 8, 10), datetime(2026, 8, 10)])
    yield con
    con.close()


class FakeGarmin:
    """Un client che restituisce quello che gli si dice, senza toccare la rete."""

    def __init__(self, activities=None, summary=None, sleep=None, hrv=None,
                 fail_on_day=None):
        self._activities = activities or []
        self._summary = summary or {}
        self._sleep = sleep or {}
        self._hrv = hrv or {}
        self._fail_on_day = fail_on_day

    def get_activities_by_date(self, start, end):
        return self._activities

    def _maybe_fail(self, day):
        if self._fail_on_day and day == self._fail_on_day:
            raise ConnectionError("rete non disponibile")

    def get_user_summary(self, day):
        self._maybe_fail(day)
        return self._summary

    def get_sleep_data(self, day):
        self._maybe_fail(day)
        return {"dailySleepDTO": self._sleep}

    def get_hrv_data(self, day):
        self._maybe_fail(day)
        return {"hrvSummary": self._hrv}


WEB_ACTIVITY = {
    "activityId": 987654321,
    "activityName": "Nuoto mattina",
    "startTimeGMT": "2026-08-14 06:30:00",
    "startTimeLocal": "2026-08-14 08:30:00",
    "activityType": {"typeKey": "lap_swimming"},
    "duration": 3600.0,          # secondi — l'API web usa unità SI
    "distance": 3000.0,          # metri
    "averageHR": 138.0,
    "poolLength": 25.0,
    "averageSwolf": 31.0,
    "deviceId": 20000000001,
}


def test_web_units_are_accepted(connection):
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[WEB_ACTIVITY]))
    assert report.succeeded, report.errors
    assert report.activities_written == 1

    row = connection.execute(
        "SELECT distance_m, duration_s, pool_length_m, avg_hr_bpm, sport "
        "FROM activities WHERE activity_id = 987654321").fetchone()
    assert row == (3000.0, 3600.0, 25.0, 138.0, "lap_swimming")


def test_pool_length_in_centimetres_is_recognised(connection):
    """Misurato sul campo il 2026-08-20: l'API web restituisce la vasca in
    centimetri (2500) mentre la distanza è in metri. Il sync deve riconoscere
    la scala, non rifiutare il dato né scrivere una vasca da 2.500 metri."""
    real = dict(WEB_ACTIVITY, poolLength=2500.0)
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[real]))

    assert report.succeeded, report.errors
    pool = connection.execute(
        "SELECT pool_length_m FROM activities WHERE activity_id = 987654321"
    ).fetchone()[0]
    assert pool == 25.0
    # la scala riconosciuta non resta un dettaglio nascosto
    assert report.units_detected.get("pool_length_m") == "centesimi"


def test_scaled_distance_and_duration_are_recognised(connection):
    scaled = dict(WEB_ACTIVITY, distance=300_000.0, duration=3_600_000.0)
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[scaled]))

    assert report.succeeded, report.errors
    row = connection.execute(
        "SELECT distance_m, duration_s FROM activities WHERE activity_id = 987654321"
    ).fetchone()
    assert row == (3000.0, 3600.0)


def test_value_no_scale_explains_is_still_refused(connection):
    """La tolleranza sulle scale non deve diventare tolleranza sugli assurdi:
    900 bpm non è un problema di unità di misura."""
    absurd = dict(WEB_ACTIVITY, averageHR=900.0)
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[absurd]))

    assert not report.succeeded
    assert "nessuna scala nota" in report.errors[0]
    written = connection.execute(
        "SELECT count(*) FROM activities WHERE activity_id = 987654321").fetchone()[0]
    assert written == 0, "niente va scritto quando il dato non è interpretabile"


def test_garmin_zero_does_not_become_a_measurement(connection):
    """Garmin scrive 0 al posto del dato mancante. Trovato il 2026-08-20: 15
    sedute erano entrate con distanza per bracciata = 0, e la media a 28 giorni
    del briefing diceva 0,00 m/bracciata — un numero inventato dal sync, non
    misurato. Zero non è una misura: resta mancante (Regola Aurea n.5)."""
    silent = dict(WEB_ACTIVITY, avgStrokeDistance=0, strokes=0,
                  averageSwimCadenceInStrokesPerMinute=0, activityTrainingLoad=0)
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[silent]))

    assert report.succeeded, report.errors
    row = connection.execute(
        "SELECT avg_stroke_distance_m, total_strokes, avg_swim_cadence_spm, "
        "garmin_training_load FROM activities WHERE activity_id = 987654321"
    ).fetchone()
    assert row == (None, None, None, None)


def test_technical_metrics_are_written_when_present(connection):
    complete = dict(WEB_ACTIVITY, avgStrokeDistance=2.1, strokes=1180,
                    averageSwimCadenceInStrokesPerMinute=34.0,
                    activityTrainingLoad=96.0, aerobicTrainingEffect=3.2)
    report = sync.pull(connection, until=date(2026, 8, 14),
                       client=FakeGarmin(activities=[complete]))

    assert report.succeeded, report.errors
    row = connection.execute(
        "SELECT avg_stroke_distance_m, total_strokes, avg_swim_cadence_spm, "
        "garmin_training_load, garmin_aerobic_te FROM activities "
        "WHERE activity_id = 987654321").fetchone()
    assert row == (2.1, 1180.0, 34.0, 96.0, 3.2)


def test_sync_is_idempotent(connection):
    client = FakeGarmin(activities=[WEB_ACTIVITY])
    sync.pull(connection, until=date(2026, 8, 14), client=client)
    sync.pull(connection, until=date(2026, 8, 14), client=client)

    count = connection.execute(
        "SELECT count(*) FROM activities WHERE activity_id = 987654321").fetchone()[0]
    assert count == 1


def test_sync_overlaps_the_last_known_day(connection):
    # Garmin corregge i dati del giorno prima: senza sovrapposizione si
    # conserverebbe una versione provvisoria.
    report = sync.pull(connection, until=date(2026, 8, 14), client=FakeGarmin())
    assert report.start == date(2026, 8, 10) - __import__("datetime").timedelta(
        days=sync.OVERLAP_DAYS)


def test_a_failing_day_does_not_stop_the_others(connection):
    client = FakeGarmin(summary={"restingHeartRate": 52},
                        fail_on_day="2026-08-12")
    report = sync.pull(connection, until=date(2026, 8, 14), client=client)

    assert report.succeeded
    assert any("2026-08-12" in note for note in report.skipped)
    assert report.health_days_written > 0


def test_gap_too_large_is_refused(connection):
    report = sync.pull(connection, until=date(2027, 6, 1), client=FakeGarmin())
    assert not report.succeeded
    assert "export completo" in report.errors[0]


def test_missing_token_gives_actionable_advice(connection, monkeypatch, tmp_path):
    from garmin_coach.ingest import garmin_login
    monkeypatch.setattr(garmin_login, "TOKEN_STORE", tmp_path / "assente")
    report = sync.pull(connection, until=date(2026, 8, 14))
    assert not report.succeeded
    assert "garmin_coach connect" in report.errors[0]


def test_sync_rows_are_traceable_to_garmin_connect(connection):
    sync.pull(connection, until=date(2026, 8, 14),
              client=FakeGarmin(activities=[WEB_ACTIVITY]))
    origin = connection.execute(
        "SELECT source_object_id FROM activities WHERE activity_id = 987654321").fetchone()[0]
    assert origin.startswith(sync.SOURCE_PREFIX)
