"""«Cosa programmo, cosa ho eseguito e come mi sono sentito?»

Piani e feedback in Markdown; fatti nel DB. Le associazioni ambigue non sono
completamenti automatici. Una proposta non viene salvata senza conferma.
"""
from datetime import date, timedelta
import statistics

from .. import athlete_files
from . import workout_builder, health_monitor
from .dashboard import rows


def validate_entry(kind, data, connection=None):
    if kind == "wellness":
        day=date.fromisoformat(str(data["date"]))
        if day>date.today():
            raise ValueError("Il feedback non può essere nel futuro")
        result={"title":"Feedback del "+day.isoformat(),"date":day.isoformat(),
                "notes":str(data.get("notes", ""))[:3000],"declared_rest":data.get("declared_rest") is True}
        for key in ("fatigue","soreness","motivation","recovery","sleep_quality","rpe"):
            value=data.get(key)
            if value in (None, ""):
                result[key]=None
            elif isinstance(value,bool) or not str(value).isdigit() or not 0<=int(value)<=10:
                raise ValueError("Le valutazioni soggettive devono essere interi da 0 a 10")
            else:
                result[key]=int(value)
        return result
    if kind == "training-settings":
        weekdays=sorted(set(int(v) for v in data.get("weekdays", [])))
        if not weekdays or any(v<0 or v>6 for v in weekdays):
            raise ValueError("Seleziona almeno un giorno disponibile")
        max_minutes=int(data.get("max_minutes",90))
        if not 20<=max_minutes<=240:
            raise ValueError("Durata disponibile: da 20 a 240 minuti")
        race_date=data.get("race_date") or None
        if race_date:
            date.fromisoformat(race_date)
        return {"title":"Preferenze e obiettivi di allenamento","key":"athlete",
            "weekdays":weekdays,"max_minutes":max_minutes,
            "goal":str(data.get("goal", ""))[:2000],"race_date":race_date,
            "race_name":str(data.get("race_name", ""))[:200],
            "race_distance_m":max(0,min(50000,int(data.get("race_distance_m") or 0))),
            "environment":"open_water" if data.get("environment")=="open_water" else "pool"}
    if kind in ("plan-links","plan-revisions"):
        plans={p["id"]:p for p in athlete_files.structured_entries("workouts")}
        identifier=str(data.get("plan_id", ""))
        if identifier not in plans:
            raise ValueError("Piano non trovato")
        revisions={p['plan_id']:p for p in athlete_files.current_structured_entries('plan-revisions','plan_id')}
        current_date=revisions.get(identifier,{}).get('date') or plans[identifier]['date']
        if kind=="plan-revisions":
            status=data.get("status")
            if status not in ("planned","cancelled"):
                raise ValueError("Stato piano non valido")
            changed_date=data.get("date")
            if changed_date:
                date.fromisoformat(str(changed_date))
            return {"title":"Revisione del piano","plan_id":identifier,"status":status,
                    "date":str(changed_date) if changed_date else current_date}
        activity_id=int(data["activity_id"])
        matches=rows(connection,"SELECT activity_id,activity_date,distance_m FROM canonical_activities WHERE is_swim AND activity_id=?",[activity_id])
        if not matches:
            raise ValueError("Attività non trovata")
        if revisions.get(identifier,{}).get('status')=='cancelled':
            raise ValueError('Riattiva il piano prima di collegarlo a una seduta')
        if str(matches[0]["activity_date"])!=current_date:
            raise ValueError("Il collegamento deve riguardare una seduta dello stesso giorno")
        linked=athlete_files.current_structured_entries('plan-links','plan_id')
        if any(p['activity_id']==activity_id and p['plan_id']!=identifier and revisions.get(p['plan_id'],{}).get('status')!='cancelled' for p in linked):
            raise ValueError('La seduta è già collegata a un altro piano attivo')
        return {"title":"Collegamento piano e attività","plan_id":identifier,"activity_id":activity_id}
    if kind=="session-annotations":
        from .session_annotations import validate_groups
        activity_id=int(data["activity_id"])
        if not connection.execute("SELECT count(*) FROM canonical_activities WHERE activity_id=?",[activity_id]).fetchone()[0]:
            raise ValueError("Attività non trovata")
        return {"title":"Contesto e struttura dichiarati","activity_id":activity_id,
            "intent":str(data.get("intent", ""))[:200],"equipment":str(data.get("equipment", ""))[:200],
            "sets":validate_groups(connection,activity_id,data.get("sets",[])),
            "structure":str(data.get("structure", ""))[:4000],"notes":str(data.get("notes", ""))[:2000]}
    raise ValueError("Tipo di memoria non valido")


def settings():
    saved=athlete_files.current_structured_entries("training-settings","key")
    return saved[-1] if saved else {"weekdays":[0,1,3,5],"max_minutes":90,"goal":"",
        "race_date":None,"race_name":"","race_distance_m":0,"environment":"pool",
        "source":"Profilo storico: 3–4 sedute serali, mercoledì escluso; sabato pomeriggio. Confermare i giorni prima di proporre.","confirmed":False}


