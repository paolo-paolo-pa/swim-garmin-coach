"""«Come sono cambiati battito e Body Battery durante quella giornata?»

Import on demand e replay locale. Sorgenti originali append-only, upsert su
giorno/metrica/istante e cache; non riscarica lo storico completo.
"""
from datetime import date,datetime,timedelta,timezone
import json
import math

from .. import database,rebuild
from . import source_catalog
from .personal_api import PersonalGarmin

METRICS={
    'heart_rate_bpm':('get_daily_heart_rate','heartRateValues','heartRateValueDescriptors','index','key','heartrate'),
    'body_battery':('get_daily_body_battery','bodyBatteryValuesArray','bodyBatteryValueDescriptorDTOList','bodyBatteryValueDescriptorIndex','bodyBatteryValueDescriptorKey','bodyBatteryLevel'),
}


def parse(payload,metric):
    _,values_key,descriptor_key,index_key,name_key,value_key=METRICS[metric]
    rows=payload if isinstance(payload,list) else [payload]
    samples={}
    for row in rows:
        if not isinstance(row,dict):continue
        descriptors={d.get(name_key):d.get(index_key) for d in row.get(descriptor_key,[]) if isinstance(d,dict)}
        ti,vi=descriptors.get('timestamp'),descriptors.get(value_key)
        if ti is None or vi is None:continue
        for values in row.get(values_key,[]) or []:
            if not isinstance(values,(list,tuple)) or len(values)<=max(ti,vi):continue
            timestamp,value=values[ti],values[vi]
            if not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp):continue
            try:observed=datetime.fromtimestamp(timestamp/1000,timezone.utc).replace(tzinfo=None)
            except (ValueError,OSError,OverflowError):continue
            valid=isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
            valid=valid and (value>0 if metric=='heart_rate_bpm' else 0<=value<=100)
            samples[observed]=float(value) if valid else None
    return sorted(samples.items())


def normalize(connection,day,metric,payload,source):
    source_catalog.register(connection,[source])
    samples=parse(payload,metric)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    # Uno snapshot corretto può togliere un campione. L'originale resta nel raw.
    connection.execute('DELETE FROM health_samples WHERE sample_date=? AND metric=?',[day,metric])
    if samples:
        connection.executemany('INSERT INTO health_samples VALUES (?,?,?,?,?,?)',
            [(day,metric,at,value,source.source_object_id,now) for at,value in samples])
    status='available' if any(value is not None for _,value in samples) else 'not_available'
    connection.execute('INSERT OR REPLACE INTO health_sample_imports VALUES (?,?,?,?,?)',
        [day,metric,now,status,source.source_object_id])
    return {'metric':metric,'samples':len(samples),'valid_n':sum(v is not None for _,v in samples),'status':status}


def pull(day,force=False,client=None):
    day=date.fromisoformat(str(day))
    if day>date.today():raise ValueError('Il giorno richiesto è nel futuro')
    results=[]
    with rebuild.single_writer('personal-api-health-samples'):
        with database.connect() as connection:
            owned=client is None
            try:
                for metric,(method,*_) in METRICS.items():
                    previous=connection.execute('SELECT fetched_at,status FROM health_sample_imports WHERE sample_date=? AND metric=?',[day,metric]).fetchone()
                    if previous and not force and (day<date.today()-timedelta(days=2) or datetime.now(timezone.utc).replace(tzinfo=None)-previous[0]<timedelta(hours=2)):
                        results.append({'metric':metric,'cached':True,'status':previous[1]});continue
                    if client is None:client=PersonalGarmin()
                    args=(str(day),) if metric=='heart_rate_bpm' else (str(day),str(day))
                    payload=client._call(method,*args)
                    source=source_catalog.capture(payload,'personal_'+method,str(day))
                    connection.execute('BEGIN')
                    try:
                        results.append(normalize(connection,day,metric,payload,source))
                        connection.execute('COMMIT')
                    except Exception:
                        connection.execute('ROLLBACK');raise
            finally:
                if owned and client is not None:client.close()
    return {'date':day,'results':results}


def replay(connection,day):
    """Ricalcola gli ultimi snapshot di un giorno, senza contattare Garmin."""
    result=[]
    for metric,(method,*_) in METRICS.items():
        files=sorted((source_catalog.RAW/str(day)).glob('personal_'+method+'*.json'),key=lambda p:p.stat().st_mtime)
        if files:
            path=files[-1]
            content=path.read_bytes()
            source=source_catalog.describe(content,'garmin_connect',path.relative_to(source_catalog.paths.ROOT).as_posix(),parser='health-samples',parser_version='1')
            result.append(normalize(connection,day,metric,json.loads(content),source))
    return result


def replay_all(connection):
    """Ricostruisce anche questi campioni da tutti i giorni catturati, senza rete."""
    results=[]
    for folder in sorted(source_catalog.RAW.iterdir()) if source_catalog.RAW.exists() else []:
        if not folder.is_dir():continue
        try:day=date.fromisoformat(folder.name)
        except ValueError:continue
        results.extend(replay(connection,day))
    return results
