"""«Posso fidarmi di grafici, serie dichiarate e piani prima di usarli?»

Contratti del completamento piattaforma, su sorgenti sintetiche e memoria
atleta temporanea. Nessuna chiamata Garmin o a modelli esterni.
"""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import duckdb
import pytest

from starlette.applications import Starlette
from starlette.testclient import TestClient

from garmin_coach import athlete_files, paths, schema_migrations
from garmin_coach.analysis import calendar_view, intraday, session_annotations
from garmin_coach.analysis import training_workspace as training
from garmin_coach.coach import codex_cli
from garmin_coach.coach.contract import CoachContextPacket, Fact
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import health_samples, source_catalog
from garmin_coach.metrics import daily_status


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "COACH", tmp_path / "athlete")
    connection = duckdb.connect(":memory:")
    connection.execute(SCHEMA)
    yield connection
    connection.close()


@pytest.fixture
def packet():
    result = CoachContextPacket("Come sto andando?", date(2026, 10, 26))
    result.add(Fact("volume", "Nuoto", 21.78, "km", "21,78 km", "ultimi 7 giorni", n=3))
    return result


VALID_RESPONSE = {
    "verdict": "La continuità è documentata, la tenuta specifica resta da verificare.",
    "primary_focus": "Confrontare sedute omogenee con il tuo allenatore.",
    "confidence": "moderate",
    "why": ["volume"],
}


def test_codex_command_disables_external_tools_and_user_configuration(tmp_path):
    args = codex_cli.command(Path("codex.exe"), tmp_path / "answer.json")
    assert args[:2] == ["codex.exe", "exec"]
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--output-last-message") + 1] == str(tmp_path / "answer.json")
    assert 'web_search="disabled"' in args and "project_doc_max_bytes=0" in args
    disabled = {args[i + 1] for i, value in enumerate(args) if value == "--disable"}
    assert {"shell_tool", "unified_exec", "apps", "plugins", "browser_use",
            "browser_use_external", "computer_use", "in_app_browser", "view_image",
            "image_generation", "multi_agent", "multi_agent_v2"} <= disabled
    assert args[-1] == "-"


@pytest.mark.parametrize("changes", [
    {"verdict": "Hai nuotato 38,4 km."},
    {"why": ["evidence_not_in_packet"]},
    {"counterpoints": ["unknown_counterpoint"]},
])
def test_codex_rejects_fabricated_numbers_and_unknown_evidence(packet, monkeypatch, changes):
    runner = Mock(return_value=json.dumps({**VALID_RESPONSE, **changes}))
    monkeypatch.setattr(codex_cli, "run", runner)
    with pytest.raises(codex_cli.BrainUnavailable, match="dati verificati"):
        codex_cli.CodexBrain(Path("synthetic-codex.exe")).judge(packet)
    assert runner.call_count == 2
    assert "validatore" in runner.call_args_list[1].args[1]
    assert not codex_cli.LOCK.locked()


def test_codex_accepts_corrected_answer_with_packet_digest(packet, monkeypatch):
    runner = Mock(side_effect=[
        json.dumps({**VALID_RESPONSE, "why": ["unknown"]}),
        json.dumps(VALID_RESPONSE),
    ])
    monkeypatch.setattr(codex_cli, "run", runner)
    response = codex_cli.CodexBrain(Path("synthetic-codex.exe")).judge(packet)
    assert response.packet_digest == packet.digest
    assert response.why == ["volume"] and response.model == codex_cli.CodexBrain.name
    assert response.generated_on == packet.observation_date
    assert json.dumps(packet.as_dict(), ensure_ascii=False, default=str) in runner.call_args_list[0].args[1]
    assert not codex_cli.LOCK.locked()


def test_codex_provider_failure_releases_single_request_lock(packet, monkeypatch):
    runner = Mock(side_effect=codex_cli.BrainUnavailable("Provider non disponibile"))
    monkeypatch.setattr(codex_cli, "run", runner)
    with pytest.raises(codex_cli.BrainUnavailable, match="Provider"):
        codex_cli.CodexBrain(Path("synthetic-codex.exe")).judge(packet)
    assert runner.call_count == 1 and not codex_cli.LOCK.locked()


def sample_payload(metric, values):
    _, values_key, descriptor_key, index_key, name_key, value_key = health_samples.METRICS[metric]
    # Valore in posizione zero, timestamp in posizione due: niente indici fissi.
    return {descriptor_key: [{name_key: value_key, index_key: 0},
                             {name_key: "timestamp", index_key: 2}],
            values_key: values}


def source_for(payload, revision="first"):
    return source_catalog.describe(json.dumps(payload).encode(), "garmin_connect",
                                   "synthetic/" + revision + ".json", "health-samples", "1")


