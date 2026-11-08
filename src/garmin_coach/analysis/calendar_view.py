"""«Come si distribuiscono sedute, piani e recupero nella mia settimana?»"""
from datetime import timedelta

from .training_workspace import workspace
from .dashboard import rows


def build(connection, start, end):
    data = workspace(connection, start, end)
    health = {str(r['status_date']): r for r in rows(connection,
        "SELECT status_date,hrv_ms,resting_hr_bpm,sleep_total_s FROM daily_status WHERE status_date BETWEEN ? AND ?", [start,end])}
    weeks, days = [], []
    day = start
    while day <= end:
        key = day.isoformat()
        activities = [a for a in data['activities'] if str(a['activity_date']) == key]
        plans = [p for p in data['plans'] if p['date'] == key]
        feedback = next((w for w in data['wellness'] if w['date'] == key), None)
        cards = [dict(id=str(a['activity_id']), source='completed', title=a['name'] or 'Attività Garmin',
            type='Piscina' if a['environment']=='pool' else 'Acque libere', distance_m=a['distance_m'],
            status='completed', activity_id=a['activity_id']) for a in activities]
        cards += [dict(id=p['id'], source='planned', title=p['title'],type='Piano',
            distance_m=p['total_m'], status='completed_plan' if p['match_status']=='completed' else p['match_status']) for p in plans]
        h = health.get(key,{})
        days.append(dict(date=key, activities=activities, plans=plans, cards=cards, wellness=feedback,
            hrv_ms=h.get('hrv_ms'),resting_hr_bpm=h.get('resting_hr_bpm'),
            sleep_hours=h['sleep_total_s']/3600 if h.get('sleep_total_s') is not None else None,
            planned_n=sum(p['match_status']!='cancelled' for p in plans), completed_n=len(activities)))
        day += timedelta(days=1)
    for offset in range(0,len(days),7):
        group = days[offset:offset+7]
        acts = [a for d in group for a in d['activities']]
        planned = [p for d in group for p in d['plans'] if p['match_status']!='cancelled']
        distances = [a['distance_m'] for a in acts if a['distance_m'] is not None]
        loads = [a['garmin_training_load'] for a in acts if a['garmin_training_load'] is not None]
        weeks.append(dict(start=group[0]['date'],end=group[-1]['date'],days=group,
            completed_n=len(acts),planned_n=len(planned),distance_m=sum(distances) if distances else None,
            distance_n=len(distances),planned_m=sum(p['total_m'] for p in planned),
            load=sum(loads) if loads else None,load_n=len(loads)))
    data.update(days=days,weeks=weeks)
    return data
