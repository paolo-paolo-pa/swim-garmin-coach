"""Controlli su confronti onesti, baseline retrospettive e intenzioni confermate."""
from datetime import date, timedelta

import duckdb
import pytest

from garmin_coach import athlete_files, paths
from garmin_coach.database import SCHEMA
from garmin_coach.analysis import health_monitor as health, swim_comparison, training_workspace as training


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "COACH", tmp_path / "athlete")
    c = duckdb.connect(":memory:")
    c.execute(SCHEMA)
    yield c
    c.close()


def insert_swim(c, identifier, day, paces=(90,), device=11, pool=25, stroke="freestyle", meters=100):
    c.execute("""INSERT INTO activities(activity_id,start_time_utc,activity_date,sport,is_swim,
        environment,pool_length_m,device_id,distance_m,duration_s,source_object_id,imported_at)
        VALUES (?, ?, ?, 'lap_swimming',true,'pool',?,?,2400,2400,'synthetic-fixture',current_timestamp)""",
        [identifier,day,day,pool,device])
    for i, pace in enumerate(paces):
        c.execute("""INSERT INTO activity_laps(activity_id,lap_index,duration_s,distance_m,
            stroke,pace_per_100m_s,swolf,is_rest,source_object_id,imported_at)
            VALUES (?,?,?,?,?,?,40,false,'synthetic-fixture',current_timestamp)""",
            [identifier,i,pace*meters/100,meters,stroke,pace])


def test_baseline_never_uses_current_or_future_measurements():
    day = date(2026,10,26)
    series=[{"date":day-timedelta(days=i),"hrv_ms":40} for i in range(28,0,-1)]
    series += [{"date":day,"hrv_ms":1000},{"date":day+timedelta(days=1),"hrv_ms":9999}]
    result=health.metric_summary(series,"hrv_ms",day,day)
    assert result["baseline"] == 40
    assert result["baseline_n"] == 28
    assert result["value"] == 1000
    assert result["n"] == result["expected_n"] == 1


def test_missing_and_stale_are_distinct_from_a_fresh_zero():
    day=date(2026,10,26)
    assert health.metric_summary([],"stress_avg",day,day)["status"] == "missing"
    stale=health.metric_summary([{"date":day-timedelta(days=3),"stress_avg":0}],"stress_avg",day,day)
    assert stale["status"] == "stale"
    assert stale["value"] == 0 and stale["n"] == 0
    fresh=health.metric_summary([{"date":day,"stress_avg":0}],"stress_avg",day,day)
    assert fresh["status"] == "available" and fresh["n"] == 1


def test_sparse_baseline_does_not_create_personal_range():
    day=date(2026,10,26)
    values=[{"date":day-timedelta(days=i),"hrv_ms":40} for i in range(14)]
    result=health.metric_summary(values[::-1],"hrv_ms",day-timedelta(days=27),day)
    assert result["baseline_n"] == 13
    assert result["baseline"] is None
    assert result["position"] == "insufficient_data"
    assert result["coverage_pct"] == 50


def test_lag_pairing_excludes_partial_load_and_unknown_rest():
    day=date(2026,10,1)
    series=[{"date":day+timedelta(days=i),"hrv_ms":40+i,"load":100+i,
             "load_n":1,"activity_n":1} for i in range(16)]
    r=health.association(series,"hrv_ms",day,day+timedelta(days=15))
    assert r["n"] == 15 and r["pearson_r"] == pytest.approx(1)
    series[0]["activity_n"]=2
    series[1].update(load_n=0,activity_n=0,load=None)
    r=health.association(series,"hrv_ms",day,day+timedelta(days=15))
    assert r["n"] == 13 and r["pearson_r"] is None


