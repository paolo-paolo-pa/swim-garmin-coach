"""«Come sto, quanto nuoto, e come è andata questa seduta?»

Contratto unico per Nuxt e strumenti locali. Nessuna metrica nel frontend.
Si leggono le viste canoniche che applicano già le correzioni dell'atleta.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from . import critical_speed, session_structure, swimming_time


def rows(connection, sql, args=()):
    result = connection.execute(sql, args)
    keys = [c[0] for c in result.description]
    return [dict(zip(keys, r)) for r in result.fetchall()]


def _technique_by_watch(laps):
    """SWOLF, cadenza e passo del libero, per lunghezza di vasca e **modello** di orologio.

    Il modello conta perché cambia ciò che l'orologio sa registrare (e il SWOLF non si
    confronta tra modelli); il singolo esemplare no. Il modello viene da
    ``coach/orologi.md`` per data: senza quella tabella i lap finiscono nel gruppo
    «Orologio non indicato», che il confronto numerico non usa.
    """
    from .. import athlete_files
    groups = {}
    labeler = athlete_files.WatchLabeler()
    for lap in laps:
        groups.setdefault((lap['pool_length_m'], labeler.label(lap['activity_date'], lap['device_id'])), []).append(lap)
    result = []
    for (pool, watch), items in groups.items():
        swolf = [i['swolf'] for i in items if i['swolf'] is not None]
        cadence = [i['avg_cadence_spm'] for i in items if i['avg_cadence_spm'] is not None]
        metres = sum(i['distance_m'] or 0 for i in items)
        result.append({'pool_length_m': pool, 'watch': watch, 'laps_n': len(items), 'swolf_n': len(swolf),
                       'swolf': sum(swolf) / len(swolf) if swolf else None,
                       'cadence': sum(cadence) / len(cadence) if cadence else None,
                       'pace_100_s': sum(i['duration_s'] or 0 for i in items) / metres * 100 if metres else None})
    return sorted(result, key=lambda r: -r['laps_n'])


COVERAGE_RADIUS_DAYS = 7


def _zero_on_covered_days(connection, swim_rows, first, last):
    """Un giorno senza nuotate è «0 km» quando l'orologio era in uso, non «dato mancante».

    Il volume è una somma di sedute registrate. Se nello stesso periodo esistono
    altri dati Garmin (salute, sonno, attività di altro sport), la mancanza di una
    nuotata è un fatto: l'atleta non ha nuotato. Resta invece un'interruzione il
    periodo senza alcun dato, perché lì non si può dire nulla. Un giorno è coperto
    se c'è un dato Garmin entro ``COVERAGE_RADIUS_DAYS`` giorni: un buco di una sola
    notte nei dati del polso non deve spezzare la serie.
    """
    observed = {r[0] for r in connection.execute("""
        SELECT health_date FROM daily_health UNION SELECT sleep_date FROM sleep
        UNION SELECT activity_date FROM activities""").fetchall() if r[0] is not None}
    swum = {r['date']: r for r in swim_rows}
    observed |= set(swum)
    if not observed:
        return swim_rows
    result = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        if day in swum:
            result.append(swum[day])
        elif any((day + timedelta(days=d)) in observed for d in range(-COVERAGE_RADIUS_DAYS, COVERAGE_RADIUS_DAYS + 1)):
            result.append({'date': day, 'km': 0.0})
    return result


def overview(connection, days=28, environment=None, until=None, since=None, resolution='auto'):
    until = until or date.today()
    start = since or ((connection.execute('SELECT min(swim_date) FROM counted_swims').fetchone()[0] or until) if days == 0 else until - timedelta(days=days - 1))
    if start>until or (until-start).days>20000:
        raise ValueError('Periodo non valido')
    filters = "activity_date BETWEEN ? AND ?"
    args = [start, until]
    if environment:
        filters += " AND environment = ?"
        args.append(environment)
    activities = rows(connection, f"""
        SELECT activity_id, activity_date, name, environment, distance_m,
               duration_s, moving_s, elapsed_s, avg_hr_bpm, avg_swolf,
               pool_length_m, avg_swim_cadence_spm, total_strokes,
               garmin_training_load, device_id,
               CASE WHEN distance_m>0 THEN duration_s/distance_m*100 END AS session_pace_s,
               (SELECT count(*) FROM activity_laps l WHERE l.activity_id=a.activity_id) AS laps_n
        FROM canonical_activities a WHERE is_swim AND {filters} ORDER BY activity_date DESC, activity_id DESC
    """, args)
    swim_filters = filters.replace('activity_date', 'swim_date')
    weekly = rows(connection, f"""
        SELECT CAST(date_trunc('week',swim_date) AS DATE) AS week,
               round(sum(distance_m)/1000,2) AS km, count(*) AS sessions,
               count(distance_m) AS distance_n
        FROM counted_swims WHERE {swim_filters} GROUP BY 1 ORDER BY 1
    """, args)
    from . import chart_series
    history_args=[start-timedelta(days=128),until]+([environment] if environment else [])
    daily_volume=rows(connection,f"""SELECT swim_date AS date,
        sum(distance_m)/1000 AS km FROM counted_swims
        WHERE swim_date BETWEEN ? AND ? {'AND environment = ?' if environment else ''}
        GROUP BY swim_date ORDER BY swim_date""",history_args)
    daily_volume=_zero_on_covered_days(connection,daily_volume,history_args[0],until)
    volume_history=chart_series.build(daily_volume,start,until,{'km':'sum'},resolution)
    health = rows(connection, """SELECT * FROM daily_status
        WHERE status_date BETWEEN ? AND ? ORDER BY status_date""", [start, until])
    latest_health = rows(connection, "SELECT * FROM daily_status WHERE status_date<=? ORDER BY status_date DESC LIMIT 1", [until])
    latest_metrics = {}
    for metric in ("hrv_ms", "sleep_total_s", "sleep_score"):
        samples = rows(connection, f"SELECT status_date AS date, {metric} AS value FROM daily_status WHERE status_date<=? AND {metric} IS NOT NULL ORDER BY status_date DESC LIMIT 1", [until])
        latest_metrics[metric] = samples[0] if samples else None
    summary = {"sessions": len(activities),
               "distance_m": sum(a["distance_m"] for a in activities if a["distance_m"] is not None) if any(a["distance_m"] is not None for a in activities) else None,
               "distance_n": sum(a["distance_m"] is not None for a in activities),
               "duration_s": sum(a["duration_s"] for a in activities if a["duration_s"] is not None) if any(a["duration_s"] is not None for a in activities) else None,
               "load_n": sum(a["garmin_training_load"] is not None for a in activities)}
    volume = rows(connection, f"SELECT sum(distance_m) AS distance_m, count(distance_m) AS distance_n, count(*) AS sessions FROM counted_swims WHERE {swim_filters}", args)[0]
    summary.update(volume)
    inventory = rows(connection, """SELECT count(*) AS activities, count(*) FILTER(WHERE is_swim) AS swims,
        min(activity_date) AS first_day, max(activity_date) AS last_day FROM activities""")[0]
    inventory["laps"] = connection.execute("SELECT count(*) FROM activity_laps").fetchone()[0]
    inventory["lengths"] = connection.execute("SELECT count(*) FROM pool_lengths").fetchone()[0]
    css = critical_speed.current(connection,until=until)
    technique_filters = filters.replace("activity_date", "a.activity_date").replace("environment", "a.environment")
    technique = _technique_by_watch(rows(connection, f"""
        SELECT a.activity_date, a.device_id, a.pool_length_m, l.duration_s, l.distance_m, l.swolf, l.avg_cadence_spm
        FROM canonical_activities a JOIN activity_laps l USING(activity_id)
        WHERE a.is_swim AND a.environment='pool' AND NOT l.is_rest
          AND l.stroke='freestyle' AND {technique_filters}
    """, args))
    return {"start": start, "end": until, "days": (until-start).days+1,
            "summary": summary, "activities": activities, "weekly": weekly, "volume_history":volume_history,
            "health": health, "latest_health": latest_health[0] if latest_health else None,
            "latest_metrics": latest_metrics,
            "inventory": inventory, "technique": technique,
            "css": asdict(css) | {"pace_100_s": css.pace_100_s} if css else None,
            "load_method": "Carico Garmin per attività; acuto 7 giorni e cronico 28 giorni dalla pipeline esistente. Nessuna conversione a TSS/CTL/ATL/TSB.",
            "pace_method": "Passo sessione = tempo registrato / distanza × 100: può comprendere recuperi. Il dettaglio FIT separa vasche attive e pause.",
            "technical_note": "Confrontare SWOLF e bracciate solo a parità di vasca, stile e modello di orologio. Il passo medio di seduta non misura da solo il miglioramento."}


def activity(connection, activity_id):
    from .. import athlete_files
    from .session_annotations import summarize
    from .open_water_segments import report as segments
    summary = rows(connection, "SELECT * FROM canonical_activities WHERE activity_id=?", [activity_id])
    if not summary:
        return None
    laps = rows(connection, "SELECT * FROM activity_laps WHERE activity_id=? ORDER BY lap_index", [activity_id])
    lengths = rows(connection, """SELECT *, CASE WHEN duration_s>0 AND is_active
         THEN duration_s/?*100 END AS pace_100_s
         FROM pool_lengths WHERE activity_id=? ORDER BY length_index""",
         [summary[0].get("pool_length_m"), activity_id])
    active_times=[r['duration_s'] for r in lengths if r['is_active'] is True and r['duration_s'] is not None]
    idle=[r for r in lengths if r['is_active'] is False]
    idle_times=[r['duration_s'] for r in idle if r['duration_s'] is not None]
    times = {"active_s": sum(active_times) if active_times else None,
             "active_duration_n":len(active_times),
             "rest_s": sum(idle_times) if idle_times else 0 if not idle else None,
             "rest_duration_n":len(idle_times),
             "rest_lengths":len(idle),
             "active_lengths": sum(bool(r["is_active"]) for r in lengths),
             "coverage_lengths": len(lengths)} if lengths else None
    if times and summary[0].get("pool_length_m"):
        times["active_distance_m"] = times["active_lengths"] * summary[0]["pool_length_m"]
        paired=[r for r in lengths if r['is_active'] is True and r['duration_s'] is not None and r['duration_s']>0]
        paired_distance=len(paired)*summary[0]['pool_length_m']
        times['pace_lengths_n']=len(paired)
        times["active_pace_100_s"] = sum(r['duration_s'] for r in paired)/paired_distance*100 if paired_distance else None
    # Coordinates intentionally omitted by the established privacy contract.
    track = rows(connection, """SELECT elapsed_s, distance_m, speed_ms, heart_rate_bpm
         FROM activity_track WHERE activity_id=? ORDER BY elapsed_s""", [activity_id])
    annotation=next((r for r in athlete_files.current_structured_entries('session-annotations','activity_id') if r['activity_id']==activity_id),None)
    return {"summary": summary[0], "laps": laps, "lengths": lengths, "times": times,
            "annotation":annotation,"manual_structure":summarize(annotation,laps),
            "open_water":segments(connection,activity_id) if summary[0]['environment']=='open_water' else None,
            "structure": session_structure.as_page_dict(connection, activity_id),
            "track": track,
            "gps_note": "Distanza e passo GPS in acqua possono contenere errori. Nessuna deduzione su correnti o condizioni ambientali."}
