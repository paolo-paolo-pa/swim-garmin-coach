"""Passo e serie dichiarate: soltanto sui campioni realmente disponibili."""

from datetime import datetime, timedelta

import duckdb
import pytest

from garmin_coach import athlete_files
from garmin_coach.analysis import dashboard, open_water_segments, session_annotations
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import track


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def add_track(connection, samples, passed=True):
    connection.executemany(
        "INSERT INTO activity_track (activity_id,point_index,elapsed_s,distance_m,heart_rate_bpm,source_object_id,imported_at) VALUES (1,?,?,?,?,'synthetic',current_timestamp)",
        [(i, *sample) for i, sample in enumerate(samples)],
    )
    if passed is not None:
        connection.execute(
            "INSERT INTO activity_track_quality (activity_id,points,gps_points,segments_ok,has_heart_rate,source_object_id,imported_at) VALUES (1,?,?,?,false,'synthetic',current_timestamp)",
            [len(samples), len(samples), passed],
        )


@pytest.mark.parametrize("gate", [False, None])
def test_rejected_or_missing_gps_quality_has_no_segment_pace(connection, gate):
    add_track(connection, [(0, 0, None), (100, 100, None)], gate)
    segment = open_water_segments.report(connection, 1)["segments"][0]
    assert segment["pace_100_s"] is None
    assert segment["hr_bpm"] is None and segment["hr_n"] == 0


def test_distance_reset_even_between_windows_disables_pace(connection):
    add_track(connection, [(0, 0, 130), (299, 299, 140), (300, 0, 140), (599, 299, 150)])
    report = open_water_segments.report(connection, 1)
    assert all(s["pace_100_s"] is None for s in report["segments"])
    assert report["distance_monotonic"] is False


def test_window_geometry_pairs_distance_timestamps_without_interpolation(connection):
    add_track(connection, [(10, None, None), (20, 100, 140), (120, 200, None), (290, None, 160), (300, 300, None)])
    report = open_water_segments.report(connection, 1)
    first, second = report["segments"]
    assert (first["start_s"], first["end_s"], first["observed_s"]) == (10, 290, 280)
    assert first["distance_m"] == 100 and first["pace_100_s"] == 100
    assert first["distance_observed_s"] == 100
    assert first["distance_n"] == 2 and first["points_n"] == 4
    assert first["hr_bpm"] == 150 and first["hr_n"] == 2
    assert second["label"] == "5–10 min"
    assert second["distance_m"] is None and second["pace_100_s"] is None
    assert second["observed_s"] == 0


@pytest.mark.parametrize("distances", [[100, 50, 200], [None, None, None], [50, 50, 50]])
def test_nonmonotonic_missing_or_stationary_distance_has_no_pace(connection, distances):
    add_track(connection, [(i * 50, d, None) for i, d in enumerate(distances)])
    assert open_water_segments.report(connection, 1)["segments"][0]["pace_100_s"] is None


def test_report_contains_no_coordinate_fields(connection):
    add_track(connection, [(0, 0, None), (100, 100, None)])
    connection.execute("UPDATE activity_track_quality SET start_lat_rounded=45,start_lon_rounded=9")
    report = open_water_segments.report(connection, 1)
    assert not any("lat" in key or "lon" in key for key in report["quality"])
    assert all(not any("lat" in key or "lon" in key for key in segment) for segment in report["segments"])


def add_laps(connection):
    connection.executemany("INSERT INTO activity_laps (activity_id,lap_index,source_object_id,imported_at) VALUES (1,?,'synthetic',current_timestamp)", [(0,), (1,), (3,), (4,)])


def test_manual_groups_preserve_recorded_indices_and_declared_provenance(connection):
    add_laps(connection)
    groups = session_annotations.validate_groups(connection, 1, [
        {"first_lap": "0", "last_lap": "1", "label": "Riscaldamento"},
        {"first_lap": 3, "last_lap": 4},
    ])
    assert groups[0] == {"first_lap": 0, "last_lap": 1, "label": "Riscaldamento", "source": "athlete_confirmed"}
    assert groups[1]["first_lap"] == 3