@pytest.mark.parametrize("metric,values,expected", [
    ("heart_rate_bpm", [61, None, 0, -1, True, float("nan")], [61.0, None, None, None, None, None]),
    ("body_battery", [0, 100, None, -1, 101, True, float("inf")], [0.0, 100.0, None, None, None, None, None]),
])
def test_sample_descriptors_and_missing_sentinels(metric, values, expected):
    start = datetime(2026, 10, 25, tzinfo=timezone.utc)
    milliseconds = int(start.timestamp() * 1000)
    payload = sample_payload(metric, [[v, "unused", milliseconds + i * 60000]
                                      for i, v in enumerate(values)])
    parsed = health_samples.parse(payload, metric)
    assert [v for _, v in parsed] == expected
    assert [t for t, _ in parsed] == [start.replace(tzinfo=None) + timedelta(minutes=i)
                                     for i in range(len(values))]


def test_sample_parse_sorts_deduplicates_and_keeps_null_gap():
    payload = sample_payload("body_battery", [[5, None, 180000], [9, None, 60000],
                                               [None, None, 120000], [0, None, 180000],
                                               [10], [10, None, "bad timestamp"]])
    assert [v for _, v in health_samples.parse([{}, payload], "body_battery")] == [9.0, None, 0.0]
    assert health_samples.parse({}, "body_battery") == []


def test_sample_normalization_replaces_snapshot_idempotently_and_tracks_source(database):
    day = date(2026, 10, 25)
    payload = sample_payload("body_battery", [[0, None, 1792886400000], [None, None, 1792886460000]])
    source = source_for(payload)
    for _ in range(2):
        result = health_samples.normalize(database, day, "body_battery", payload, source)
        assert result == {"metric": "body_battery", "samples": 2, "valid_n": 1, "status": "available"}
    assert database.execute("SELECT count(*) FROM source_objects").fetchone()[0] == 1
    rows = database.execute("SELECT value,source_object_id FROM health_samples ORDER BY observed_at").fetchall()
    assert rows == [(0.0, source.source_object_id), (None, source.source_object_id)]
    revised = sample_payload("body_battery", [[None, None, 1792886400000]])
    newer = source_for(revised, "second")
    result = health_samples.normalize(database, day, "body_battery", revised, newer)
    assert result["status"] == "not_available"
    assert database.execute("SELECT value,source_object_id FROM health_samples").fetchall() == [(None, newer.source_object_id)]
    assert database.execute("SELECT status,source_object_id FROM health_sample_imports").fetchall() == [("not_available", newer.source_object_id)]
    assert database.execute("SELECT sha256 FROM source_objects WHERE source_object_id=?", [source.source_object_id]).fetchone()[0] == source.sha256
    assert database.execute("SELECT count(*) FROM source_objects").fetchone()[0] == 2


@pytest.mark.parametrize("day,utc_hours,local_times", [
    (date(2026, 10, 25), [0, 1], ["02:30 +0200", "02:30 +0100"]),
    (date(2026, 3, 29), [0, 1], ["01:30 +0100", "03:30 +0200"]),
])
def test_intraday_distinguishes_rome_dst_hours_without_interpolation(database, day, utc_hours, local_times):
    for hour, value in zip(utc_hours, [0, None]):
        database.execute("INSERT INTO health_samples VALUES (?,?,?,?,?,current_timestamp)",
                         [day, "body_battery", datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=30), value, "fixture"])
    report = intraday.report(database, day)
    series = next(s for s in report["series"] if s["metric"] == "body_battery")
    assert report["timezone"] == "Europe/Rome"
    assert [p["time"] for p in series["points"]] == local_times
    assert all(p["timestamp"].endswith("+00:00") for p in series["points"])
    assert [p["value"] for p in series["points"]] == [0, None]
    assert series["samples_n"] == 2 and series["valid_n"] == 1


def insert_swim(connection, identifier, day):
    connection.execute("""INSERT INTO activities(activity_id,start_time_utc,activity_date,sport,is_swim,
        environment,pool_length_m,device_id,distance_m,duration_s,source_object_id,imported_at)
        VALUES (?, ?, ?, 'lap_swimming',true,'pool',25,11,2400,2400,'synthetic-fixture',current_timestamp)""",
                       [identifier, day, day])


def save_validated(connection, kind, entry):
    return athlete_files.add_structured_entry(kind, training.validate_entry(kind, entry, connection))


