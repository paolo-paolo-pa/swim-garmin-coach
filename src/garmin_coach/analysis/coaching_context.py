"""«Cosa dicono insieme il mio nuoto, il recupero e il programma?»

Adatta servizi deterministici al contratto del coach. I riferimenti Garmin
restano nella mappa locale; al provider arrivano alias e metriche calcolate.
"""
from datetime import date,timedelta

from .. import coach,athlete_files
from ..coach.contract import Fact
from . import health_monitor,swim_comparison,training_workspace,volume


def build(connection,question,today=None):
    today=today or date.today()
    packet=coach.build(connection,question,today=today)
    first=today-timedelta(days=41)
    monitoring=health_monitor.report(connection,first,today)
    sources={}
    for m in monitoring['metrics']:
        packet.add(Fact('monitor_'+m['key'],m['label'],m['value'],m['unit'],
            str(m['value']) if m['value'] is not None else 'Non disponibile',
            str(m['date']) if m['date'] else str(today),availability=m['status'],
            n=m['n'],expected_n=m['expected_n'],why=m['note']))
        packet.add(Fact('baseline_'+m['key'],'Baseline personale: '+m['label'],m['baseline'],m['unit'],
            str(m['baseline']) if m['baseline'] is not None else 'Baseline insufficiente',
            '28 giorni precedenti il campione '+str(m['date']),
            availability='available' if m['baseline'] is not None else 'insufficient_data',n=m['baseline_n'],expected_n=28))
    packet.recovery['monitoring']={'metrics':monitoring['metrics'],'associations':monitoring['associations']}
    # Le associazioni usano soltanto coppie giornaliere, senza dettagli originali.
    packet.recovery['monitoring']['associations']=[{k:v for k,v in a.items() if k!='pairs'} for a in monitoring['associations']]
    weekly=[]
    for i in range(6):
        start=first+timedelta(days=7*i)
        end=start+timedelta(days=6)
        v=volume.of_period(connection,start,end)
        known=connection.execute('SELECT count(distance_m) FROM counted_swims WHERE swim_date BETWEEN ? AND ?',[start,end]).fetchone()[0]
        value=v.distance_m if known else None
        entry=dict(start=str(start),end=str(end),distance_m=value,sessions=v.sessions,distance_n=known)
        weekly.append(entry)
        packet.add(Fact('week_'+str(i+1),'Volume di nuoto registrato',value,'m',str(value) if value is not None else 'Non disponibile',
            str(start)+' → '+str(end),availability='available' if known else 'missing',n=known,expected_n=v.sessions))
    packet.training['six_weeks']=weekly
    comparison=swim_comparison.compare(connection,first,today)
    device_groups={device:'gruppo '+chr(65+i) for i,device in enumerate(dict.fromkeys(s['device_id'] for s in comparison['sessions']))}
    for i,s in enumerate(comparison['sessions'][-5:]):
        alias='swim_session_'+str(i+1)
        packet.add(Fact(alias,'Lap 100 m stile libero · vasca 25 m',s['median_pace'],'s/100 m',
            str(s['median_pace']),str(s['date']),n=s['laps_n'],expected_n=s['laps_n'],
            why='Mediana dei lap corrispondenti. Dispositivo '+(device_groups[s['device_id']] if s['device_id'] is not None else 'non noto')+'; non classifica la seduta come soglia.'))
        sources[alias]={'activity_id':s['activity_id'],'date':str(s['date']),'label':'Lap 100 m stile libero'}
    preferences=training_workspace.settings()
    packet.training['preferences']={k:preferences.get(k) for k in ('weekdays','max_minutes','goal','race_date','race_name','race_distance_m','environment','confirmed')}
    calendar=training_workspace.workspace(connection,today,today+timedelta(days=28))
    packet.training['confirmed_plans']=[{k:p.get(k) for k in ('date','title','total_m','blocks','goal')}
        for p in calendar['plans'] if p['match_status']!='cancelled']
    packet.recovery['subjective_feedback']=[{k:p.get(k) for k in ('date','fatigue','soreness','recovery','motivation','sleep_quality','rpe','notes')}
        for p in athlete_files.current_structured_entries('wellness','date') if str(first)<=p['date']<=str(today)]
    if preferences.get('goal'):
        packet.goal['athlete_declared_goal']=preferences['goal']
    packet.limitations.extend(comparison['limits'])
    packet.limitations.append('Lap 100 m non significa allenamento di soglia. Nessuna causalità fra carico, sonno e HRV; nessun punteggio clinico.')
    return packet,sources
