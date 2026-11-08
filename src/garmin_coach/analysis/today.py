"""«C'è qualcosa che merita la mia attenzione oggi?» (fase 4.1).

## La regola che governa questo file

Nessun punteggio nuovo. Garmin ne ha già tre — Training Readiness, Body Battery,
Training Status — e un quarto inventato qui sarebbe la quarta opinione che
nessuno ha chiesto, per di più senza validazione.

Quello che manca a Garmin non è un numero: è **la fascia personale**. Un HRV di
42 ms non significa niente in assoluto; significa qualcosa rispetto ai sessanta
giorni precedenti di questa persona. Questo file calcola quella fascia e dice
soltanto se il segnale di oggi ci sta dentro o fuori.

## Perché servono segnali concordi

Un solo segnale fuori fascia è rumore: HRV e sonno oscillano da soli, e la
lettura al polso in acqua produce picchi falsi già documentati nel profilo.
Due o più segnali che puntano nella stessa direzione sono un'osservazione.

Non è una diagnosi e non è una previsione di infortunio: è la descrizione di uno
scostamento, con il numero di segnali su cui è stata fatta.

## L'ordine di priorità non è un'opinione

L'atleta ha dichiarato lui stesso il proprio innesco: «leggero fastidio alla
cuffia dei rotatori quando il volume aumenta in maniera sproporzionata». Un
salto di volume viene quindi prima dei segnali di recupero, perché è la cosa che
lui ha chiesto di sorvegliare. Il coach la segnala perché ne parli con
l'allenatore, non per prescrivere niente.

## La sera cambia la lettura, ed è scritto nel profilo

Le sedute sono alle [orario]. Un sonno o un HRV bassi dopo una seduta serale non
sono un segnale indipendente: è il motivo per cui, quando ieri c'è stata una
nuotata serale, il fatto compare fra i **contrari** e non fra le prove.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from ..metrics.evidence import Availability
from . import freshness as freshness_module
from .insight import (InsightPacket, Status, evidence, format_range,
                      missing_evidence)

# Quanti giorni compongono la fascia personale di un segnale. Sessanta e non
# ventotto: la fascia deve dire com'è fatta la normalità di questa persona, e
# quattro settimane in un periodo di carico descrivono il carico, non la persona.
BAND_WINDOW_DAYS = 60

# Sotto questo numero di giorni con dato, la fascia descrive il caso e non
# l'atleta: il segnale viene dichiarato `insufficient_data`, non calcolato.
MIN_BAND_DAYS = 14

# Quante deviazioni standard delimitano la fascia. Una sola: con due, un segnale
# esce dalla fascia così di rado che l'osservazione non arriverebbe mai.
BAND_WIDTH_SD = 1.0

# Quanti segnali concordi servono perché sia un'osservazione invece che rumore.
MIN_CONCORDANT_SIGNALS = 2

# Salto di volume settimanale oltre il quale il coach lo dice. Non è una soglia
# di rischio: è il punto in cui vale la pena portare la domanda all'allenatore.
VOLUME_JUMP_RATIO = 1.50

# L'ora dopo la quale una seduta influenza il sonno della notte seguente.
EVENING_SESSION_HOUR = 19


@dataclass(frozen=True)
class Signal:
    """Un segnale di recupero e il verso in cui va guardato."""

    column: str
    low_is_concerning: bool
    concerning_phrase: str
    better_phrase: str


RECOVERY_SIGNALS = (
    Signal("hrv_ms", True,
           "HRV sotto la fascia personale", "l'HRV è sopra il tuo solito"),
    Signal("resting_hr_bpm", False,
           "FC a riposo sopra la fascia personale", "la FC a riposo è più bassa del solito"),
    Signal("sleep_total_s", True,
           "sonno sotto la fascia personale", "hai dormito più del solito"),
    Signal("body_battery_max", True,
           "Body Battery massima sotto la fascia", "la Body Battery è salita più del solito"),
    Signal("stress_avg", False,
           "stress sopra la fascia personale", "lo stress è più basso del solito"),
)


@dataclass(frozen=True)
class Reading:
    """Un segnale letto oggi contro la propria fascia personale."""

    signal: Signal
    value: float | None
    low: float | None
    high: float | None
    n: int
    availability: str

    @property
    def is_outside(self) -> bool:
        if self.availability != Availability.AVAILABLE or self.value is None:
            return False
        return self.value < self.low or self.value > self.high

    @property
    def is_concerning(self) -> bool:
        """Fuori fascia **nel verso che conta**.

        Un HRV alto e un HRV basso sono entrambi fuori fascia e non vogliono dire
        la stessa cosa: trattarli insieme produrrebbe allarmi su giornate buone.
        """
        if not self.is_outside:
            return False
        return (self.value < self.low) if self.signal.low_is_concerning else (self.value > self.high)

    def as_evidence(self) -> dict:
        if self.availability == Availability.MISSING:
            # Il valore non e stato registrato quel giorno. Non e un problema di
            # storia: e proprio il dato che non c'e.
            return missing_evidence(
                self.signal.column, self.availability,
                "l'orologio non ha registrato questo valore per il giorno")
        if self.availability == Availability.INSUFFICIENT_DATA:
            # Il valore c'e, ma manca la storia per sapere cosa sia normale.
            return missing_evidence(
                self.signal.column, self.availability,
                f"il valore c'e, ma servono almeno {MIN_BAND_DAYS} giorni con "
                f"dato negli ultimi {BAND_WINDOW_DAYS} per avere una fascia "
                f"personale: ce ne sono {self.n}")

        entry = evidence(self.signal.column, self.value, n=self.n,
                         expected_n=BAND_WINDOW_DAYS)
        entry["personal_band"] = {
            "low": round(self.low, 1), "high": round(self.high, 1),
            "display": "fascia personale " + format_range(
                round(self.low, 1), round(self.high, 1), entry.get("unit")),
        }
        entry["position"] = ("sotto" if self.value < self.low
                             else "sopra" if self.value > self.high else "dentro")
        return entry


def _band(connection: duckdb.DuckDBPyConnection, column: str,
          day: date) -> tuple[float | None, float | None, int]:
    """La fascia personale di un segnale, dai giorni precedenti a ``day``."""
    rows = connection.execute(f"""
        SELECT {column} FROM daily_status
        WHERE status_date BETWEEN ? AND ? AND {column} IS NOT NULL
    """, [day - timedelta(days=BAND_WINDOW_DAYS), day - timedelta(days=1)]).fetchall()
    values = [r[0] for r in rows]
    if len(values) < MIN_BAND_DAYS:
        return None, None, len(values)
    centre = statistics.median(values)
    spread = statistics.stdev(values) if len(values) > 1 else 0.0
    return centre - BAND_WIDTH_SD * spread, centre + BAND_WIDTH_SD * spread, len(values)


def _read_signals(connection: duckdb.DuckDBPyConnection, day: date) -> list[Reading]:
    columns = ", ".join(signal.column for signal in RECOVERY_SIGNALS)
    row = connection.execute(
        f"SELECT {columns} FROM daily_status WHERE status_date = ?", [day]).fetchone()
    today_values = dict(zip([s.column for s in RECOVERY_SIGNALS], row or [None] * len(RECOVERY_SIGNALS)))

    readings = []
    for signal in RECOVERY_SIGNALS:
        value = today_values.get(signal.column)
        low, high, n = _band(connection, signal.column, day)
        if value is None:
            availability = Availability.MISSING
        elif low is None:
            availability = Availability.INSUFFICIENT_DATA
        else:
            availability = Availability.AVAILABLE
        readings.append(Reading(signal, value, low, high, n, availability))
    return readings


def _evening_session_yesterday(connection: duckdb.DuckDBPyConnection,
                               day: date) -> bool:
    """Se ieri sera l'atleta ha nuotato tardi.

    Cambia la lettura del sonno e dell'HRV di stanotte, e sta scritto nel
    profilo: è un contrario, non una prova.
    """
    return bool(connection.execute("""
        SELECT count(*) FROM canonical_activities
        WHERE is_swim AND activity_date = ?
          AND start_time_local IS NOT NULL
          AND hour(start_time_local) >= ?
    """, [day - timedelta(days=1), EVENING_SESSION_HOUR]).fetchone()[0])


def _volume_jump(connection: duckdb.DuckDBPyConnection, day: date
                 ) -> tuple[float | None, float | None, float | None]:
    """Volume di sette giorni contro la media settimanale delle ultime quattro."""
    row = connection.execute(
        "SELECT swim_km_7d, swim_km_28d FROM daily_status WHERE status_date = ?",
        [day]).fetchone()
    if not row or row[0] is None or not row[1]:
        return None, None, None
    recent, month = row[0], row[1]
    typical = month / 4
    return recent, typical, (recent / typical if typical else None)


def observation(connection: duckdb.DuckDBPyConnection,
                day: date | None = None,
                today: date | None = None) -> InsightPacket:
    """L'osservazione prioritaria del giorno. Una sola, con le sue prove."""
    state = freshness_module.of_database(connection, today)
    day = day or state.data_through

    packet = InsightPacket(
        question="C'è qualcosa che merita la mia attenzione oggi?",
        observation="",
        freshness=state,
    )

    if day is None:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = ("Non ci sono ancora dati giornalieri: il database è "
                              "vuoto o l'import non è mai stato eseguito.")
        return packet

    packet.period = (day, day)
    readings = _read_signals(connection, day)
    for reading in readings:
        packet.add(reading.as_evidence())

    usable = [r for r in readings if r.availability == Availability.AVAILABLE]
    concerning = [r for r in usable if r.is_concerning]
    reassuring = [r for r in usable if not r.is_outside]

    recent_km, typical_km, ratio = _volume_jump(connection, day)
    if ratio is not None:
        packet.add(evidence("swim_km_7d", round(recent_km, 2)))
        packet.add(evidence("swim_km_28d",
                            round(typical_km * 4, 2) if typical_km else None))

    # ── Priorità 1: il salto di volume, che è l'innesco dichiarato dall'atleta.
    if ratio is not None and ratio >= VOLUME_JUMP_RATIO:
        packet.status = Status.WATCH
        packet.observation = (
            f"Il volume degli ultimi sette giorni è {recent_km:,.1f} km contro una "
            f"media di {typical_km:,.1f} km a settimana nelle ultime quattro: "
            f"{ratio:.0%} del tuo solito recente."
        ).replace(",", " ")
        packet.limitations.append(
            "È una descrizione del volume, non una previsione di infortunio e "
            "non una diagnosi. Il fastidio alla cuffia dei rotatori che hai "
            "dichiarato compare quando il volume sale sproporzionatamente: è "
            "una domanda da portare all'allenatore, non un motivo per fermarsi.")
        packet.next_question = (
            "Questa salita è voluta dal programma dell'allenatore, o è il "
            "risultato di sedute recuperate?")
        if reassuring:
            for reading in reassuring:
                packet.against(reading.as_evidence())
    # ── Priorità 2: segnali di recupero concordi.
    elif len(concerning) >= MIN_CONCORDANT_SIGNALS:
        packet.status = Status.WATCH
        packet.observation = (
            f"{len(concerning)} segnali su {len(usable)} disponibili sono fuori "
            "dalla tua fascia personale nello stesso verso: "
            + ", ".join(r.signal.concerning_phrase for r in concerning) + ".")
        packet.next_question = (
            "Come ti senti in acqua rispetto a com'è andata la settimana scorsa?")
        for reading in reassuring:
            packet.against(reading.as_evidence())
        if _evening_session_yesterday(connection, day):
            packet.against({
                "field": "evening_session",
                "label": "Seduta serale ieri",
                "display": "sì",
                "availability": Availability.AVAILABLE,
                "note": ("Hai nuotato dopo le 19: il sonno e l'HRV di stanotte "
                         "risentono dell'allenamento e non sono un segnale "
                         "indipendente di recupero."),
            })
    # ── Priorità 3: dati troppo pochi per dire qualcosa.
    elif len(usable) < MIN_CONCORDANT_SIGNALS:
        packet.status = Status.INSUFFICIENT_DATA
        # «Non l'ho misurato quel giorno» e «non ho abbastanza storia per sapere
        # cos'è normale» sono due assenze diverse, e comprimerle in una sola
        # frase è esattamente ciò che la Regola Aurea n.5 vieta.
        absent = [r for r in readings if r.availability == Availability.MISSING]
        short = [r for r in readings if r.availability == Availability.INSUFFICIENT_DATA]
        pieces = []
        if absent:
            pieces.append(f"{len(absent)} non {'è stato' if len(absent) == 1 else 'sono stati'} "
                          f"misurat{'o' if len(absent) == 1 else 'i'} quel giorno")
        if short:
            pieces.append(f"{len(short)} non {'ha' if len(short) == 1 else 'hanno'} "
                          f"abbastanza storia per una fascia personale")
        packet.observation = (
            f"Dei {len(RECOVERY_SIGNALS)} segnali di recupero, "
            + " e ".join(pieces) + ". Non basta per dire se questo giorno è "
            "diverso dal tuo normale.")
        packet.limitations.append(
            "L'HRV esiste in questi dati solo dal settembre 2025, e FC a "
            "riposo, stress e Body Battery solo dal 2021. Prima di allora la "
            "domanda sul recupero non ha una risposta misurata, e non è un "
            "difetto: è quello che l'orologio registrava.")
    # ── Altrimenti: normale variabilità personale, e va detto.
    else:
        packet.status = Status.INFORMATIVE
        # Un segnale fuori fascia dal lato buono non è «dentro la fascia», e
        # scriverlo sarebbe falso proprio nel campo che deve essere vero sempre.
        favourable = [r for r in usable if r.is_outside and not r.is_concerning]
        if concerning:
            detail = (f"{len(concerning)} fuori fascia da solo, senza altri "
                      "segnali che vadano nella stessa direzione.")
        elif favourable:
            detail = ("nessuno fuori fascia dal lato che preoccupa, e "
                      + ", ".join(r.signal.better_phrase for r in favourable) + ".")
        else:
            detail = "tutti dentro la fascia personale."
        packet.observation = (
            f"Niente di diverso dal tuo normale: {len(usable)} segnali "
            f"disponibili, {detail}")
        packet.next_question = "Vuoi vedere come è andata l'ultima seduta?"

    if ratio is not None and ratio < VOLUME_JUMP_RATIO and packet.status != Status.INSUFFICIENT_DATA:
        packet.limitations.append(
            f"Volume dei sette giorni al {ratio:.0%} della media delle ultime "
            f"quattro settimane, sotto il {VOLUME_JUMP_RATIO:.0%} oltre il quale "
            "il coach lo segnala.")

    packet.links = _recent_sessions(connection, day)
    return packet


def _recent_sessions(connection: duckdb.DuckDBPyConnection, day: date,
                     how_many: int = 5) -> list[dict]:
    """Le ultime sedute, come collegamenti apribili.

    Il nome viene da Garmin ed è **dato non fidato**: qui viaggia come testo e
    l'interfaccia lo sfugge prima di scriverlo.
    """
    rows = connection.execute("""
        SELECT activity_id, activity_date, environment, distance_m, duration_s, name
        FROM canonical_activities
        WHERE is_swim AND activity_date <= ?
        ORDER BY start_time_utc DESC LIMIT ?
    """, [day, how_many]).fetchall()
    return [{
        "kind": "session",
        "activity_id": r[0],
        "date": r[1].isoformat(),
        "environment": r[2],
        "distance_m": r[3],
        "duration_s": r[4],
        "name": r[5],
        "display": (f"{r[1].strftime('%d/%m')} · "
                    f"{(r[3] or 0):,.0f} m".replace(",", " ") +
                    (" in mare" if r[2] == "open_water" else " in vasca")),
    } for r in rows]
