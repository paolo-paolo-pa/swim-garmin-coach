"""Recupera soltanto punteggi mancanti dagli snapshot locali, con backup."""
import json
import shutil
from datetime import datetime

import duckdb
from garmin_coach import paths
from garmin_coach.rebuild import single_writer
from garmin_coach.ingest.sleep_replay import replay_missing_scores
from garmin_coach.metrics.daily_status import build

with single_writer('sleep-score-recovery'):
    backup=paths.DATA/'backups'/datetime.now().strftime('sleep-recovery-%Y%m%d-%H%M%S')
    backup.mkdir(parents=True)
    # Aprire e chiudere lo scrittore completa l'eventuale WAL prima della copia.
    with duckdb.connect(str(paths.DATABASE)) as connection:
        connection.execute('CHECKPOINT')
    shutil.copy2(paths.DATABASE,backup/paths.DATABASE.name)
    with duckdb.connect(str(paths.DATABASE)) as connection:
        before=connection.execute('SELECT count(sleep_score) FROM sleep').fetchone()[0]
        result=replay_missing_scores(connection)
        build(connection)
        after=connection.execute('SELECT count(sleep_score) FROM sleep').fetchone()[0]
        result.update(before=before,after=after,backup=str(backup))
    (paths.DATA/'sleep-score-recovery.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='recovered'},indent=2))
