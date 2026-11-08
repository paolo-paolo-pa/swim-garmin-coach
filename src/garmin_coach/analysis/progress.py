"""«Quando mi sono trovato in una situazione simile, cosa è successo?» (fase 4.2).

## La cosa che Garmin non può fare

Garmin conosce gli ultimi mesi. Questo archivio conosce **nove anni della stessa
persona**. La domanda che ne nasce non è «come sto», ma «l'ultima volta che il
mio volume è salito così, la settimana dopo com'è andata?».

È una domanda a cui si può rispondere onestamente solo in modo descrittivo.
Questo file trova blocchi storici simili, dice **in cosa** sono simili e in cosa
no, e racconta cosa è successo nei 7, 14 e 28 giorni seguenti.

## Perché non dice mai «perché»

Un atleta solo, nove anni, decine di confronti possibili: le associazioni
casuali si trovano da sole. «Dopo blocchi come questo hai nuotato meno» è una
descrizione; «questo blocco ti ha stancato» è una causa, e non è dimostrabile
con questi dati. Il secondo audit ha quindi limitato questa fase al descrittivo:
nessun ordinamento viene presentato come predittivo, e per questo non serve
ancora un walk-forward — che diventerà obbligatorio nel momento in cui qualcosa
qui pretendesse di prevedere.

## Perché il 2017-2020 non sparisce in silenzio

La somiglianza fra due blocchi si calcola **solo su volume e continuità**, che
sono coperti al 97-100% su tutti e nove gli anni. Se si usasse anche il carico,
i quattro anni senza cardiofrequenzimetro verrebbero esclusi automaticamente e
nessuno lo saprebbe. Ogni caso porta quindi la propria **epoca del dato**, e
l'assenza di intensità in un caso del 2018 è dichiarata, non nascosta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from . import adaptation as adaptation_module
from . import chart as chart_module
from . import freshness as freshness_module
from . import volume as volume_module
from .insight import InsightPacket, Status, evidence, format_measure

# Quante settimane compongono il blocco di cui si cerca il precedente. Quattro:
# è il periodo su cui l'allenatore ragiona, ed è abbastanza da non essere una
# settimana storta e abbastanza poco da descrivere un momento.
BLOCK_WEEKS = 4

# Quante settimane si mostrano nel grafico.
CHART_WEEKS = 26

# Quanti casi storici si mostrano. Tre-cinque: sopra, si smette di leggerli.
MAX_CASES = 4

# Quanto possono differire due blocchi per essere ancora «simili», in
# percentuale sul volume settimanale.
SIMILAR_VOLUME_TOLERANCE = 0.15

# Le finestre in cui si guarda cosa è successo dopo.
FOLLOW_UP_DAYS = (7, 14, 28)

# Quando ogni cosa ha cominciato a esistere in questi dati. Serve a dichiarare
# l'epoca di ogni caso invece di lasciare che i vecchi spariscano.
FIRST_INTENSITY_DAY = date(2021, 1, 1)
FIRST_HRV_DAY = date(2025, 9, 19)


def epoch_of(day: date) -> str:
    """Che cosa l'orologio registrava, in quel periodo."""
    if day >= FIRST_HRV_DAY:
        return "volume, intensità, carico e HRV"
    if day >= FIRST_INTENSITY_DAY:
        return "volume, intensità e carico; l'HRV non esisteva ancora"
    return "solo volume e continuità: l'orologio non misurava la frequenza cardiaca"


@dataclass(frozen=True)
class Block:
    """Quattro settimane di nuoto, riassunte da ciò che regge nove anni."""

    start: date
    end: date
    km_per_week: float
    sessions_per_week: float

    @property
    def epoch(self) -> str:
        return epoch_of(self.start)

    @property
    def display(self) -> str:
        return (f"{self.start.strftime('%d/%m/%Y')} → "
                f"{self.end.strftime('%d/%m/%Y')}")


@dataclass(frozen=True)
class DailySeries:
    """Metri e sedute per ogni giorno, letti una volta sola.

    La ricerca dei precedenti confronta centinaia di blocchi. Farlo con una
    query per blocco significava quattrocentocinquanta interrogazioni e due
    secondi di attesa; leggere i giorni una volta e sommarli in memoria costa
    quattro millisecondi. Il database non e lento: era la domanda a essere
    posta male.
    """

    metri: dict[date, float]
    sedute: dict[date, int]
    primo: date | None
    ultimo: date | None

    def window(self, start: date, end: date) -> tuple[float, int]:
        """Metri e sedute fra due date, estremi inclusi."""
        km = sedute = 0.0
        giorno = start
        while giorno <= end:
            km += self.metri.get(giorno, 0.0)
            sedute += self.sedute.get(giorno, 0)
            giorno += timedelta(days=1)
        return km, int(sedute)


