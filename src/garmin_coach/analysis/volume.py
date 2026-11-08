"""Quanto ha nuotato l'atleta, in un periodo o settimana per settimana.

## Perché esiste questo file

Il volume era calcolato in due posti con SQL diverso: ``_period_stats`` in
``mcp/queries.py`` e ``weekly_volume`` in ``mcp/planning.py``. Due query che
rispondono alla stessa domanda sono due occasioni di rispondere in modo diverso,
e nessuno se ne accorge finché i due numeri non finiscono nella stessa pagina.

Qui c'è una sola definizione di «volume di un periodo», e la usano il confronto,
la preparazione gara, i progressi e l'applicazione.

## Cosa conta come nuotata

Non solo ciò che l'orologio ha registrato. In mare l'orologio spesso non è
ammesso, e venticinque gare in acque libere fra il 2016 e il 2026 non hanno una
seduta Garmin corrispondente: sono nuotate a tutti gli effetti, e nelle settimane
in cui l'atleta ha gareggiato il volume diceva zero.

Quali gare entrano — solo quelle dei giorni in cui l'orologio non ha registrato
nessuna nuotata, così nulla è contato due volte — lo decide la vista
``counted_swims``, che è anche ciò che legge ``daily_status``. Il motivo per cui
la domanda va posta sul giorno e non su ``races.activity_id`` sta nella
migrazione 0016.

I metri di una gara sono **dichiarati dall'evento**, non misurati: per questo
ogni risposta porta anche ``declared_sessions``. Una gara non ha SWOLF, non ha
bracciate, non ha battiti e non nomina un dispositivo, quindi non sposta nessuna
delle medie tecniche — entra nei metri, nei minuti e nel conteggio.

## Perché il volume regge nove anni e l'intensità no

Distanza e durata sono coperte al 97-100% dal 2017. Frequenza cardiaca e carico
non esistono prima del 2021. Le funzioni qui dentro restituiscono quindi
**sempre** anche la numerosità di ciò che è coperto: chi le chiama deve poter
dire «quattro settimane su otto» invece di mostrare una media che finge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

# Sotto questa quota di sedute con frequenza cardiaca, una media di intensità
# descrive un sottoinsieme e non il periodo. Vive qui perché è la stessa soglia
# che usa il rifiuto dei confronti in `compare`.
MIN_INTENSITY_COVERAGE = 0.60


@dataclass(frozen=True)
class PeriodVolume:
    """Il volume di un periodo, con la copertura di ciò che lo compone."""

    start: date
    end: date
    sessions: int
    distance_m: float
    duration_s: float
    swolf_avg: float | None
    swolf_n: int
    stroke_distance_avg: float | None
    stroke_distance_n: int
    hr_avg: float | None
    hr_n: int
    load_avg: float | None
    load_n: int
    devices: tuple[int, ...]
    pool_lengths_m: tuple[float, ...]
    # Quante delle sedute sono gare senza orologio, con i metri dichiarati
    # dall'evento invece che misurati. Zero nella quasi totalità dei periodi.
    declared_sessions: int = 0

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def weeks(self) -> float:
        return max(self.days, 1) / 7

    @property
    def distance_km(self) -> float:
        return round(self.distance_m / 1000, 2)

    @property
    def km_per_week(self) -> float:
        return round(self.distance_m / 1000 / self.weeks, 2)

    @property
    def sessions_per_week(self) -> float:
        return round(self.sessions / self.weeks, 2)

    @property
    def duration_h(self) -> float:
        return round(self.duration_s / 3600, 2)

    @property
    def hr_coverage(self) -> float:
        return self.hr_n / self.sessions if self.sessions else 0.0

    @property
    def intensity_is_comparable(self) -> bool:
        """Se una media di intensità su questo periodo descrive il periodo."""
        return self.hr_coverage >= MIN_INTENSITY_COVERAGE


def _filters(environment: str | None, pool_length_m: float | None
             ) -> tuple[str, list[object]]:
    # `counted_swims` contiene soltanto nuotate: non serve più chiedere
    # `is_swim`. Le gare vi compaiono con `environment = 'open_water'` e
    # `pool_length_m` nullo, quindi un filtro sulla vasca le esclude da solo.
    clauses = ["swim_date BETWEEN ? AND ?"]
    parameters: list[object] = []
    if environment:
        clauses.append("environment = ?")
        parameters.append(environment)
    if pool_length_m:
        clauses.append("pool_length_m = ?")
        parameters.append(float(pool_length_m))
    return " AND ".join(clauses), parameters


def of_period(connection: duckdb.DuckDBPyConnection, start: date, end: date,
              environment: str | None = None,
              pool_length_m: float | None = None) -> PeriodVolume:
    """Il volume fra due date, estremi inclusi."""
    where, extra = _filters(environment, pool_length_m)
    row = connection.execute(f"""
        SELECT count(DISTINCT unit_key), coalesce(sum(distance_m), 0), coalesce(sum(duration_s), 0),
               avg(avg_swolf), count(avg_swolf),
               avg(avg_stroke_distance_m), count(avg_stroke_distance_m),
               avg(avg_hr_bpm), count(avg_hr_bpm),
               avg(garmin_training_load), count(garmin_training_load),
               list_distinct(list(device_id)), list_distinct(list(pool_length_m)),
               count(*) FILTER (WHERE origin = 'race')
        FROM counted_swims WHERE {where}
    """, [start, end] + extra).fetchone()

    return PeriodVolume(
        start=start, end=end,
        sessions=row[0] or 0, distance_m=row[1] or 0.0, duration_s=row[2] or 0.0,
        swolf_avg=round(row[3], 2) if row[3] else None, swolf_n=row[4] or 0,
        stroke_distance_avg=round(row[5], 3) if row[5] else None,
        stroke_distance_n=row[6] or 0,
        hr_avg=round(row[7], 1) if row[7] else None, hr_n=row[8] or 0,
        load_avg=round(row[9], 1) if row[9] else None, load_n=row[10] or 0,
        devices=tuple(sorted(d for d in (row[11] or []) if d is not None)),
        pool_lengths_m=tuple(sorted(p for p in (row[12] or []) if p is not None)),
        declared_sessions=row[13] or 0,
    )


@dataclass(frozen=True)
class Week:
    """Una settimana di nuoto. L'unità in cui l'allenatore ragiona davvero."""

    week_start: date
    sessions: int
    distance_m: float
    duration_s: float
    sessions_with_hr: int
    training_load: float | None
    # Gare senza orologio: metri dichiarati dall'evento, non misurati.
    declared_sessions: int = 0

    @property
    def km(self) -> float:
        return round(self.distance_m / 1000, 2)

    @property
    def hours(self) -> float:
        return round(self.duration_s / 3600, 2)

    def as_dict(self) -> dict:
        return {"week_start": self.week_start.isoformat(), "sessions": self.sessions,
                "km": self.km, "hours": self.hours,
                "sessions_with_hr": self.sessions_with_hr,
                "training_load": self.training_load,
                "declared_sessions": self.declared_sessions}


def weeks_until(connection: duckdb.DuckDBPyConnection, until: date,
                weeks: int = 8) -> list[Week]:
    """Le ultime settimane di nuoto, una riga per settimana.

    Le settimane senza nuotate **non compaiono come zero**: compaiono come
    assenti, e chi le legge deve trattarle come tali. Una settimana di riposo e
    una settimana senza dati sono cose diverse, e sommare zero le confonde.
    """
    start = until - timedelta(weeks=weeks)
    rows = connection.execute("""
        SELECT date_trunc('week', swim_date)::DATE AS week_start,
               count(DISTINCT unit_key), coalesce(sum(distance_m), 0), coalesce(sum(duration_s), 0),
               count(avg_hr_bpm), sum(garmin_training_load),
               count(*) FILTER (WHERE origin = 'race')
        FROM counted_swims
        WHERE swim_date BETWEEN ? AND ?
        GROUP BY 1 ORDER BY 1
    """, [start, until]).fetchall()
    return [Week(week_start=r[0], sessions=r[1], distance_m=r[2], duration_s=r[3],
                 sessions_with_hr=r[4],
                 training_load=round(r[5], 1) if r[5] else None,
                 declared_sessions=r[6])
            for r in rows]