@pytest.mark.parametrize("groups", [
    [{"first_lap": 0, "last_lap": 3}, {"first_lap": 1, "last_lap": 4}],
    [{"first_lap": 2, "last_lap": 4}],
    [{"first_lap": 4, "last_lap": 0}],
    [{"first_lap": 0.9, "last_lap": 1}],
    [{"first_lap": True, "last_lap": 3}],
    [{"first_lap": None, "last_lap": 3}],
    [{"first_lap": 0}], [None], {}, [dict(first_lap=0,last_lap=0)] * 61,
])
def test_invalid_or_overlapping_groups_raise_validation_errors(connection, groups):
    add_laps(connection)
    with pytest.raises(ValueError):
        session_annotations.validate_groups(connection, 1, groups)


def lap(index, distance, duration, rest=False):
    return dict(lap_index=index, distance_m=distance, duration_s=duration, is_rest=rest)


def test_declared_series_separates_rest_unknown_and_paired_measurements():
    laps = [lap(0, 100, 90), lap(1, 0, 20, True), lap(2, 100, None),
            lap(3, None, 30), lap(4, 200, 200, None)]
    summary = session_annotations.summarize({"sets": [{"first_lap": 0, "last_lap": 4}]}, laps)[0]
    assert summary["lap_n"] == 5 and summary["active_laps"] == 3
    assert summary["unknown_laps"] == 1
    assert summary["distance_m"] == 200 and summary["distance_n"] == 2
    assert summary["active_s"] == 120 and summary["time_n"] == 2
    assert summary["rest_s"] == 20 and summary["rest_laps"] == 1
    assert summary["pace_100_s"] == 90 and summary["pace_n"] == 1


def test_declared_series_missing_values_remain_missing():
    result = session_annotations.summarize({"sets": [{"first_lap": 0, "last_lap": 0}]}, [lap(0, None, None)])[0]
    assert result["distance_m"] is None and result["active_s"] is None
    assert result["rest_s"] is None and result["pace_100_s"] is None
    assert result["pace_n"] == 0


def test_nonpositive_active_duration_is_not_a_valid_pace_pair():
    result = session_annotations.summarize({"sets": [{"first_lap": 0, "last_lap": 1}]}, [lap(0, 100, -1), lap(1, 100, 0)])[0]
    assert result["pace_100_s"] is None and result["pace_n"] == 0


