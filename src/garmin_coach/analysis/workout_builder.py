"""«Come scrivo la prossima seduta e a che ritmo?»

Libreria Zoned MIT; zone adattate dal suo swimmingPaceEngine. Nessun fallback
di popolazione: senza test CSS dichiarato non vengono assegnati ritmi precisi.
"""
import json
import math
from datetime import date
from pathlib import Path

CSS_DELTAS = {"Z1": (10, 20), "Z2": (5, 10), "Z3": (2, 5),
              "Z4": (-2, 2), "Z5": (-5, -2), "Z6": (-10, -5)}


def css_test(data):
    day = date.fromisoformat(str(data["date"]))
    long_s, short_s = float(data["t400"]), float(data["t200"])
    if not all(math.isfinite(v) and v > 0 for v in [long_s, short_s]):
        raise ValueError("Tempi non validi")
    if long_s <= short_s or (200 / (long_s - short_s)) > 3:
        raise ValueError("Tempi incompatibili con il protocollo 400/200")
    if int(data["pool"]) not in (25, 50) or data.get("maximal") is not True:
        raise ValueError("Servono prove massimali confrontabili nella stessa vasca 25 o 50 m")
    pace = (long_s - short_s) / 2
    return {"title": "Test CSS 400/200", "date": day.isoformat(), "t400": long_s,
            "t200": short_s, "pool": int(data["pool"]), "maximal": True,
            "protocol": "400m + 200m massimali; stessa vasca e giornata, recupero completo dichiarato",
            "pace_100_s": pace, "zones": {z: [pace+a, pace+b] for z,(a,b) in CSS_DELTAS.items()}}


def workout(data):
    day = date.fromisoformat(str(data["date"]))
    title = str(data.get("title", "Nuoto")).strip()[:140]
    blocks = data.get("blocks", [])
    if not title or not 1 <= len(blocks) <= 60:
        raise ValueError("Servono titolo e da 1 a 60 blocchi")
    normalized = []
    for b in blocks:
        reps, meters, rest = int(b["reps"]), int(b["distance_m"]), int(b.get("rest_s", 0))
        if not 1 <= reps <= 100 or not 25 <= meters <= 10000 or not 0 <= rest <= 1800:
            raise ValueError("Distanza, ripetizioni o recupero fuori intervallo")
        zone = str(b.get("zone", "Z2"))
        if zone not in CSS_DELTAS:
            raise ValueError("Zona non valida")
        normalized.append({"reps": reps, "distance_m": meters, "rest_s": rest,
                           "zone": zone, "label": str(b.get("label", "Serie"))[:100]})
    volume = sum(b["reps"] * b["distance_m"] for b in normalized)
    if volume > 30000:
        raise ValueError("La seduta supera 30 km: verificare i blocchi")
    return {"title": title, "date": day.isoformat(), "blocks": normalized,
            "total_m": volume, "goal": str(data.get("goal", ""))[:1000],
            "status": "planned", "source": "atleta", "garmin_published": False}


def library():
    return json.loads((Path(__file__).parents[1] / "swimming_workouts.json").read_text(encoding="utf-8"))["templates"]
