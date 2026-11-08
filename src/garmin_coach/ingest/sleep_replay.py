"""Recupera punteggi sonno realmente presenti negli snapshot, senza rete.

Il parser e quello del sync, eseguito su un DB temporaneo in memoria. Sul
database dell'atleta viene aggiornato soltanto il punteggio mancante: fasi,
durate, registrazioni e fonti precedenti restano intatte. Il report registra
la fonte del singolo campo recuperato senza attribuirle gli altri campi.
"""
from datetime import datetime,timezone

import duckdb

from .. import paths
from ..database import SCHEMA
from .snapshot_replay import SnapshotClient
from . import sync,source_catalog


def audit(connection,client=None):
    client=client or SnapshotClient()
    candidates=[]
    for day, in connection.execute('SELECT sleep_date FROM sleep WHERE sleep_score IS NULL ORDER BY sleep_date').fetchall():
        payload=client.get_sleep_data(str(day)) or {}
        dto=payload.get('dailySleepDTO') or {}
        scores=dto.get('sleepScores') or {}
        value=scores.get('overallScore')
        if value is None:value=(scores.get('overall') or {}).get('value')
        if value is not None:
            candidates.append(day)
    return candidates


def replay_missing_scores(connection,client=None):
    client=client or SnapshotClient()
    candidates=audit(connection,client)
    recovered=[]
    skipped=[]
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with duckdb.connect(':memory:') as temporary:
        temporary.execute(SCHEMA)
        for day in candidates:
            report=sync.SyncReport()
            sync._pull_health(temporary,client,day,day,now,report)
            row=temporary.execute('SELECT sleep_score FROM sleep WHERE sleep_date=?',[day]).fetchone()
            path=client.source_path(str(day),'get_sleep_data')
            if not row or row[0] is None or not path:
                skipped.append({'date':str(day),'reason':'snapshot_non_normalizzabile','errors':report.errors+report.skipped})
                continue
            source=source_catalog.describe(path.read_bytes(),'garmin_connect',path.relative_to(paths.ROOT).as_posix(),parser='sync',parser_version='1')
            recovered.append({'date':str(day),'value':row[0],'source':source})
    connection.execute('BEGIN')
    try:
        for item in recovered:
            source_catalog.register(connection,[item['source']])
            connection.execute('UPDATE sleep SET sleep_score=? WHERE sleep_date=? AND sleep_score IS NULL',[item['value'],item['date']])
        connection.execute('COMMIT')
    except Exception:
        connection.execute('ROLLBACK');raise
    return {'candidates_n':len(candidates),'recovered_n':len(recovered),'skipped':skipped,
            'recovered':[{'date':r['date'],'source_object_id':r['source'].source_object_id,'sha256':r['source'].sha256} for r in recovered],
            'method':'existing-sync-parser-score-only-v1','network_used':False}