def workspace(connection,start,end):
    activities=rows(connection,"""SELECT activity_id,activity_date,name,environment,distance_m,duration_s,
        garmin_training_load FROM canonical_activities WHERE is_swim AND activity_date BETWEEN ? AND ? ORDER BY activity_date""",[start,end])
    linked={p["plan_id"]:p for p in athlete_files.current_structured_entries("plan-links","plan_id")}
    revised={p["plan_id"]:p for p in athlete_files.current_structured_entries("plan-revisions","plan_id")}
    plans=[]
    for plan in athlete_files.structured_entries("workouts"):
        revision=revised.get(plan["id"],{})
        if revision.get("date"):
            plan=dict(plan,original_date=plan["date"],date=revision["date"])
        if not start.isoformat()<=plan["date"]<=end.isoformat():
            continue
        candidates=[a for a in activities if str(a["activity_date"])==plan["date"]]
        linked_id=linked.get(plan["id"],{}).get("activity_id")
        actual=next((a for a in candidates if a["activity_id"]==linked_id),None)
        status=revised.get(plan["id"],{}).get("status","planned")
        if status!="cancelled":
            status="completed" if actual else "ambiguous" if len(candidates)>1 else "candidate" if candidates else "upcoming" if plan["date"]>=date.today().isoformat() else "unmatched"
        plans.append(dict(plan,match_status=status,candidates=candidates,actual=actual,
            delta_m=(actual["distance_m"]-plan["total_m"]) if actual and actual["distance_m"] is not None else None))
    feedback=[e for e in athlete_files.current_structured_entries("wellness","date") if start.isoformat()<=e["date"]<=end.isoformat()]
    return {"start":start,"end":end,"activities":activities,"plans":plans,"wellness":feedback,"settings":settings(),
        "annotations":athlete_files.current_structured_entries("session-annotations","activity_id"),
        "match_note":"Una somiglianza di data non certifica il completamento. Conferma esplicitamente il collegamento; con più sedute non viene scelta la più lunga."}


def propose(connection,data,today=None):
    today=today or date.today()
    start=date.fromisoformat(str(data["start"]))
    preferences=validate_entry("training-settings",data)
    weeks=int(data.get("weeks",1))
    if not 1<=weeks<=4 or start<today or start>today+timedelta(days=90):
        raise ValueError("Scegli 1–4 settimane con inizio da oggi ai prossimi 90 giorni")
    begin=today-timedelta(days=28)
    history=rows(connection,"""SELECT activity_id,activity_date,distance_m,duration_s FROM canonical_activities
       WHERE is_swim AND activity_date>=? AND activity_date<? ORDER BY activity_date""",[begin,today])
    valid=[a for a in history if a["distance_m"] is not None and a["distance_m"]>0]
    if len(valid)<4:
        raise ValueError("Servono almeno quattro sedute con distanza negli ultimi 28 giorni; nessun volume inventato")
    weekly=sum(a["distance_m"] for a in valid)/4
    available=len(preferences["weekdays"])
    # Non aumenta il volume rispetto alla media recente, né la durata disponibile.
    typical=statistics.median(a["distance_m"] for a in valid)
    timed=[a["duration_s"]/a["distance_m"] for a in valid if a["duration_s"] and a["duration_s"]>0]
    seconds_per_m=statistics.median(timed) if timed else None
    target=min(weekly/available,typical,preferences["max_minutes"]*60/seconds_per_m if seconds_per_m else typical)
    health=health_monitor.report(connection,today-timedelta(days=27),today)
    observed=[m for m in health["metrics"] if m["status"]=="available" and
        ((m["direction"]==1 and m["position"]=="below_personal_range") or (m["direction"]==-1 and m["position"]=="above_personal_range"))]
    subjective=athlete_files.current_structured_entries("wellness","date")
    latest=next((r for r in sorted(subjective,key=lambda r:r["date"],reverse=True) if today-timedelta(days=1)<=date.fromisoformat(r["date"])<=today),None)
    cautious=len(observed)>=2 or bool(latest and ((latest.get("fatigue") or 0)>=7 or (latest.get("soreness") or 0)>=7))
    if cautious:
        target*=.8
    target=int(target//100)*100
    if target<800:
        raise ValueError("Vincoli e volume recente non sostengono una proposta strutturata di almeno 800 m. Usa il builder manuale con il tuo allenatore")
    sessions=[]
    for offset in range(weeks*7):
        day=start+timedelta(days=offset)
        if day.weekday() not in preferences["weekdays"]:
            continue
        main=target-600
        reps=max(1,main//200)
        main_distance=main//reps//25*25
        blocks=[{"label":"Riscaldamento","reps":1,"distance_m":400,"zone":"Z1","rest_s":20},
                {"label":"Serie aerobica regolare","reps":reps,"distance_m":main_distance,"zone":"Z1" if cautious else "Z2","rest_s":20},
                {"label":"Defaticamento","reps":1,"distance_m":200,"zone":"Z1","rest_s":0}]
        session=workout_builder.workout({"title":"Aerobico controllato" if cautious else "Base endurance", "date":day.isoformat(),"goal":preferences["goal"],"blocks":blocks})
        session.update(source="deterministic_proposal",environment="pool")
        sessions.append(session)
    return {"sessions":sessions,"weekly_reference_m":weekly,"total_m":sum(s["total_m"] for s in sessions),
        "weeks":weeks,"n_history":len(valid),"history_start":begin,"history_end":today-timedelta(days=1),
        "activity_ids":[r["activity_id"] for r in valid],"cautious":cautious,
        "basis":["Volume di riferimento: totale registrato negli ultimi 28 giorni diviso quattro, incluse le settimane senza sedute.",
                 "Nessuna progressione automatica fra settimane; la proposta rispetta disponibilità e durata dichiarate.",
                 "Ritmi non assegnati da una CSS vecchia; zone proposte come intenzione, non come intensità Garmin misurata."],
        "limits":["Proposta locale di piscina, non prescrizione clinica o programma del tuo allenatore.",
                  "Preparazione specifica gara e acque libere richiedono contesto e revisione del coach; non vengono inventate.",
                  "Adattamento prudenziale del 20% solo con almeno due scostamenti personali o feedback di fatica/dolore elevato: regola esplicita di prodotto, non soglia medica."],
        "preferences":preferences}
