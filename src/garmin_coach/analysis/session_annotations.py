"""«La serie era diversa: posso dichiarare io quali lap ne fanno parte?»"""
import math


def _lap_index(value):
    if type(value) is int:
        return value
    if isinstance(value,str) and value.strip().isdigit():
        try:
            return int(value)
        except ValueError:
            pass
    raise ValueError('Gli indici dei lap devono essere numeri interi registrati')


def _measured(value):
    return value is not None and math.isfinite(value) and value>=0


def validate_groups(connection,activity_id,groups):
    if not isinstance(groups,list) or len(groups)>60:
        raise ValueError('Sono consentiti al massimo 60 gruppi di lap')
    valid={r[0] for r in connection.execute('SELECT lap_index FROM activity_laps WHERE activity_id=?',[activity_id]).fetchall()}
    used=set()
    result=[]
    for group in groups:
        if not isinstance(group,dict) or 'first_lap' not in group or 'last_lap' not in group:
            raise ValueError('Ogni gruppo richiede primo e ultimo lap registrato')
        first,last=_lap_index(group['first_lap']),_lap_index(group['last_lap'])
        if first not in valid or last not in valid or first>last:
            raise ValueError('Ogni gruppo deve iniziare e finire su un lap registrato della seduta')
        included={i for i in valid if first<=i<=last}
        if included&used:
            raise ValueError('Uno stesso lap non può appartenere a due gruppi dichiarati')
        used|=included
        result.append({'label':str(group.get('label','Serie dichiarata'))[:120],
                       'first_lap':first,'last_lap':last,'source':'athlete_confirmed'})
    return result


def summarize(annotation,laps):
    summaries=[]
    for group in (annotation or {}).get('sets',[]):
        selected=[l for l in laps if group['first_lap']<=l['lap_index']<=group['last_lap']]
        active=[l for l in selected if l['is_rest'] is False]
        rest_laps=[l for l in selected if l['is_rest'] is True]
        rest=[l for l in rest_laps if _measured(l['duration_s'])]
        distances=[l['distance_m'] for l in active if _measured(l['distance_m'])]
        times=[l['duration_s'] for l in active if _measured(l['duration_s'])]
        paired=[l for l in active if _measured(l['distance_m']) and l['distance_m']>0
                and _measured(l['duration_s']) and l['duration_s']>0]
        summaries.append(dict(group,lap_n=len(selected),active_laps=len(active),
            rest_laps=len(rest_laps),rest_n=len(rest),
            unknown_laps=sum(l['is_rest'] is None for l in selected),
            distance_m=sum(distances) if distances else None,distance_n=len(distances),
            active_s=sum(times) if times else None,time_n=len(times),
            rest_s=sum(l['duration_s'] for l in rest) if rest else None,
            pace_100_s=sum(l['duration_s'] for l in paired)/sum(l['distance_m'] for l in paired)*100 if paired else None,
            pace_n=len(paired)))
    return summaries