def test_downloaded_track_is_incremental_source_linked_and_idempotent(connection, tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(track.source_catalog, "RAW_FIT", raw)
    monkeypatch.setattr(track.paths, "ROOT", tmp_path)
    connection.executemany(
        "INSERT INTO activities (activity_id,is_swim,environment,distance_m,start_time_utc,activity_date,sport,source_object_id,imported_at) VALUES (?,true,'open_water',100,'2026-01-01','2026-01-01','open_water_swimming','synthetic',current_timestamp)", [(1,), (2,)],
    )
    add_track(connection, [(0, 0, None), (100, 100, None)])
    historical = connection.execute("SELECT * FROM activity_track WHERE activity_id=1 ORDER BY point_index").fetchall()
    quality = connection.execute("SELECT * FROM activity_track_quality WHERE activity_id=1").fetchall()
    (raw / "1.fit").write_bytes(b"must not reparse history")
    (raw / "2.fit").write_bytes(b"synthetic fit bytes")
    calls = []
    def points(content):
        calls.append(content)
        return [{"timestamp": datetime(2026, 1, 1) + timedelta(seconds=i), "distance": i * 10} for i in range(2)]
    monkeypatch.setattr(track, "_points", points)
    assert track.load_downloaded(connection) == {"activities_parsed": 1, "errors": []}
    assert track.load_downloaded(connection) == {"activities_parsed": 0, "errors": []}
    assert calls == [b"synthetic fit bytes"]
    assert connection.execute("SELECT * FROM activity_track WHERE activity_id=1 ORDER BY point_index").fetchall() == historical
    assert connection.execute("SELECT * FROM activity_track_quality WHERE activity_id=1").fetchall() == quality
    assert connection.execute("SELECT count(*) FROM activity_track t JOIN source_objects s USING(source_object_id) WHERE activity_id=2 AND s.parser='fit-track' AND length(s.sha256)=64").fetchone()[0] == 2


def test_failed_source_registration_rolls_back_only_new_track(connection, tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(track.source_catalog, "RAW_FIT", raw)
    monkeypatch.setattr(track.paths, "ROOT", tmp_path)
    connection.executemany(
        "INSERT INTO activities (activity_id,is_swim,environment,distance_m,start_time_utc,activity_date,sport,source_object_id,imported_at) VALUES (?,true,'open_water',100,'2026-01-01','2026-01-01','open_water_swimming','synthetic',current_timestamp)", [(1,), (2,)],
    )
    add_track(connection, [(0, 0, None), (100, 100, None)])
    historical = connection.execute("SELECT * FROM activity_track ORDER BY point_index").fetchall()
    (raw / "2.fit").write_bytes(b"synthetic fit bytes")
    monkeypatch.setattr(track, "_points", lambda _: [{"timestamp": datetime(2026, 1, 1), "distance": 0}])
    def fail_registration(*_):
        raise RuntimeError("synthetic registration failure")
    monkeypatch.setattr(track.source_catalog, "register", fail_registration)
    assert track.load_downloaded(connection) == {"activities_parsed": 0, "errors": [{"activity_id": 2, "error": "RuntimeError"}]}
    assert connection.execute("SELECT * FROM activity_track ORDER BY point_index").fetchall() == historical
    assert connection.execute("SELECT count(*) FROM activity_track_quality WHERE activity_id=2").fetchone()[0] == 0


def test_activity_detail_reads_persisted_annotation_and_shared_private_track_report(connection, tmp_path, monkeypatch):
    monkeypatch.setattr(athlete_files.paths, "COACH", tmp_path / "synthetic-coach")
    connection.execute("""INSERT INTO activities
        (activity_id,is_swim,environment,distance_m,start_time_utc,activity_date,sport,source_object_id,imported_at)
        VALUES (1,true,'open_water',100,'2026-01-01','2026-01-01','open_water_swimming','synthetic',current_timestamp)""")
    add_laps(connection)
    connection.execute("UPDATE activity_laps SET is_rest=false,distance_m=100,duration_s=90 WHERE lap_index=0")
    add_track(connection, [(0, 0, None), (100, 100, None)])
    connection.execute("UPDATE activity_track_quality SET start_lat_rounded=45,start_lon_rounded=9")
    groups = session_annotations.validate_groups(connection, 1, [{"first_lap": 0, "last_lap": 0, "label": "Dichiarata"}])
    original = connection.execute("SELECT * FROM activity_laps ORDER BY lap_index").fetchall()
    athlete_files.add_structured_entry("session-annotations", {"activity_id": 1, "sets": []})
    saved = athlete_files.add_structured_entry("session-annotations", {"activity_id": 1, "sets": groups})
    for _ in range(2):
        detail = dashboard.activity(connection, 1)
        assert detail["annotation"] == saved
        assert detail["manual_structure"][0]["pace_100_s"] == 90
        assert detail["manual_structure"][0]["source"] == "athlete_confirmed"
        assert detail["open_water"] == open_water_segments.report(connection, 1)
        assert not any("lat" in key or "lon" in key for key in detail["open_water"]["quality"])
        assert all(set(p) == {"elapsed_s", "distance_m", "speed_ms", "heart_rate_bpm"} for p in detail["track"])
    assert connection.execute("SELECT * FROM activity_laps ORDER BY lap_index").fetchall() == original
    assert len(athlete_files.structured_entries("session-annotations")) == 2


@pytest.mark.parametrize("first_duration", [30, None])
def test_activity_pool_detail_pairs_pace_and_preserves_all_missing_duration(connection, tmp_path, monkeypatch, first_duration):
    monkeypatch.setattr(athlete_files.paths, "COACH", tmp_path / "synthetic-coach")
    connection.execute("""INSERT INTO activities
        (activity_id,is_swim,environment,pool_length_m,start_time_utc,activity_date,sport,source_object_id,imported_at)
        VALUES (1,true,'pool',25,'2026-01-01','2026-01-01','lap_swimming','synthetic',current_timestamp)""")
    connection.executemany("INSERT INTO pool_lengths (activity_id,length_index,is_active,duration_s) VALUES (1,?,?,?)",
                           [(0, True, first_duration), (1, True, None), (2, False, None), (3, None, 500)])
    detail = dashboard.activity(connection, 1)
    times = detail["times"]
    assert times["active_s"] == first_duration
    assert times["active_duration_n"] == (1 if first_duration else 0)
    assert times["pace_lengths_n"] == (1 if first_duration else 0)
    assert times["active_pace_100_s"] == (120 if first_duration else None)
    assert times["active_lengths"] == 2 and times["active_distance_m"] == 50
    assert times["rest_s"] is None and times["rest_duration_n"] == 0
    assert times["rest_lengths"] == 1 and times["coverage_lengths"] == 4
    assert detail["open_water"] is None
