"""Crea un archivio di esempio con dati inventati (nessun dato reale).

Uso:  python scripts/make_demo_data.py [percorso.duckdb]

Senza argomenti scrive in ``data/coach.duckdb`` (solo se non esiste già).
Genera due anni di sedute di piscina e acque libere, salute, sonno e qualche gara,
con un seme fisso: lo stesso comando dà sempre lo stesso archivio.
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from garmin_coach import database  # noqa: E402
from garmin_coach.metrics.daily_status import build  # noqa: E402

END = date(2026, 10, 25)
START = END - timedelta(days=730)
DEVICE = 1001


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else database.paths.DATABASE
    if target.exists():
        print(f"{target} esiste già: non lo tocco.", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(2026)
    con = database.connect(path=target)
    ts = "current_timestamp"
    activity_id = 5_000_000
    day = START
    while day <= END:
        # salute e sonno ogni giorno
        con.execute(f"INSERT INTO daily_health(health_date,resting_hr_bpm,stress_avg,body_battery_min,body_battery_max,source_object_id,imported_at) "
                    f"VALUES (?,?,?,?,?,'demo',{ts})", [day, rnd.randint(50, 58), rnd.randint(20, 40), rnd.randint(15, 35), rnd.randint(70, 95)])
        sleep_s = rnd.randint(6 * 3600, 8 * 3600 + 1800)
        start_utc = datetime(day.year, day.month, day.day, 21, 30)
        con.execute(f"INSERT INTO sleep(sleep_date,sleep_start_utc,sleep_end_utc,total_sleep_s,deep_s,light_s,rem_s,awake_s,sleep_score,source_object_id,imported_at) "
                    f"VALUES (?,?,?,?,?,?,?,?,?,'demo',{ts})",
                    [day, start_utc, start_utc + timedelta(seconds=sleep_s), sleep_s, int(sleep_s * .2), int(sleep_s * .55), int(sleep_s * .22), int(sleep_s * .03), rnd.randint(60, 90)])
        # 3-4 sedute a settimana: lun, mar, gio, sab
        if day.weekday() in (0, 1, 3, 5) and rnd.random() > 0.12:
            activity_id += 1
            open_water = day.month in (6, 7, 8, 9) and day.weekday() == 5
            laps = 1 if open_water else 20
            pace = rnd.uniform(86, 98)          # secondi per 100 m
            lap_m = 2500 if open_water else 100
            total_m = laps * lap_m
            dur = total_m / 100 * pace
            con.execute(
                "INSERT INTO activities(activity_id,start_time_utc,start_time_local,activity_date,sport,is_swim,environment,name,duration_s,elapsed_s,moving_s,"
                "distance_m,avg_hr_bpm,pool_length_m,avg_swolf,total_strokes,lap_count,device_id,source_object_id,imported_at) "
                f"VALUES (?,?,?,?,?,true,?,?,?,?,?,?,?,?,?,?,?,?,'demo',{ts})",
                [activity_id, datetime(day.year, day.month, day.day, 18), datetime(day.year, day.month, day.day, 20), day, "open_water_swimming" if open_water else "lap_swimming",
                 "open_water" if open_water else "pool", "Open Water Swim" if open_water else "Pool Swim", dur, dur * 1.1, dur, total_m,
                 rnd.randint(125, 150), None if open_water else 25, None if open_water else rnd.randint(28, 34), rnd.randint(500, 900), laps, DEVICE])
            for i in range(laps):
                lap_pace = pace + rnd.uniform(-3, 3)
                con.execute(
                    "INSERT INTO activity_laps(activity_id,lap_index,start_time_utc,duration_s,distance_m,lengths_count,active_lengths_count,stroke,total_strokes,"
                    f"avg_hr_bpm,pace_per_100m_s,swolf,is_rest,source_object_id,imported_at,environment) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,false,'demo',{ts},?)",
                    [activity_id, i, datetime(day.year, day.month, day.day, 18, i), lap_m / 100 * lap_pace, lap_m, lap_m // 25, lap_m // 25, "freestyle",
                     rnd.randint(70, 90), rnd.randint(125, 150), lap_pace, rnd.randint(28, 34), "open_water" if open_water else "pool"])
        day += timedelta(days=1)
    build(con)
    con.close()
    print(f"Archivio di esempio creato: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
