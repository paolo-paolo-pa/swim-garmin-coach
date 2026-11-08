"""Contratti nuovi: API ufficiale, non perdita dello storico, piani e CSS."""
from datetime import date, datetime

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach.database import SCHEMA
from garmin_coach.ingest.personal_api import PersonalGarmin, PersonalApiFailure, normalize_summary
from garmin_coach.ingest import sync, source_catalog
from garmin_coach.analysis import dashboard, workout_builder
from garmin_coach.app import server, security


def test_official_nested_health_units_and_missing_values():
    result = normalize_summary({"heartRate": {"restingValue": 46},
        "stress": {"restDurationInMillis": 13500}, "bodyBattery": {"minValue": 9}})
    assert result["restingHeartRate"] == 46
    assert result["restStressDuration"] == 13.5
    assert result["bodyBatteryLowestValue"] == 9
    assert result["bodyBatteryHighestValue"] is None


def test_official_pagination_and_capture(monkeypatch):
    captured = []
    monkeypatch.setattr(source_catalog, "capture", lambda *args: captured.append(args))
    class Client:
        def search_activities(self, **kwargs):
            return [{"activityId": i} for i in range(100)] if kwargs["start"] == 0 else [{"activityId": 100}]
    adapter = PersonalGarmin(Client())
    assert len(adapter.get_activities_by_date("2026-10-01", "2026-10-26")) == 101
    assert captured[-1][1] == "get_activities_by_date"
    assert not hasattr(adapter, "upload_workout")


def test_http_auth_error_never_leaks_response(monkeypatch):
    class FakeError(Exception):
        status_code = 401
    class Client:
        def get_daily_hrv(self, *args):
            raise FakeError("SECRET bearer token")
    with pytest.raises(PersonalApiFailure) as error:
        PersonalGarmin(Client()).get_hrv_data("2026-10-25")
    assert "SECRET" not in str(error.value)
    assert "401" in str(error.value)


def test_personal_flat_sleep_is_adapted_before_ingestion(monkeypatch):
    monkeypatch.setattr(source_catalog, "capture", lambda *args: None)
    class Client:
        def get_daily_sleep(self, *args):
            return {"sleepTimeSeconds": 28000, "sleepScores": {"overall": {"value": 86}}}
    result = PersonalGarmin(Client()).get_sleep_data("2026-10-25")
    assert result["dailySleepDTO"]["sleepTimeSeconds"] == 28000


def test_incremental_fit_uses_identity_and_does_not_duplicate(tmp_path, monkeypatch):
    from garmin_coach.ingest import swim_details
    from test_swim_details import _four_by_hundred, _reader
    import fitdecode
    monkeypatch.setattr(source_catalog, "RAW_FIT", tmp_path)
    monkeypatch.setattr(fitdecode, "FitReader", _reader(_four_by_hundred()))
    (tmp_path / "42.fit").write_bytes(b"fixture-explicitly-synthetic")
    c = duckdb.connect(":memory:")
    c.execute(SCHEMA)
    c.execute("""INSERT INTO activities(activity_id,start_time_utc,activity_date,sport,is_swim,
        environment,distance_m,duration_s,source_object_id,imported_at)
        VALUES (42,'2026-10-25','2026-10-25','lap_swimming',true,'pool',400,400,'fixture',current_timestamp)""")
    assert swim_details.load_downloaded(c) == {"activities_parsed":1,"errors":[]}
    counts = [c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['activity_laps','pool_lengths']]
    assert counts[0] > 0 and counts[1] == 16
    assert swim_details.load_downloaded(c) == {"activities_parsed":0,"errors":[]}
    assert [c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['activity_laps','pool_lengths']] == counts
    assert c.execute('SELECT method FROM activity_source_matches').fetchone()[0] == 'activity_id'
    c.close()


def test_activity_refresh_preserves_device_and_columns_not_returned_by_api():
    c = duckdb.connect(":memory:")
    c.execute(SCHEMA)
    c.execute("""INSERT INTO activities(activity_id,start_time_utc,activity_date,sport,is_swim,
        distance_m,duration_s,device_id,hr_zone_3_s,source_object_id,imported_at)
        VALUES (42,'2026-10-25','2026-10-25','lap_swimming',true,2000,3000,99,150,'original',current_timestamp)""")
    class Client:
        def get_activities_by_date(self, *args):
            return [{"activityId":42,"startTimeGMT":"2026-10-25 10:00:00",
                     "activityType":{"typeKey":"lap_swimming"},"distance":2100,"duration":3100}]
        def get_user_summary(self, *args):
            return None
    sync.pull(c, until=date(2026,10,25), client=Client())
    sync.pull(c, until=date(2026,10,25), client=Client())
    assert c.execute("SELECT device_id,hr_zone_3_s,distance_m FROM activities WHERE activity_id=42").fetchone() == (99,150,2100)
    assert c.execute("SELECT count(*) FROM activities").fetchone()[0] == 1
    c.close()


def test_css_requires_real_protocol_and_computes_pace():
    test = {"date":"2026-10-26","t400":300,"t200":140,"pool":25,"maximal":True}
    result = workout_builder.css_test(test)
    assert result["pace_100_s"] == 80
    assert result["zones"]["Z2"] == [85,90]
    with pytest.raises(ValueError):
        workout_builder.css_test(dict(test, maximal=False))


def test_builder_total_and_rejects_unsafe_input():
    result = workout_builder.workout({"date":"2026-10-27","title":"10×100",
         "blocks":[{"reps":10,"distance_m":100,"rest_s":20,"zone":"Z4"}]})
    assert result["total_m"] == 1000
    assert result["garmin_published"] is False
    with pytest.raises(ValueError):
        workout_builder.workout(dict(result, blocks=[{"reps":-1,"distance_m":100}]))


def test_api_preview_confirmation_is_bound_and_idempotent(tmp_path, monkeypatch):
    from garmin_coach import paths, athlete_files
    from garmin_coach.app.platform import install
    monkeypatch.setattr(paths, "COACH", tmp_path)
    app = server.build()
    install(app)
    client = TestClient(app)
    body = {"date":"2026-10-27","title":"Sessione di prova",
            "blocks":[{"reps":6,"distance_m":200,"zone":"Z2","rest_s":20}]}
    assert client.post('/api/platform/builder', json=body).status_code == 403
    headers = {"origin":"http://127.0.0.1:8766", "x-csrf-token":security.TOKEN}
    preview = client.post('/api/platform/builder', json=body, headers=headers).json()
    assert not athlete_files.structured_entries('workouts')
    confirmation = {"confirm":True,"preview_token":preview['preview_token'],"title":"Alterato"}
    first = client.post('/api/platform/builder', json=confirmation, headers=headers)
    assert first.status_code == 200
    second = client.post('/api/platform/builder', json=confirmation, headers=headers)
    assert second.json() == first.json()
    assert athlete_files.structured_entries('workouts')[0]['title'] == 'Sessione di prova'