def daily_series(connection: duckdb.DuckDBPyConnection) -> DailySeries:
    rows = connection.execute("""
        SELECT activity_date, sum(distance_m), count(*)
        FROM canonical_activities WHERE is_swim
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    metri = {r[0]: (r[1] or 0.0) for r in rows}
    sedute = {r[0]: r[2] for r in rows}
    giorni = [r[0] for r in rows]
    return DailySeries(metri, sedute, giorni[0] if giorni else None,
                       giorni[-1] if giorni else None)


def _block_ending(series: DailySeries, end: date) -> Block:
    start = end - timedelta(weeks=BLOCK_WEEKS) + timedelta(days=1)
    metri, sedute = series.window(start, end)
    return Block(start=start, end=end,
                 km_per_week=round(metri / 1000 / BLOCK_WEEKS, 2),
                 sessions_per_week=round(sedute / BLOCK_WEEKS, 2))


def _what_was_done_after(series: DailySeries, block: Block) -> list[dict]:
    """Quanto e' stato **fatto** nei 7, 14 e 28 giorni dopo la fine di un blocco.

    Si chiamava `_what_happened_after` e la parola era sbagliata: il volume
    delle settimane successive lo hanno deciso il programma dell'allenatore, il
    lavoro e la vita, non il blocco. Chiamarlo "cosa e' successo" faceva
    sembrare una scelta un effetto — il rilievo A4.3 dell'audit.

    Resta utile e resta qui, con il nome giusto. La risposta vera del corpo la
    misura `adaptation.py`.
    """
    esiti = []
    for giorni in FOLLOW_UP_DAYS:
        metri, sedute = series.window(block.end + timedelta(days=1),
                                      block.end + timedelta(days=giorni))
        km = round(metri / 1000, 2)
        settimanale = round(metri / 1000 / (giorni / 7), 2)
        rapporto = (settimanale / block.km_per_week) if block.km_per_week else None
        esiti.append({
            "days": giorni,
            "km": km,
            "sessions": sedute,
            "km_per_week": settimanale,
            "ratio_to_block": round(rapporto, 2) if rapporto else None,
            "display": (f"nei {giorni} giorni dopo hai nuotato "
                        f"{km} km in {sedute} sedute"),
        })
    return esiti


def similar_blocks(connection: duckdb.DuckDBPyConnection, series: DailySeries,
                   current: Block, until: date) -> list[dict]:
    """I blocchi storici piu simili a quello corrente, dal piu simile.

    La somiglianza guarda **solo volume e sedute a settimana**. Non e una
    semplificazione: e l'unico modo di poter confrontare un blocco del 2018 con
    uno del 2026 senza escludere in silenzio quattro anni di storia.
    """
    if not current.km_per_week or series.primo is None:
        return []

    # I blocchi che si sovrappongono a quello corrente non sono precedenti: sono
    # lo stesso periodo visto di sbieco.
    limite = until - timedelta(weeks=BLOCK_WEEKS * 3)

    # Il blocco piu antico possibile e quello che **comincia** il primo giorno
    # con una nuotata, quindi finisce ventisette giorni dopo. Chiedere che
    # finisca quattro settimane dopo il primo giorno buttava via il primo
    # blocco dell'archivio: nella prova, il precedente del 2018 spariva.
    primo_fine_utile = series.primo + timedelta(weeks=BLOCK_WEEKS) - timedelta(days=1)

    trovati = []
    fine = limite
    while fine >= primo_fine_utile:
        candidato = _block_ending(series, fine)
        fine -= timedelta(weeks=1)
        if not candidato.km_per_week:
            continue
        scarto = abs(candidato.km_per_week - current.km_per_week) / current.km_per_week
        if scarto <= SIMILAR_VOLUME_TOLERANCE:
            trovati.append((scarto, candidato))

    trovati.sort(key=lambda coppia: coppia[0])
    scelti, usate = [], []
    for scarto, candidato in trovati:
        # Due blocchi che si sovrappongono raccontano la stessa storia due volte.
        if any(abs((candidato.end - altra).days) < BLOCK_WEEKS * 7 for altra in usate):
            continue
        usate.append(candidato.end)
        assi = adaptation_module.how_the_body_answered(
            connection, candidato.start, candidato.end)
        scelti.append({
            "block": candidato,
            "display": candidato.display,
            "km_per_week": candidato.km_per_week,
            "sessions_per_week": candidato.sessions_per_week,
            "difference_pct": round(scarto * 100, 1),
            "epoch": candidato.epoch,
            "what_you_did_after": _what_was_done_after(series, candidato),
            "response": adaptation_module.as_dicts(assi),
            "response_summary": adaptation_module.summary(assi),
        })
        if len(scelti) >= MAX_CASES:
            break
    return scelti


def observation(connection: duckdb.DuckDBPyConnection,
                until: date | None = None,
                today: date | None = None) -> InsightPacket:
    """Il quadro dei progressi: dove si è adesso, e quando ci si è già stati."""
    state = freshness_module.of_database(connection, today)
    until = until or state.data_through

    packet = InsightPacket(
        question="Quando mi sono trovato in una situazione simile, cosa è successo?",
        observation="",
        freshness=state)

    if until is None:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = "Non ci sono ancora dati da cui ricostruire le settimane."
        return packet

    settimane = volume_module.weeks_until(connection, until, weeks=CHART_WEEKS)
    series = daily_series(connection)
    corrente = _block_ending(series, until)
    packet.period = (corrente.start, corrente.end)

    packet.add(evidence("swim_km_per_week_block", corrente.km_per_week))
    packet.add(evidence("swim_sessions_7d", round(corrente.sessions_per_week, 1)))

    if not corrente.km_per_week:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = (
            f"Nelle quattro settimane fino al {until.strftime('%d/%m/%Y')} non "
            "risultano nuotate: non c'è un blocco da confrontare con la storia.")
        return packet

    casi = similar_blocks(connection, series, corrente, until)
    packet.comparisons = [_caso_dict(caso) for caso in casi]

    if casi:
        packet.status = Status.INFORMATIVE
        packet.observation = (
            f"Le ultime quattro settimane sono a {corrente.km_per_week} km a "
            f"settimana su {corrente.sessions_per_week:.1f} sedute. "
            f"Nell'archivio ci sono {len(casi)} blocchi simili per volume, il "
            f"più vicino è {casi[0]['display']}.")
        packet.next_question = (
            "Guarda come avevi risposto a quei blocchi: è quello che ti aspetti "
            "anche stavolta, o il programma è diverso?")
    else:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = (
            f"Le ultime quattro settimane sono a {corrente.km_per_week} km a "
            "settimana, e nell'archivio non c'è nessun blocco di quattro "
            f"settimane entro il {SIMILAR_VOLUME_TOLERANCE:.0%} di quel volume. "
            "È un periodo senza precedenti confrontabili.")

    packet.limitations.append(
        "La somiglianza è calcolata solo su volume e sedute a settimana. Sono le "
        "uniche grandezze coperte su tutti e nove gli anni: usare anche il "
        "carico escluderebbe in silenzio il 2017-2020, che il tuo orologio di "
        "allora non misurava.")
    packet.limitations.append(
        "Quanto hai nuotato nelle settimane dopo non è una risposta del corpo: "
        "lo hanno deciso il programma dell'allenatore, il lavoro e la vita. La "
        "risposta vera è nei tre assi — prestazione a parità di ripetuta, "
        "tenuta e fisiologia — e anche quelli restano descrizioni: dicono cosa "
        "è cambiato, non che sia stato il blocco a cambiarlo.")
    packet.limitations.append(
        "La prestazione si confronta solo fra ripetute della stessa lunghezza "
        "nella stessa vasca. In acque libere i lap li premi tu a mano e non "
        "hanno lunghezza costante, quindi lì il confronto non esiste.")

    packet.links = [{"kind": "chart", "display": "volume settimanale"}]
    packet.chart = chart_module.weekly_bars(settimane)
    return packet


def _caso_dict(caso: dict) -> dict:
    blocco: Block = caso["block"]
    return {
        "label": f"blocco del {caso['display']}",
        "display": caso["display"],
        "start": blocco.start.isoformat(),
        "end": blocco.end.isoformat(),
        "km_per_week": caso["km_per_week"],
        "km_per_week_display": format_measure(caso["km_per_week"], "km"),
        "sessions_per_week": caso["sessions_per_week"],
        "difference_pct": caso["difference_pct"],
        "epoch": caso["epoch"],
        "what_you_did_after": caso["what_you_did_after"],
        "response": caso["response"],
        "response_summary": caso["response_summary"],
        "note": (f"Simile per volume entro il {caso['difference_pct']}%. "
                 f"In quel periodo l'orologio registrava: {caso['epoch']}."),
    }
