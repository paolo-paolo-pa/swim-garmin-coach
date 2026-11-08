"""Buchi espliciti, consultazione retrospettiva e periodi oltre l'anno."""
from datetime import date,timedelta

import duckdb
import pytest
from garmin_coach.database import SCHEMA
from garmin_coach.analysis import monitoring_history as history,dashboard
from garmin_coach.metrics.daily_status import build


@pytest.fixture
def connection():
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        yield c


def test_gaps_distinguish_edges_internal_absence_and_real_zero(connection):
    connection.execute("INSERT INTO daily_health(health_date,stress_avg,source_object_id,imported_at) VALUES ('2026-10-02',0,'fixture',current_timestamp),('2026-10-04',40,'fixture',current_timestamp),('2026-10-08',90,'fixture',current_timestamp)")
    start,end=date(2026,10,1),date(2026,10,5)
    series=[{'date':start+timedelta(days=i),'stress_avg':{1:0,3:40}.get(i)} for i in range(5)]
    r=history.coverage(connection,'stress_avg',series,start,end)
    assert r['samples']==2 and r['last']==date(2026,10,4)
    assert r['missing_n']==3
    assert [g['reason'] for g in r['gaps']]==['before_first','inside_history','after_last']


def test_old_weight_remains_dated_and_future_values_are_excluded(connection):
    connection.execute("INSERT INTO daily_health(health_date,resting_hr_bpm,source_object_id,imported_at) VALUES ('2026-10-01',45,'fixture',current_timestamp)")
    connection.execute("INSERT INTO body_metrics(measure_date,weight_kg,source_object_id,imported_at) VALUES ('2025-01-01',71,'fixture',current_timestamp),('2027-01-01',99,'fixture',current_timestamp)")
    build(connection)
    r=history.build(connection,{'days':'28','end':'2026-10-26'})
    weight=next(m for m in r['metrics'] if m['key']=='weight_kg')
    assert weight['value']==71 and weight['status']=='stale'
    assert weight['date']==date(2025,1,1)
    assert weight['n']==0 and weight['period_mean'] is None
    assert weight['availability']['samples']==1
    assert all(row['weight_kg'] is None for row in r['history']['rows'])
    assert history.interval(connection,{'days':'0','end':'2026-10-26'})[0]==date(2026,10,1)


def test_all_swim_history_includes_early_activities_and_conserves_distance(connection):
    connection.execute("INSERT INTO activities(activity_id,activity_date,start_time_utc,sport,is_swim,environment,distance_m,source_object_id,imported_at) VALUES (1,'2016-09-01','2016-09-01','lap_swimming',true,'pool',1000,'fixture',current_timestamp),(2,'2026-10-01','2026-10-01','lap_swimming',true,'pool',2000,'fixture',current_timestamp)")
    build(connection)
    r=dashboard.overview(connection,0,until=date(2026,10,26))
    assert r['start']==date(2016,9,1)
    assert r['volume_history']['resolution']=='month'
    assert sum(row['km'] for row in r['volume_history']['rows'] if row['km'] is not None)==r['summary']['distance_m']/1000==3
    assert any(row['km'] is None for row in r['volume_history']['rows'])
    r=dashboard.overview(connection,1825,until=date(2026,10,26),since=date(2026,10,1),resolution='week')
    assert r['days']==26 and r['summary']['distance_m']==2000
