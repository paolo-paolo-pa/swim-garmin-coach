"""«Come cambia il mio recupero, rispetto a me e al lavoro che ho fatto?»

Descrizione multidimensionale: nessun punteggio sanitario inventato.
Baseline mobile personale, copertura esplicita, associazioni non causali.
"""
from datetime import date, timedelta
import math
import statistics

from .dashboard import rows

METHOD = "personal-monitor-v1"
METRICS = {
    "hrv_ms": ("HRV notturna", "ms", 1),
    "resting_hr_bpm": ("FC a riposo", "bpm", -1),
    "sleep_hours": ("Durata del sonno", "h", 1),
    "sleep_score": ("Punteggio sonno Garmin", "/100", 1),
    "stress_avg": ("Stress medio Garmin", "/100", -1),
    "body_battery_max": ("Body Battery massimo", "/100", 1),
    "body_battery_min": ("Body Battery minimo", "/100", 1),
    "respiration_avg": ("Respirazione media", "atti/min", 0),
    "spo2_avg": ("SpO₂ media Garmin", "%", 0),
    "weight_kg": ("Peso", "kg", 0),
}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*q
    low = math.floor(index)
    return values[low] + (values[min(low+1, len(values)-1)]-values[low])*(index-low)


def metric_summary(series, key, start, end):
    label, unit, direction = METRICS[key]
    observed = [r for r in series if r["date"] <= end and finite(r.get(key))]
    period = [r[key] for r in observed if start <= r["date"]]
    current = observed[-1] if observed else None
    baseline = [r[key] for r in observed if current and current["date"]-timedelta(days=28) <= r["date"] < current["date"]]
    days = (end-start).days+1
    previous_start = start-timedelta(days=days)
    previous = [r[key] for r in observed if previous_start <= r["date"] < start]
    enough = len(baseline) >= 14
    low, high = (percentile(baseline, .1), percentile(baseline, .9)) if enough else (None,None)
    age = (end-current["date"]).days if current else None
    value = current[key] if current else None
    status = "missing" if current is None else "stale" if age > 2 else "available"
    position = "insufficient_data"
    if enough:
        position = "below_personal_range" if value < low else "above_personal_range" if value > high else "within_personal_range"
    current_mean = statistics.mean(period) if period else None
    previous_mean = statistics.mean(previous) if previous else None
    return {"key":key,"label":label,"unit":unit,"value":value,
        "date":current["date"] if current else None,"age_days":age,"status":status,
        "period_mean":current_mean,"previous_mean":previous_mean,
        "period_delta":current_mean-previous_mean if current_mean is not None and previous_mean is not None else None,
        "n":len(period),"expected_n":days,"coverage_pct":100*len(period)/days,
        "previous_n":len(previous),"baseline_n":len(baseline),
        "baseline":statistics.median(baseline) if enough else None,
        "baseline_low":low,"baseline_high":high,"position":position,
        "direction":direction,"method":METHOD,
        "note":"Fascia descrittiva 10°–90° percentile dei 28 giorni precedenti il campione; almeno 14 misure. Non è un intervallo clinico."}


def association(series, metric, start, end, lag=1):
    by_day = {r["date"]:r for r in series}
    pairs = []
    for day, row in by_day.items():
        if not start <= day <= end or not finite(row.get(metric)):
            continue
        earlier = by_day.get(day-timedelta(days=lag), {})
        # Un giorno senza attività non diventa uno zero di carico confermato.
        if earlier.get("load_n",0) < 1 or earlier.get("load_n") != earlier.get("activity_n"):
            continue
        pairs.append({"date":day,"load_date":day-timedelta(days=lag),"load":earlier["load"],"value":row[metric]})
    r = None
    if len(pairs) >= 14:
        xs, ys = [p["load"] for p in pairs], [p["value"] for p in pairs]
        if len(set(xs))>1 and len(set(ys))>1:
            r = statistics.correlation(xs,ys)
    return {"metric":metric,"lag_days":lag,"n":len(pairs),"pearson_r":r,
        "status":"available" if r is not None else "insufficient_data","pairs":pairs,
        "note":"Associazione esplorativa tra carico Garmin registrato e misura del giorno successivo. Richiede almeno 14 coppie complete; non prova causalità. Orario serale, sonno, lavoro e altri fattori possono incidere."}