def test_rescheduled_plan_links_on_revised_date_and_calendar_uses_that_day(database):
    old, new = date(2026, 10, 20), date(2026, 10, 22)
    insert_swim(database, 1, old)
    insert_swim(database, 2, new)
    plan = athlete_files.add_structured_entry("workouts", {"title": "Serie", "date": str(old), "total_m": 2300})
    save_validated(database, "plan-revisions", {"plan_id": plan["id"], "status": "planned", "date": str(new)})
    with pytest.raises(ValueError, match="stesso giorno"):
        training.validate_entry("plan-links", {"plan_id": plan["id"], "activity_id": 1}, database)
    save_validated(database, "plan-links", {"plan_id": plan["id"], "activity_id": 2})
    daily_status.build(database)
    result = calendar_view.build(database, old, new)
    assert not result["days"][0]["plans"]
    revised = result["days"][-1]["plans"][0]
    assert revised["original_date"] == str(old) and revised["date"] == str(new)
    assert revised["match_status"] == "completed" and revised["actual"]["activity_id"] == 2
    assert revised["delta_m"] == 100
    assert athlete_files.structured_entries("workouts")[0]["date"] == str(old)


def test_cancelling_rescheduled_plan_preserves_date_and_removes_planned_volume(database):
    old, new = date(2026, 10, 20), date(2026, 10, 22)
    plan = athlete_files.add_structured_entry("workouts", {"title": "Serie", "date": str(old), "total_m": 2300})
    save_validated(database, "plan-revisions", {"plan_id": plan["id"], "status": "planned", "date": str(new)})
    cancelled = save_validated(database, "plan-revisions", {"plan_id": plan["id"], "status": "cancelled"})
    assert cancelled["date"] == str(new)
    daily_status.build(database)
    result = calendar_view.build(database, old, new)
    assert result["days"][-1]["plans"][0]["match_status"] == "cancelled"
    assert result["weeks"][0]["planned_n"] == 0 and result["weeks"][0]["planned_m"] == 0
    insert_swim(database, 1, new)
    with pytest.raises(ValueError, match="Riattiva"):
        training.validate_entry("plan-links", {"plan_id": plan["id"], "activity_id": 1}, database)


def test_same_session_cannot_complete_two_active_plans(database):
    day = date(2026, 10, 20)
    insert_swim(database, 1, day)
    plans = [athlete_files.add_structured_entry("workouts", {"title": "Serie", "date": str(day), "total_m": 2400}) for _ in range(2)]
    before = training.workspace(database, day, day)
    assert all(p["match_status"] == "candidate" and p["actual"] is None for p in before["plans"])
    save_validated(database, "plan-links", {"plan_id": plans[0]["id"], "activity_id": 1})
    with pytest.raises(ValueError, match="già collegata"):
        training.validate_entry("plan-links", {"plan_id": plans[1]["id"], "activity_id": 1}, database)
    assert sum(p["match_status"] == "completed" for p in training.workspace(database, day, day)["plans"]) == 1


def insert_laps(connection):
    for index in [0, 1, 2, 3]:
        connection.execute("""INSERT INTO activity_laps(activity_id,lap_index,duration_s,distance_m,
            is_rest,source_object_id,imported_at) VALUES (1,?,100,100,false,'fixture',current_timestamp)""", [index])


def test_declared_series_reject_overlap_and_unrecorded_endpoints(database):
    insert_laps(database)
    with pytest.raises(ValueError, match="due gruppi"):
        session_annotations.validate_groups(database, 1, [{"first_lap": 0, "last_lap": 2}, {"first_lap": 2, "last_lap": 3}])
    for first, last in [(3, 1), (-1, 2), (0, 8)]:
        with pytest.raises(ValueError, match="lap registrato"):
            session_annotations.validate_groups(database, 1, [{"first_lap": first, "last_lap": last}])
    groups = session_annotations.validate_groups(database, 1, [{"first_lap": 0, "last_lap": 1}, {"first_lap": 2, "last_lap": 3}])
    assert all(g["source"] == "athlete_confirmed" for g in groups)


def test_declared_series_pace_uses_paired_distance_and_time_excluding_rests():
    annotation = {"sets": [{"label": "Serie", "first_lap": 0, "last_lap": 6}]}
    laps = [dict(lap_index=i, distance_m=distance, duration_s=duration, is_rest=rest)
            for i, (distance, duration, rest) in enumerate([
                (100, 80, False), (300, 300, False), (None, 50, False),
                (100, None, False), (0, 40, True), (25, 20, None), (0, 0, False)])]
    result = session_annotations.summarize(annotation, laps)[0]
    assert result["pace_100_s"] == pytest.approx(95)
    assert result["pace_n"] == 2
    assert result["distance_m"] == 500 and result["distance_n"] == 4
    assert result["active_s"] == 430 and result["time_n"] == 4
    assert result["rest_s"] == 40 and result["active_laps"] == 5 and result["lap_n"] == 7


def test_declared_series_with_only_missing_measurements_stays_missing():
    annotation = {"sets": [{"first_lap": 0, "last_lap": 0}]}
    result = session_annotations.summarize(annotation, [dict(lap_index=0, distance_m=None, duration_s=None, is_rest=False)])[0]
    assert result["distance_m"] is result["active_s"] is result["pace_100_s"] is None
    assert result["distance_n"] == result["time_n"] == result["pace_n"] == 0


