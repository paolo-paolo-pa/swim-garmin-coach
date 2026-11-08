import json
from datetime import date,datetime

import duckdb
import pytest

from garmin_coach import paths
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import health,sleep_replay
from garmin_coach.ingest.snapshot_replay import SnapshotClient


@pytest.mark.parametrize('score',[0,83])
def test_raw_score_is_recovered_without_overwriting_sleep_fields(tmp_path,monkeypatch,score):
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    folder=tmp_path/'raw'/'2026-10-01';folder.mkdir(parents=True)
    (folder/'get_sleep_data.json').write_text(json.dumps({'dailySleepDTO':{'sleepTimeSeconds':25000,'deepSleepSeconds':4000,'sleepScores':{'overall':{'value':score}}}}))
    (folder/'get_user_summary.json').write_text(json.dumps({'restingHeartRate':50}))
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        c.execute("INSERT INTO sleep(sleep_date,total_sleep_s,deep_s,source_object_id,imported_at) VALUES ('2026-10-01',27000,6000,'original',?)",[datetime(2026,10,1)])
        result=sleep_replay.replay_missing_scores(c,SnapshotClient(tmp_path/'raw'))
        assert result['recovered_n']==1 and result['network_used'] is False
        assert c.execute('SELECT total_sleep_s,deep_s,sleep_score,source_object_id FROM sleep').fetchone()==(27000,6000,score,'original')
        assert c.execute('SELECT count(*) FROM activities').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM source_objects WHERE source_object_id=?',[result['recovered'][0]['source_object_id']]).fetchone()[0]==1
        assert sleep_replay.replay_missing_scores(c,SnapshotClient(tmp_path/'raw'))['recovered_n']==0


def test_no_score_is_created_when_source_has_none(tmp_path):
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        c.execute("INSERT INTO sleep(sleep_date,total_sleep_s,source_object_id,imported_at) VALUES ('2026-10-01',27000,'original',current_timestamp)")
        assert sleep_replay.replay_missing_scores(c,SnapshotClient(tmp_path))['recovered_n']==0
        assert c.execute('SELECT sleep_score FROM sleep').fetchone()[0] is None


def test_export_parser_supports_nested_score_for_future_rebuilds():
    row=health._sleep_rows({'calendarDate':'2026-10-01','sleepScores':{'overall':{'value':84}}})
    assert row[9]==84