def report(connection, start, end, include_context=False):
    if start > end or (end-start).days>20000:
        raise ValueError("Intervallo di monitoraggio non valido")
    lookback = min(start-timedelta(days=(end-start).days+1), start-timedelta(days=128 if include_context else 60))
    data = rows(connection,"""SELECT d.*, h.respiration_avg, h.spo2_avg, h.spo2_lowest,
        h.active_kcal,h.total_kcal,h.min_hr_bpm,h.max_hr_bpm,
        b.weight_kg, g.score AS readiness_score,g.recovery_time_h,s.light_s,s.awake_s
        FROM daily_status d LEFT JOIN daily_health h ON h.health_date=d.status_date
        LEFT JOIN body_metrics b ON b.measure_date=d.status_date
        LEFT JOIN garmin_readiness g ON g.readiness_date=d.status_date
        LEFT JOIN sleep s ON s.sleep_date=d.status_date
        WHERE d.status_date BETWEEN ? AND ? ORDER BY d.status_date""",[lookback,end])
    indexed = {r["status_date"]:r for r in data}
    loads = {r["date"]:r for r in rows(connection,"""SELECT activity_date AS date,
        count(*) AS activity_n,count(garmin_training_load) AS load_n,
        sum(garmin_training_load) AS load,count(*) FILTER(WHERE is_swim) AS swim_n,
        sum(distance_m) FILTER(WHERE is_swim) AS swim_m
        FROM canonical_activities WHERE activity_date BETWEEN ? AND ? GROUP BY 1""",[lookback,end])}
    series = []
    day = lookback
    while day<=end:
        row = dict(indexed.get(day,{}),date=day)
        row.update(loads.get(day,{"activity_n":0,"load_n":0,"load":None,"swim_n":0,"swim_m":None}))
        row["health_recorded"] = day in indexed
        row["sleep_hours"] = row["sleep_total_s"]/3600 if finite(row.get("sleep_total_s")) else None
        row["deep_hours"] = row["deep_s"]/3600 if finite(row.get("deep_s")) else None
        row["rem_hours"] = row["rem_s"]/3600 if finite(row.get("rem_s")) else None
        row["light_hours"] = row["light_s"]/3600 if finite(row.get("light_s")) else None
        row["awake_hours"] = row["awake_s"]/3600 if finite(row.get("awake_s")) else None
        for key in METRICS:
            if not finite(row.get(key)):
                row[key] = None
        # Baseline solo dal passato, mai contaminata dal giorno corrente.
        for key in ("hrv_ms","resting_hr_bpm","sleep_hours"):
            past=[r[key] for r in series[-28:] if finite(r.get(key))]
            row[key+"_baseline"] = statistics.median(past) if len(past)>=14 else None
        series.append(row)
        day+=timedelta(days=1)
    metrics=[metric_summary(series,k,start,end) for k in METRICS]
    notices=[]
    for m in metrics:
        if m["status"]=="stale":
            notices.append({"kind":"stale","text":f"{m['label']}: ultimo campione del {m['date']}; non descrive oggi.","metric":m["key"]})
        elif m["status"]=="available" and m["position"] in ("below_personal_range","above_personal_range"):
            notices.append({"kind":"observation","text":f"{m['label']}: valore {'sotto' if m['position'].startswith('below') else 'sopra'} la fascia personale recente.","metric":m["key"]})
    readiness=rows(connection,"SELECT readiness_date,score,level,recovery_time_h FROM garmin_readiness WHERE readiness_date<=? ORDER BY readiness_date DESC LIMIT 1",[end])
    sleep_row=next((r for r in reversed(series) if finite(r.get("sleep_total_s"))),None)
    stages=[]
    if sleep_row:
        stage_keys=[("deep_s","Profondo","#818cf8"),("rem_s","REM","#c084fc"),("light_s","Leggero","#38bdf8"),("awake_s","Sveglio","#71717a")]
        known=sum(sleep_row.get(key) or 0 for key,_,_ in stage_keys)
        stages=[{"label":label,"seconds":sleep_row.get(key),"minutes":sleep_row[key]/60 if finite(sleep_row.get(key)) else None,
                 "share":100*sleep_row[key]/known if finite(sleep_row.get(key)) and known>0 else None,"color":color} for key,label,color in stage_keys]
    return {"method":METHOD,"start":start,"end":end,"days":(end-start).days+1,
        **({"context_series":series} if include_context else {}),
        "series":[r for r in series if r["date"]>=start],"metrics":metrics,"notices":notices,
        "sleep_breakdown":{"date":sleep_row["date"] if sleep_row else None,"hours":sleep_row.get("sleep_hours") if sleep_row else None,
                           "score":sleep_row.get("sleep_score") if sleep_row else None,"stages":stages,
                           "note":"Quote delle fasi registrate, inclusa la veglia. Classificazione Garmin, non misurazione clinica."},
        "associations":[association(series,k,start,end) for k in ("hrv_ms","resting_hr_bpm","sleep_hours")],
        "readiness":{"last":readiness[0] if readiness else None,"availability":"not_exposed_by_personal_api",
                     "note":"Training Readiness non è esposto dalla Personal API; l'eventuale storico è datato e non viene ricalcolato."},
        "load_method":"Carico Garmin per attività. Serie acuta 7 giorni e cronica 28 giorni del motore esistente; nessuna conversione a TSS/CTL. Un'assenza di registrazioni non certifica riposo.",
        "interpretation":"Nessuna decisione di allenamento deriva da una sola misura. Confronta trend, sedute recenti e sensazioni; gli scostamenti descrivono dati, non diagnosi.",
        "sources":[{"label":"Garmin Personal API","url":"https://developer.garmin.com/gc-developer-program/personal/swagger-docs"},
                   {"label":"AIS · HRV best practice","url":"https://www.ausport.gov.au/ais/position_statements/heart-rate-variability"}]}
