"""I fatti che servono a pianificare verso una gara.

Questo modulo **non** scrive allenamenti. Prepara i dati su cui il coach ragiona:
quanto manca, come sta l'atleta, che volume ha sostenuto nelle ultime settimane,
quale copertura hanno quei numeri. La proposta di allenamento è giudizio, e il
giudizio è del modello (Regola Aurea n.6).

Un algoritmo Python che generasse la settimana sarebbe una scorciatoia elegante e
sbagliata: nasconderebbe in un `if` decisioni che vanno motivate leggendo
``knowledge/``.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from ..analysis import volume as volume_service
from ..analysis.insight import evidence, missing_evidence
from ..athlete_files import Race
from ..metrics.evidence import Availability

# Finestra entro la quale una gara condiziona la programmazione. Oltre, il piano
# è ancora in costruzione generale.
APPROACH_WINDOW_DAYS = 21

# Quante settimane di storia servono a descrivere la tendenza del volume.
TREND_WEEKS = 8


def weekly_volume(connection: duckdb.DuckDBPyConnection, until: date,
                  weeks: int = TREND_WEEKS) -> list[dict]:
    """Volume e sedute delle ultime settimane, una riga per settimana.

    Adattatore su ``analysis/volume``: il calcolo sta la, e questa funzione
    esiste solo per non cambiare la forma della risposta di `race_readiness`.
    Aveva una propria query, e arrotondava in SQL invece che in Python: per la
    stessa settimana rispondeva 1,33 km dove l'altra definizione diceva 1,32.
    """
    return [settimana.as_dict()
            for settimana in volume_service.weeks_until(connection, until, weeks)]


def readiness(connection: duckdb.DuckDBPyConnection, race: Race,
              today: date | None = None) -> dict:
    """Il quadro completo verso una gara. Fatti, non consigli."""
    today = today or date.today()
    days_away = (race.race_date - today).days

    latest = connection.execute("SELECT max(status_date) FROM daily_status").fetchone()[0]
    reference_day = min(today, latest) if latest else None

    state = None
    if reference_day:
        row = connection.execute("""
            SELECT status_date, swim_km_7d, swim_km_28d, swim_sessions_7d,
                   swim_sessions_28d, acwr, monotony_7, load_acute_7, load_chronic_28,
                   hrv_ms, hrv_delta_pct, resting_hr_delta, sleep_total_s,
                   garmin_readiness_score, garmin_training_status,
                   days_since_last_swim, has_hrv, has_load
            FROM daily_status WHERE status_date = ?
        """, [reference_day]).fetchone()
        if row:
            keys = ["status_date", "swim_km_7d", "swim_km_28d", "swim_sessions_7d",
                    "swim_sessions_28d", "acwr", "monotony_7", "load_acute_7",
                    "load_chronic_28", "hrv_ms", "hrv_delta_pct", "resting_hr_delta",
                    "sleep_total_s", "garmin_readiness_score", "garmin_training_status",
                    "days_since_last_swim", "has_hrv", "has_load"]
            state = dict(zip(keys, row))
            state["status_date"] = state["status_date"].isoformat()

    # Gare passate sulla stessa distanza: come è andata la preparazione allora.
    comparable = connection.execute("""
        SELECT activity_date, distance_m, duration_s, avg_hr_bpm, environment
        FROM canonical_activities
        WHERE is_swim AND environment = ?
          AND distance_m BETWEEN ? AND ?
        ORDER BY activity_date DESC LIMIT 5
    """, [race.environment if race.environment in ("pool", "open_water") else "open_water",
          _target_distance(race) * 0.9 if _target_distance(race) else 0,
          _target_distance(race) * 1.1 if _target_distance(race) else 0]).fetchall()

    return {
        "race": {
            "race_id": race.race_id, "date": race.race_date.isoformat(),
            "name": race.name, "distance": race.distance,
            "environment": race.environment, "priority": race.priority,
            "goal": race.goal, "notes": race.notes,
            "days_away": days_away,
            "in_approach_window": 0 <= days_away <= APPROACH_WINDOW_DAYS,
            "approach_window_days": APPROACH_WINDOW_DAYS,
        },
        "current_state": state,
        "weekly_volume_trend": weekly_volume(connection, reference_day or today),
        "similar_efforts": [{
            "date": r[0].isoformat(), "distance_m": r[1], "duration_s": r[2],
            "avg_hr_bpm": r[3], "environment": r[4],
            "pace_per_100m_s": round(r[2] / r[1] * 100, 1) if r[1] and r[2] else None,
        } for r in comparable],
        "evidence": _evidence_of(state),
        "coverage": {
            "reference_day": reference_day.isoformat() if reference_day else None,
            "days_behind_today": (today - reference_day).days if reference_day else None,
            "hrv_available": bool(state and state.get("has_hrv")),
            # Un giorno di riposo non ha carico, ma le metriche di carico
            # restano utilizzabili: le due cose non vanno confuse.
            "load_metrics_usable": bool(state and state.get("load_acute_7") is not None),
            "acwr_usable": bool(state and state.get("acwr") is not None),
        },
        "note": (
            "Questi sono fatti misurati. La strategia di avvicinamento, il taper e "
            "la settimana vanno costruiti dal coach leggendo knowledge/, dichiarando "
            "su quali di questi numeri si basa."
        ),
    }


# I numeri che race_readiness mostra davvero. Gli altri campi dello stato sono
# contesto: un elenco di evidenze lungo quanto la risposta non si legge.
READINESS_COLUMNS = ("swim_km_7d", "swim_km_28d", "acwr", "monotony_7",
                     "hrv_ms", "resting_hr_delta", "garmin_readiness_score")


def _evidence_of(state: dict | None) -> list[dict]:
    """L'evidenza dei numeri dello stato, o il motivo per cui non ce n'e."""
    if not state:
        return [missing_evidence(
            column, Availability.MISSING,
            "non c'e nessun giorno di riferimento nel database")
            for column in READINESS_COLUMNS]
    voci = []
    for column in READINESS_COLUMNS:
        valore = state.get(column)
        if valore is None:
            voci.append(missing_evidence(
                column, Availability.MISSING,
                "non registrato per il giorno di riferimento"))
        else:
            voci.append(evidence(column, valore))
    return voci


def _target_distance(race: Race) -> float | None:
    """La distanza di gara in metri, se dichiarata in forma riconoscibile."""
    text = (race.distance or "").lower().replace(",", ".")
    import re
    match = re.search(r"([\d.]+)\s*(km|k|m\b)", text)
    if not match:
        return None
    try:
        amount = float(match.group(1))
    except ValueError:
        return None
    return amount * 1000 if match.group(2) in ("km", "k") else amount