def test_cold_and_upgraded_sample_schema_match_and_reapply_preserves_samples(monkeypatch):
    migrations = schema_migrations.discover()
    sample_migration = next(m for m in migrations if m.identifier.startswith("0019-"))
    with duckdb.connect(":memory:") as cold, duckdb.connect(":memory:") as upgraded:
        schema_migrations.apply(cold)
        monkeypatch.setattr(schema_migrations, "discover", lambda: [m for m in migrations if m.identifier < sample_migration.identifier])
        schema_migrations.apply(upgraded)
        assert upgraded.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='health_samples'").fetchone()[0] == 0
        monkeypatch.setattr(schema_migrations, "discover", lambda: migrations)
        assert sample_migration.identifier in schema_migrations.apply(upgraded)
        column_query = "SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='main' ORDER BY 1,ordinal_position"
        assert cold.execute(column_query).fetchall() == upgraded.execute(column_query).fetchall()
        payload = sample_payload("body_battery", [[0, None, 1792886400000]])
        health_samples.normalize(upgraded, date(2026, 10, 25), "body_battery", payload, source_for(payload))
        assert schema_migrations.apply(upgraded) == []
        assert upgraded.execute("SELECT metric,value FROM health_samples").fetchall() == [("body_battery", 0)]
        assert dict(upgraded.execute("SELECT migration_id,sha256 FROM schema_migrations").fetchall())[sample_migration.identifier] == sample_migration.sha256
        daily_status.build(upgraded)
        assert intraday.report(upgraded, "2026-10-25")["series"][1]["valid_n"] == 1


@pytest.fixture
def platform_client(database, monkeypatch):
    from contextlib import contextmanager
    from garmin_coach.app import platform, confirmation, security

    @contextmanager
    def read_synthetic_database():
        yield database

    monkeypatch.setattr(platform, "read", read_synthetic_database)
    monkeypatch.setattr(confirmation, "STORE", confirmation._Store())
    app = Starlette()
    platform.install(app)
    with TestClient(app) as client:
        yield client, {"origin": "http://127.0.0.1:8766", "x-csrf-token": security.TOKEN}


def test_calendar_api_revision_preview_is_bound_and_confirmation_idempotent(database, platform_client):
    client, headers = platform_client
    old, revised = "2026-10-20", "2026-10-22"
    plan = athlete_files.add_structured_entry("workouts", {"title": "Serie", "date": old, "total_m": 2400})
    body = {"kind": "plan-revisions", "plan_id": plan["id"], "status": "planned", "date": revised}
    assert client.post("/api/platform/memory", json=body).status_code == 403
    assert client.post("/api/platform/memory", json={**body, "confirm": True}, headers=headers).status_code == 403
    preview_response = client.post("/api/platform/memory", json=body, headers=headers)
    assert preview_response.status_code == 200
    token = preview_response.json()["preview_token"]
    assert not athlete_files.structured_entries("plan-revisions")
    confirm = {"kind": "plan-revisions", "confirm": True, "preview_token": token, "date": "2026-10-24", "status": "cancelled"}
    first = client.post("/api/platform/memory", json=confirm, headers=headers)
    assert first.status_code == 200
    assert first.json()["saved"]["date"] == revised and first.json()["saved"]["status"] == "planned"
    assert client.post("/api/platform/memory", json=confirm, headers=headers).json() == first.json()
    assert len(athlete_files.structured_entries("plan-revisions")) == 1
    daily_status.build(database)
    calendar = client.get("/api/platform/training", params={"start": old, "end": revised})
    assert calendar.status_code == 200
    assert calendar.json()["days"][0]["planned_n"] == 0
    assert calendar.json()["days"][-1]["plans"][0]["date"] == revised


def test_calendar_api_cannot_confirm_conflicting_link_from_older_preview(database, platform_client):
    client, headers = platform_client
    day = date(2026, 10, 20)
    insert_swim(database, 1, day)
    plans = [athlete_files.add_structured_entry("workouts", {"title": "Serie", "date": str(day), "total_m": 2400}) for _ in range(2)]
    previews = []
    for plan in plans:
        result = client.post("/api/platform/memory", json={"kind": "plan-links", "plan_id": plan["id"], "activity_id": 1}, headers=headers)
        assert result.status_code == 200
        previews.append(result.json()["preview_token"])
    first = client.post("/api/platform/memory", json={"kind": "plan-links", "confirm": True, "preview_token": previews[0]}, headers=headers)
    assert first.status_code == 200
    conflicting = client.post("/api/platform/memory", json={"kind": "plan-links", "confirm": True, "preview_token": previews[1]}, headers=headers)
    assert conflicting.status_code in (400, 409)
    assert len(athlete_files.current_structured_entries("plan-links", "plan_id")) == 1
