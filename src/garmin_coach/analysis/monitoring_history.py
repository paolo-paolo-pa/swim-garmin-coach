"""«Perche vedo un buco, e qual e il trend su un anno o piu?»"""
from datetime import date,timedelta

from . import health_monitor,chart_series
from .dashboard import rows
from .periods import parse


FIELDS={**{k:'mean' for k in health_monitor.METRICS},
    **{k:'mean' for k in ('deep_hours','rem_hours','light_hours','awake_hours','spo2_lowest',
        'hrv_ms_baseline','resting_hr_bpm_baseline','sleep_hours_baseline','load_acute_7','load_chronic_28')},
    'load':'sum','steps':'sum'}
SOURCES={
    'hrv_ms':('health_status','status_date','hrv_ms'),
    'resting_hr_bpm':('daily_health','health_date','resting_hr_bpm'),
    'sleep_hours':('sleep','sleep_date','total_sleep_s'),
    'sleep_score':('sleep','sleep_date','sleep_score'),
    'weight_kg':('body_metrics','measure_date','weight_kg'),
    **{k:('daily_health','health_date',k) for k in ('stress_avg','body_battery_min','body_battery_max','respiration_avg','spo2_avg')},
}
GAP_LABELS={'before_first':'Prima della prima misura disponibile',
    'after_last':'Oltre l’ultima misura acquisita',
    'inside_history':'Misura mancante nello storico acquisito',
    'never_available':'Misura non presente nei dati acquisiti'}


def interval(connection,params):
    options=dict(params)
    if int(options.get('days',28))==0 and not options.get('start'):
        first=connection.execute('SELECT min(health_date) FROM daily_health').fetchone()[0]
        options['start']=str(first or date.today())
    return parse(options)


def coverage(connection,metric,series,start,end):
    table,day,column=SOURCES[metric]
    item=rows(connection,f'SELECT min({day}) AS first,max({day}) AS last,count(*) AS samples FROM {table} WHERE {column} IS NOT NULL AND {day}<=?',[end])[0]
    gaps=[]
    for row in series:
        day_value=row['date']
        if not start<=day_value<=end or health_monitor.finite(row.get(metric)):continue
        reason='never_available' if item['first'] is None else 'before_first' if day_value<item['first'] else 'after_last' if day_value>item['last'] else 'inside_history'
        if gaps and gaps[-1]['reason']==reason and gaps[-1]['end']+timedelta(days=1)==day_value:
            gaps[-1]['end']=day_value;gaps[-1]['days']+=1
        else:gaps.append({'start':day_value,'end':day_value,'days':1,'reason':reason,'label':GAP_LABELS[reason]})
    return dict(item,gaps=gaps,missing_n=sum(g['days'] for g in gaps),
        note='La mancanza nel database non prova che il dispositivo non abbia misurato: distingue la copertura acquisita, senza stimare i valori mancanti.')


def build(connection,params):
    start,end=interval(connection,params)
    data=health_monitor.report(connection,start,end,include_context=True)
    context=data.pop('context_series')
    data['history']=chart_series.build(context,start,end,FIELDS,params.get('resolution','auto'))
    for metric in data['metrics']:
        info=coverage(connection,metric['key'],data['series'],start,end)
        metric['availability']=info
        # Un peso vecchio non deve sembrare una misura mai esistita.
        if metric['value'] is None and info['last']:
            table,day,column=SOURCES[metric['key']]
            value=connection.execute(f'SELECT {column} FROM {table} WHERE {day}=?',[info['last']]).fetchone()[0]
            if metric['key']=='sleep_hours':value/=3600
            metric.update(value=value,date=info['last'],age_days=(end-info['last']).days,status='stale')
    data['coverage_note']='I tratti interrotti sono misure non disponibili. Il trend riassume solo dati osservati e non riempie periodi interamente privi di campioni.'
    data['first_available']=connection.execute('SELECT min(health_date) FROM daily_health').fetchone()[0]
    return data
