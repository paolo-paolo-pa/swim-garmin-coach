"""Ricostruire un archivio non deve perdere i campioni acquisiti dopo l'export."""
from datetime import date

import duckdb

from garmin_coach import paths,rebuild
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import source_catalog,health_samples


def test_offline_replay_is_repeatable_and_sensor_timestamps_are_facts(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    monkeypatch.setattr(source_catalog,'RAW',tmp_path/'raw')
    payload={'heartRateValueDescriptors':[{'index':0,'key':'timestamp'},{'index':1,'key':'heartrate'}],
             'heartRateValues':[[1792886400000,50],[1792886520000,52]]}
    source_catalog.capture(payload,'personal_get_daily_heart_rate','2026-10-25')
    with duckdb.connect(':memory:') as c:
        c.execute(SCHEMA)
        first=health_samples.replay_all(c)
        assert first[0]['valid_n']==2
        before=rebuild.canonical_digest(c)
        health_samples.replay_all(c)
        assert c.execute('SELECT count(*) FROM health_samples').fetchone()[0]==2
        assert rebuild.canonical_digest(c)==before
        c.execute("UPDATE health_samples SET observed_at=observed_at+INTERVAL '1 second' WHERE value=50")
        assert rebuild.canonical_digest(c)!=before
