"""«A parità di distanza, stile, vasca e modello di orologio, cosa cambia?»

L'unità statistica è la seduta, non il numero di lap. Nessun verdetto di
miglioramento indipendente da intensità, attrezzi e intenzione del lavoro.
"""
from datetime import timedelta
import statistics

from .dashboard import rows
from .. import athlete_files


def compare(connection,start,end,stroke="freestyle",distance=100,pool=25,device=None):
    if stroke not in ("freestyle","backstroke","breaststroke","butterfly","mixed","drill") or distance not in (25,50,100,200,300,400,500,800,1000,1500) or pool not in (25,50):
        raise ValueError("Filtro tecnico non valido")
    params=[start,end,stroke,distance,pool]
    extra=""
    if device:
        extra=" AND a.device_id=?"
        params.append(int(device))
    data=rows(connection,f"""SELECT a.activity_id,a.activity_date,a.name,a.device_id,a.pool_length_m,
        l.lap_index,l.duration_s,l.distance_m,l.pace_per_100m_s,l.swolf,l.total_strokes,l.avg_cadence_spm
        FROM canonical_activities a JOIN activity_laps l USING(activity_id)
        WHERE a.is_swim AND a.environment='pool' AND a.activity_date BETWEEN ? AND ?
        AND l.stroke=? AND abs(l.distance_m-?)<1 AND a.pool_length_m=?
        AND NOT l.is_rest AND l.pace_per_100m_s>0 {extra}
        ORDER BY a.activity_date,a.activity_id,l.lap_index""",params)
    groups={}
    for r in data:
        groups.setdefault(r["activity_id"],[]).append(r)
    annotations={r["activity_id"]:r for r in athlete_files.current_structured_entries("session-annotations","activity_id")}
    sessions=[]
    labeler=athlete_files.WatchLabeler()
    for identifier,laps in groups.items():
        r=laps[0]
        paces=[l["pace_per_100m_s"] for l in laps]
        swolf=[l["swolf"] for l in laps if l["swolf"] is not None]
        sessions.append({"activity_id":identifier,"date":r["activity_date"],"name":r["name"],"device_id":r["device_id"],"watch":labeler.label(r["activity_date"],r["device_id"]),
            "laps_n":len(laps),"median_pace":statistics.median(paces),"min_pace":min(paces),"max_pace":max(paces),
            "pace_sd":statistics.stdev(paces) if len(paces)>1 else None,
            "swolf":statistics.median(swolf) if swolf else None,"swolf_n":len(swolf),
            "first_pace":paces[0],"last_pace":paces[-1],
            "drift_pct":(paces[-1]/paces[0]-1)*100 if len(paces)>=3 else None,
            "annotation":annotations.get(identifier),"laps":laps})
    midpoint=start+timedelta(days=((end-start).days+1)//2)
    per_device=[]
    for d in sorted(set(r["watch"] for r in sessions)):
        group=[s for s in sessions if s["watch"]==d]
        before=[s["median_pace"] for s in group if s["date"]<midpoint]
        after=[s["median_pace"] for s in group if s["date"]>=midpoint]
        enough=len(before)>=4 and len(after)>=4 and d!=athlete_files.UNKNOWN_WATCH
        delta=statistics.median(after)-statistics.median(before) if enough else None
        per_device.append({"watch":d,"before_n":len(before),"after_n":len(after),
            "before_pace":statistics.median(before) if before else None,
            "after_pace":statistics.median(after) if after else None,"delta_s":delta,
            "status":"descriptive_change" if enough else "insufficient_data",
            "note":"Differenza descrittiva fra mediane di seduta; non dimostra miglioramento. Intento, attrezzi e struttura possono differire."})
    options=sorted({r["watch"] for r in sessions})
    return {"start":start,"end":end,"midpoint":midpoint,"stroke":stroke,"distance_m":distance,"pool_m":pool,
        "sessions":sessions,"session_n":len(sessions),"lap_n":len(data),"watches":options,"comparisons":per_device,
        "method":"session-median-v1","limits":["Ogni seduta pesa una volta, anche se contiene più ripetute.",
        "Sono filtrati stile, distanza, vasca; i modelli di orologio restano gruppi distinti; riscaldamento e serie intenzionalmente diverse possono ancora mescolarsi.",
        "Meno di quattro sedute per ciascun periodo o modello di orologio non indicato: nessun confronto numerico conclusivo."]}
