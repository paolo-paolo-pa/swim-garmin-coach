"""La settimana: cosa è stato fatto, e quanto di quello che è stato fatto si sa.

## La domanda dell'atleta

*«Questa settimana è andata come doveva?»*

## Perché manca metà della risposta, e va detto

L'incarico chiede piano contro eseguito. **Il piano non esiste nel sistema**: lo
fa l'allenatore umano, altrove, e nessuno lo ha mai scritto qui dentro. Questa
pagina mostra quindi la metà che c'è — l'eseguito — e dichiara che l'altra metà
manca, invece di inventare un piano dai dati e poi confrontarci l'eseguito.
Sarebbe la forma più elegante di autoinganno: si confronterebbe l'atleta con
sé stesso e si chiamerebbe aderenza.

## Dove sta la finalità delle sedute

Nel diario, dove l'atleta la scrive. Non nel FIT, che non la contiene e non la
conterrà mai. Le sedute senza nota non spariscono e non vengono indovinate:
entrano in *«finalità non dichiarata»*, che è un numero che l'atleta può far
scendere scrivendo — ed è il modo di mostrargli perché vale la pena.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from .. import athlete_files
from . import volume as volume_service

# La settimana comincia di lunedì, come il calendario dell'atleta e come
# `date_trunc('week')` di DuckDB. Non è una scelta: è l'unico modo perché «la
# settimana scorsa» significhi la stessa cosa qui e nel resto del progetto.
WEEK_STARTS_ON_MONDAY = True


@dataclass
class Week:
    start: date
    end: date
    sessions: int = 0
    distance_km: float = 0.0
    duration_h: float = 0.0
    open_water_km: float = 0.0
    pool_km: float = 0.0
    days_trained: int = 0
    by_purpose: dict = field(default_factory=dict)
    declared_n: int = 0
    rpe_values: list = field(default_factory=list)
    other_sports_sessions: int = 0

    @property
    def declared_share(self) -> float | None:
        """Quante sedute hanno una finalità dichiarata."""
        return self.declared_n / self.sessions if self.sessions else None

    @property
    def avg_rpe(self) -> float | None:
        """La fatica percepita media, se ce n'è abbastanza per una media.

        Su una sola seduta non è una media della settimana: è quella seduta.
        """
        return (sum(self.rpe_values) / len(self.rpe_values)
                if len(self.rpe_values) >= 2 else None)

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "sessions": self.sessions, "distance_km": self.distance_km,
            "duration_h": self.duration_h,
            "open_water_km": self.open_water_km, "pool_km": self.pool_km,
            "days_trained": self.days_trained,
            "by_purpose": self.by_purpose,
            "declared_n": self.declared_n,
            "declared_share": self.declared_share,
            "avg_rpe": self.avg_rpe,
            "other_sports_sessions": self.other_sports_sessions,
        }


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def of_week(connection: duckdb.DuckDBPyConnection,
            any_day_in_it: date) -> Week:
    """La settimana che contiene quel giorno."""
    inizio = monday_of(any_day_in_it)
    fine = inizio + timedelta(days=6)
    settimana = Week(start=inizio, end=fine)

    # I totali dall'unico posto che sa cosa significa «volume di un periodo».
    nuoto = volume_service.of_period(connection, inizio, fine)
    settimana.sessions = nuoto.sessions
    settimana.distance_km = nuoto.distance_km
    settimana.duration_h = nuoto.duration_h
    settimana.open_water_km = volume_service.of_period(
        connection, inizio, fine, environment="open_water").distance_km
    settimana.pool_km = volume_service.of_period(
        connection, inizio, fine, environment="pool").distance_km

    settimana.days_trained = connection.execute("""
        SELECT count(DISTINCT activity_date) FROM canonical_activities
        WHERE is_swim AND activity_date BETWEEN ? AND ?
    """, [inizio, fine]).fetchone()[0]

    # Il carico degli altri sport resta separato: sommarlo al nuoto
    # risponderebbe a una domanda che l'atleta non ha fatto.
    settimana.other_sports_sessions = connection.execute("""
        SELECT count(DISTINCT session_key) FROM canonical_activities
        WHERE NOT is_swim AND activity_date BETWEEN ? AND ?
    """, [inizio, fine]).fetchone()[0]

    _finalita(connection, settimana)
    return settimana


def _finalita(connection: duckdb.DuckDBPyConnection, settimana: Week) -> None:
    """La distribuzione per finalità, e quanto se ne sa davvero."""
    dichiarate = athlete_files.declared_purposes()
    righe = connection.execute("""
        SELECT activity_id, coalesce(distance_m, 0) FROM canonical_activities
        WHERE is_swim AND activity_date BETWEEN ? AND ?
    """, [settimana.start, settimana.end]).fetchall()

    per_finalita: dict[str, float] = {}
    for activity_id, metri in righe:
        nota = dichiarate.get(int(activity_id)) or {}
        scopo = nota.get("purpose")
        if scopo and scopo != "non dichiarata":
            settimana.declared_n += 1
        else:
            scopo = "non dichiarata"
        per_finalita[scopo] = per_finalita.get(scopo, 0.0) + metri
        if nota.get("rpe") is not None:
            settimana.rpe_values.append(nota["rpe"])

    settimana.by_purpose = {nome: round(metri / 1000, 2)
                            for nome, metri in sorted(
                                per_finalita.items(), key=lambda x: -x[1])}


def recent(connection: duckdb.DuckDBPyConnection, today: date | None = None,
           weeks: int = 4) -> list[Week]:
    """Le ultime settimane, dalla più recente."""
    oggi = today or date.today()
    return [of_week(connection, monday_of(oggi) - timedelta(weeks=i))
            for i in range(weeks)]
