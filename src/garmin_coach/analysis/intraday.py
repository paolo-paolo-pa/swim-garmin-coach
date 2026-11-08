"""Profili del giorno: campioni osservati, mai una continuità inventata."""
from datetime import date,timezone
from zoneinfo import ZoneInfo

from .dashboard import rows


def report(connection,day):
    day=date.fromisoformat(str(day))
    results=[]
    for metric,label,unit in [('heart_rate_bpm','Frequenza cardiaca','bpm'),('body_battery','Body Battery','/100')]:
        data=rows(connection,'SELECT observed_at,value FROM health_samples WHERE sample_date=? AND metric=? ORDER BY observed_at',[day,metric])
        points=[{'timestamp':r['observed_at'].replace(tzinfo=timezone.utc).isoformat(),
                 'time':r['observed_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Rome')).strftime('%H:%M %z'),
                 'value':r['value']} for r in data]
        imports=rows(connection,'SELECT fetched_at,status FROM health_sample_imports WHERE sample_date=? AND metric=?',[day,metric])
        results.append({'metric':metric,'label':label,'unit':unit,'points':points,'samples_n':len(points),
                        'valid_n':sum(p['value'] is not None for p in points),'import':imports[0] if imports else None})
    return {'date':day,'timezone':'Europe/Rome','series':results,
            'note':'Solo campioni Garmin effettivamente disponibili. Frequenze di campionamento diverse, dati mancanti non interpolati. Lo stress della Personal API è un aggregato giornaliero; nessun profilo orario inventato.'}