def test_comparison_uses_session_not_lap_as_statistical_unit(database):
    start,end=date(2026,10,1),date(2026,10,28)
    for i in range(4):
        insert_swim(database,i+1,start+timedelta(days=i),(100,)*50 if i==0 else (80,))
        insert_swim(database,i+11,start+timedelta(days=15+i),(85,))
    r=swim_comparison.compare(database,start,end)
    group=r["comparisons"][0]
    assert group["before_n"] == group["after_n"] == 4
    assert group["before_pace"] == 80
    assert group["delta_s"] == 5


def test_comparison_filters_and_never_merges_devices(database):
    start,end=date(2026,10,1),date(2026,10,28)
    insert_swim(database,1,start,device=11)
    insert_swim(database,2,start,device=22)
    insert_swim(database,3,start,pool=50)
    insert_swim(database,4,start,stroke="breaststroke")
    insert_swim(database,5,start,meters=200)
    r=swim_comparison.compare(database,start,end)
    assert r["session_n"] == 2
    assert len(r["comparisons"]) == 2
    assert all(g["delta_s"] is None for g in r["comparisons"])
    assert swim_comparison.compare(database,start,end,device=22)["session_n"] == 1


def test_quality_exclusions_are_respected(database):
    day=date(2026,10,1)
    insert_swim(database,1,day)
    database.execute("INSERT INTO activity_quality(activity_id,status,scope,reason,confirmed_on,decided_by,applied_at) VALUES (1,'exclude','all','athlete decision',?, 'athlete',current_timestamp)",[day])
    assert swim_comparison.compare(database,day,day)["session_n"] == 0


def test_block_is_atomic_and_revisions_leave_original_readable(database):
    block=athlete_files.add_structured_entry("training-blocks",{"title":"Fixture", "sessions":[{"date":"2026-10-01","total_m":2400},{"date":"2026-10-02","total_m":2400}]})
    assert len(list((paths.COACH/"training-blocks").glob("*.md"))) == 1
    plans=athlete_files.structured_entries("workouts")
    assert len(plans) == 2 and all(p["block_id"] == block["id"] for p in plans)
    for value in (3,8):
        athlete_files.add_structured_entry("wellness",{"date":"2026-10-01","fatigue":value})
    assert len(athlete_files.structured_entries("wellness")) == 2
    assert athlete_files.current_structured_entries("wellness","date")[0]["fatigue"] == 8


def test_calendar_does_not_claim_ambiguous_activity_completed(database):
    day=date(2026,10,1)
    for i in (1,2): insert_swim(database,i,day)
    plan=athlete_files.add_structured_entry("workouts",{"date":str(day),"total_m":2400})
    assert training.workspace(database,day,day)["plans"][0]["match_status"] == "ambiguous"
    valid=training.validate_entry("plan-links",{"plan_id":plan["id"],"activity_id":2},database)
    athlete_files.add_structured_entry("plan-links",valid)
    result=training.workspace(database,day,day)["plans"][0]
    assert result["match_status"] == "completed" and result["actual"]["activity_id"] == 2


@pytest.mark.parametrize("value",[-1,11,True,"invalid"])
def test_subjective_scores_reject_invalid_values(value):
    with pytest.raises(ValueError):
        training.validate_entry("wellness",{"date":"2026-10-01","fatigue":value})


def test_proposal_does_not_replace_unknown_recent_volume(database):
    with pytest.raises(ValueError,match="quattro sedute"):
        training.propose(database,{"start":"2026-10-26","weekdays":[0,2,4]},today=date(2026,10,26))


def test_proposal_stays_within_recent_volume_and_availability(database):
    from garmin_coach.metrics import daily_status
    today=date(2026,10,26)
    for i in range(8):insert_swim(database,i+1,today-timedelta(days=i*3+1))
    daily_status.build(database)
    r=training.propose(database,{"start":str(today),"weeks":2,"weekdays":[0,2,4],"max_minutes":60},today=today)
    assert len(r["sessions"]) == 6
    assert r["total_m"]/2 <= r["weekly_reference_m"]
    assert all(date.fromisoformat(s["date"]).weekday() in [0,2,4] for s in r["sessions"])
    assert athlete_files.structured_entries("workouts") == []
