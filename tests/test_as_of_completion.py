"""Le gare future non possono migliorare un riferimento nel passato."""
from datetime import date

import duckdb

from garmin_coach.database import SCHEMA
from garmin_coach.analysis import critical_speed,race_history
from test_critical_speed import _gara
from test_monitoring_workspace import insert_swim


def test_future_races_do_not_leak_into_css_reference_or_latest_race():
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        _gara(c,'old400',date(2026,1,1),400,300)
        _gara(c,'old200',date(2026,1,1),200,140)
        _gara(c,'future400',date(2026,6,1),400,270)
        _gara(c,'future200',date(2026,6,1),200,125)
        cutoff=date(2026,2,1)
        assert critical_speed.current(c,until=cutoff).pace_100_s == 80
        assert race_history.last_race(c,cutoff)['day'] == date(2026,1,1)
        assert race_history.endurance_reference(c,until=cutoff).time_s == 300
        assert len(critical_speed.pairs(c,until=date(2025,12,31))) == 0


def test_provider_context_uses_anonymous_device_groups_and_local_source_mapping(tmp_path,monkeypatch):
    import json
    from garmin_coach import paths
    from garmin_coach.metrics import daily_status
    from garmin_coach.analysis.coaching_context import build
    monkeypatch.setattr(paths,'COACH',tmp_path)
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        insert_swim(c,987654321,date(2026,10,23),device=9876543210)
        daily_status.build(c)
        packet,sources=build(c,'Come e andata la seduta?',today=date(2026,10,26))
        sent=json.dumps(packet.as_dict(),default=str)
        assert '9876543210' not in sent
        assert '987654321' not in sent
        assert sources['swim_session_1']['activity_id']==987654321
