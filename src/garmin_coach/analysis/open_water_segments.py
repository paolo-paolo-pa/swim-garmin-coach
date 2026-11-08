"""«Come ho distribuito il ritmo in mare, e quanto regge il GPS?»"""
import statistics

from .dashboard import rows


def report(connection,activity_id):
    quality=rows(connection,"""SELECT points,gps_points,gps_coverage,gps_distance_m,
        device_distance_m,distance_gap,median_interval_s,has_heart_rate,segments_ok,gate_reason
        FROM activity_track_quality WHERE activity_id=?""",[activity_id])
    points=rows(connection,'SELECT elapsed_s,distance_m,heart_rate_bpm FROM activity_track WHERE activity_id=? AND elapsed_s IS NOT NULL ORDER BY elapsed_s,point_index',[activity_id])
    groups={}
    for point in points:
        groups.setdefault(int(point['elapsed_s']//300),[]).append(point)
    segments=[]
    distances=[p['distance_m'] for p in points if p['distance_m'] is not None]
    # Anche un reset esattamente fra due finestre invalida il cumulativo.
    distance_monotonic=(all(b>=a for a,b in zip(distances,distances[1:]))
                        if len(distances)>1 else None)
    valid=bool(quality and quality[0]['segments_ok'] and distance_monotonic)
    for index,group in sorted(groups.items()):
        duration=group[-1]['elapsed_s']-group[0]['elapsed_s']
        distance_points=[p for p in group if p['distance_m'] is not None]
        distance=distance_points[-1]['distance_m']-distance_points[0]['distance_m'] if len(distance_points)>1 else None
        # Con distanza assente, non monotona o gate negativo nessun passo.
        monotonic=all(b['distance_m']>=a['distance_m'] for a,b in zip(distance_points,distance_points[1:]))
        elapsed=distance_points[-1]['elapsed_s']-distance_points[0]['elapsed_s'] if len(distance_points)>1 else None
        pace=elapsed/distance*100 if valid and monotonic and distance and distance>0 and elapsed and elapsed>0 else None
        hr=[p['heart_rate_bpm'] for p in group if p['heart_rate_bpm'] is not None]
        segments.append({'label':f'{index*5}–{(index+1)*5} min','start_s':group[0]['elapsed_s'],
            'end_s':group[-1]['elapsed_s'],'observed_s':duration,'distance_m':distance if monotonic else None,
            'pace_100_s':pace,'hr_bpm':statistics.mean(hr) if hr else None,'hr_n':len(hr),
            'distance_observed_s':elapsed,
            'distance_n':len(distance_points),'points_n':len(group)})
    return {'quality':quality[0] if quality else None,'segments':segments,
        'distance_monotonic':distance_monotonic,'method':'observed-five-minute-windows-v2',
        'note':'Finestre temporali di cinque minuti: distanza e passo fra il primo e l’ultimo campione con distanza disponibile, usando i loro istanti e senza interpolare ai bordi. Il passo è mostrato solo quando il controllo GPS dell’intera registrazione passa e la distanza cumulativa non arretra, anche fra finestre. Il controllo globale non certifica ogni singola finestra. La FC è una media dei campioni disponibili. Nessuna deduzione su correnti, temperatura o sostenibilità futura del ritmo.'}
