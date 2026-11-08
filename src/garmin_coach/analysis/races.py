"""«Quanto è solida la preparazione per questa gara?» (fase 4.4).

## Che cosa questa pagina non fa, e perché

Non prevede il tempo di gara. Senza una curva prestativa validata da un
backtest, una previsione è un numero decorativo — che è peggio di nessun
numero, perché sembra un'informazione.

**La velocità critica invece non è più bloccata.** Lo era finché
``coach/riferimenti.md`` era l'unica sorgente di tempi veri ed era vuoto. Poi è
arrivato lo storico della federazione, e con lui le due prove massimali che il
protocollo chiede: il calcolo vive in `analysis/critical_speed.py` e questa
pagina lo mostra. Il blocco è caduto per i fatti, non per una decisione di
prodotto — ed è rimasto in piedi nove giorni più del dovuto perché il codice
guardava soltanto il file dell'atleta e non l'archivio.

Resta bloccato il tempo atteso, con il proprio motivo scritto. Le zone
cardiache non sono più fra i blocchi, ma non perché siano state sbloccate: sono
**calcolate e sbagliate**, che è un'altra cosa e va detta con le prove.
`analysis/heart_rate_zones.py` le misura e mostra la prima, che da sola basta —
l'orologio ne tiene due definizioni diverse e non concordano fra loro.

Quello che si può fare senza aspettare niente si fa: il modulo per inserire i
riferimenti, la curva delle prove confermate, il lavoro specifico osservato e
la fascia di volume che l'atleta ha **già** sostenuto.

## La fascia storicamente tollerata non è una prescrizione

Dice «hai già nuotato fino a tanto», non «puoi arrivare a tanto». È la
differenza fra una descrizione dell'archivio e un consiglio, e questo prodotto
fa la prima: l'allenatore è una persona in carne e ossa e i contenuti li decide
lui.
"""

from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

import duckdb

from .. import athlete_files
from . import critical_speed
from . import freshness as freshness_module
from . import heart_rate_zones
from . import race_history
from . import open_water_pace
from . import progress as progress_module
from . import volume as volume_module
from .insight import InsightPacket, Status, evidence, format_measure

# Entro quanti giorni una gara condiziona davvero la preparazione.
APPROACH_WINDOW_DAYS = 21

# Quante settimane compongono la fascia di volume storicamente tollerata.
TOLERATED_WINDOW_WEEKS = 52 * 9

# Sotto questo numero di settimane con nuotate la fascia descrive un periodo,
# non l'atleta.
MIN_WEEKS_FOR_BAND = 30


def tolerated_volume_band(connection: duckdb.DuckDBPyConnection,
                          until: date) -> dict:
    """Quanto volume settimanale l'atleta ha **già** sostenuto, in nove anni.

    Prototipo dichiarato tale nella proposta. Non è una soglia di sicurezza e
    non è un obiettivo: è la distribuzione di ciò che è successo davvero.
    """
    settimane = volume_module.weeks_until(connection, until,
                                          weeks=TOLERATED_WINDOW_WEEKS)
    volumi = sorted(s.km for s in settimane if s.km > 0)
    if len(volumi) < MIN_WEEKS_FOR_BAND:
        return {"available": False, "weeks": len(volumi),
                "why": (f"servono almeno {MIN_WEEKS_FOR_BAND} settimane con "
                        f"nuotate; ce ne sono {len(volumi)}")}

    def percentile(quota: float) -> float:
        posizione = min(int(quota * len(volumi)), len(volumi) - 1)
        return volumi[posizione]

    return {
        "available": True,
        "weeks": len(volumi),
        "median_km": round(statistics.median(volumi), 1),
        "usual_high_km": round(percentile(0.90), 1),
        "max_km": round(volumi[-1], 1),
        "display": (
            f"in {len(volumi)} settimane di nuoto la tua mediana è "
            f"{statistics.median(volumi):.1f} km; nel 10% più carico sei stato "
            f"sopra {percentile(0.90):.1f} km, e il massimo di sempre è "
            f"{volumi[-1]:.1f} km"),
    }


def _specific_work(connection: duckdb.DuckDBPyConnection, race, until: date) -> dict:
    """Quanto lavoro nell'ambiente della gara, nelle ultime otto settimane."""
    ambiente = "open_water" if "acque libere" in (race.environment or "").lower() else "pool"
    inizio = until - timedelta(weeks=8)
    specifico = volume_module.of_period(connection, inizio, until, environment=ambiente)
    tutto = volume_module.of_period(connection, inizio, until)
    quota = (specifico.distance_m / tutto.distance_m) if tutto.distance_m else None
    return {
        "environment": ambiente,
        "sessions": specifico.sessions,
        "km": specifico.distance_km,
        "share": round(quota, 3) if quota is not None else None,
        "display": (
            f"{specifico.distance_km} km in {specifico.sessions} sedute "
            + ("in acque libere" if ambiente == "open_water" else "in vasca")
            + " nelle ultime otto settimane"
            + (f", il {quota:.0%} del tuo volume totale" if quota else "")),
    }


def reference_curve() -> list[dict]:
    """Le prove confermate, ordinate per distanza.

    Vuota finché l'atleta non ne conferma almeno una. Non si riempie con i
    tempi trovati nei dati: la media di una seduta con i recuperi dentro non è
    un tempo prestativo, e un 10 km veloce non è una prova massimale finché non
    lo dice chi c'era.
    """
    prove = athlete_files.references()
    per_distanza: dict[tuple, athlete_files.Reference] = {}
    for prova in prove:
        chiave = (prova.distance_m, prova.stroke, prova.pool)
        migliore = per_distanza.get(chiave)
        if migliore is None or prova.seconds < migliore.seconds:
            per_distanza[chiave] = prova

    return [{
        "distance_m": prova.distance_m,
        "stroke": prova.stroke,
        "pool": prova.pool,
        "time_display": athlete_files.format_swim_time(prova.seconds),
        "pace_display": format_measure(round(prova.pace_per_100m_s, 1), "secondi"),
        "date": prova.day.isoformat(),
        "kind": prova.kind,
        "context": prova.context,
        "activity_id": prova.activity_id,
        "label": (f"{prova.distance_m} m {prova.stroke}, vasca {prova.pool}"
                  if prova.pool != "acque libere"
                  else f"{prova.distance_m} m {prova.stroke} in acque libere"),
    } for prova in sorted(per_distanza.values(),
                          key=lambda p: (p.pool, p.stroke, p.distance_m))]


# Le funzioni che restano chiuse finché non ci sono riferimenti confermati, con
# il motivo scritto una volta sola invece che sparso nelle pagine.
BLOCKED_BY_MISSING_REFERENCES = (
    ("tempo di gara atteso",
     "serve un backtest che batta una baseline semplice: la curva adesso c'è, "
     "la prova che sappia prevedere no"),
)


def _critical_speed_note(coppia: critical_speed.Pair) -> str:
    """Da dove viene la velocità critica, in una riga leggibile.

    Non è una curiosità: il numero cambia significato a seconda di quanto erano
    distanti le due prove e di che cosa c'era in mezzo, e mostrarlo nudo
    inviterebbe a fidarsene più di quanto meriti.
    """
    quando = (f"stesso giorno, {coppia.long_day.strftime('%d/%m/%Y')}"
              if coppia.gap_days == 0
              else f"a {coppia.gap_days} giorni di distanza")
    nota = (f"dal 400 in {_swim_time(coppia.long_time_s)} e dal 200 in "
            f"{_swim_time(coppia.short_time_s)}, vasca da "
            f"{coppia.pool_length_m} m, {quando}")
    if coppia.races_between:
        gare = ("un'altra gara" if coppia.races_between == 1
                else f"altre {coppia.races_between} gare")
        nota += (f"; fra le due hai nuotato {gare}, quindi il valore è "
                 "prudente: da fresco il passo è più veloce")
    return nota


def _swim_time(seconds: float) -> str:
    """Il tempo come lo scrive la federazione. Una funzione sola, importata."""
    from .race_history import _show_time
    return _show_time(seconds)


def race_distance_m(testo: str) -> int | None:
    """«10 km» → 10000. «1500 m» → 1500. Quello che non si legge resta None.

    La distanza della gara futura la scrive l'atleta a mano in `coach/gare.md`,
    e un umano scrive «10 km» e non «10000». Indovinare oltre queste due forme
    non serve: se un giorno scriverà qualcosa di diverso, è meglio che la
    pagina dica di non aver capito piuttosto che assegnargli la distanza
    sbagliata.
    """
    pulito = (testo or "").strip().lower().replace(",", ".")
    chilometri = re.search(r"(\d+(?:\.\d+)?)\s*km\b", pulito)
    if chilometri:
        return round(float(chilometri.group(1)) * 1000)
    metri = re.search(r"(\d+)\s*m\b", pulito)
    return int(metri.group(1)) if metri else None


def _passo_obiettivo(packet: InsightPacket,
                     connection: duckdb.DuckDBPyConnection,
                     gara) -> None:
    """A che passo partire, quando i dati di **questo** atleta lo permettono.

    Esiste uno studio che darebbe la formula subito — i primi dieci della 10 km
    ai Mondiali tengono il 92% della propria velocità critica — e applicarlo qui
    produrrebbe un numero con una bibliografia sotto e sbagliato di un quarto.
    Il passo esce solo dalle sue gare; la banda d'élite compare accanto, come
    misura di quanto è distante.
    """
    metri = race_distance_m(gara.distance)
    if metri is None:
        packet.limitations.append(
            f"Non ho capito la distanza «{gara.distance}» scritta in "
            "coach/gare.md: senza distanza non posso proporre un passo.")
        return

    quadro = open_water_pace.summary(connection, metri)
    if quadro["target_s_per_100m"]:
        veloce, lenta = quadro["target_s_per_100m"]
        packet.add(evidence(
            "open_water_target_pace_s_per_100m", round((veloce + lenta) / 2, 2),
            n=len([una for una in quadro["observations"] if una["usable"]]),
            notes=(f"banda {format_measure(veloce, 'secondi per 100 m')} – "
                   f"{format_measure(lenta, 'secondi per 100 m')}, dalle tue "
                   "gare in mare rapportate alla tua velocità critica",)))
    else:
        packet.add(evidence(
            "open_water_target_pace_s_per_100m", None,
            availability="insufficient_data",
            notes=(quadro["why_unavailable"],)))

    if quadro["personal_median_pct"] is not None:
        basso, alto = quadro["literature_band_pct"]
        quota = f"{quadro['personal_median_pct']:.1f}".replace(".", ",")
        packet.limitations.append(
            f"Nelle tue gare in mare hai tenuto in media il "
            f"{quota}% della tua velocità critica. Nei "
            f"{quadro['literature_source']} la quota è {basso}-{alto}%. La "
            "differenza è reale e non va colmata a tavolino: un passo "
            "obiettivo costruito sulla quota d'élite sarebbe molto più veloce "
            "di qualunque cosa tu abbia tenuto in mare.")


def observation(connection: duckdb.DuckDBPyConnection,
                race_id: str | None = None,
                today: date | None = None) -> InsightPacket:
    """Il quadro verso la prossima gara. Fatti e limiti, nessuna previsione."""
    state = freshness_module.of_database(connection, today)
    oggi = today or date.today()
    until = state.data_through or oggi

    packet = InsightPacket(
        question="Quanto è solida la preparazione per questa gara?",
        observation="",
        freshness=state)

    prove = reference_curve()
    packet.comparisons = prove

    gare = athlete_files.upcoming_races()
    gara = next((g for g in gare if g.race_id == race_id), gare[0] if gare else None)

    fascia = tolerated_volume_band(connection, until)
    if fascia["available"]:
        packet.add(evidence("swim_km_week_median", fascia["median_km"], n=fascia["weeks"],
                            notes=(fascia["display"],)))
    else:
        packet.add(evidence("swim_km_week_median", None, availability="insufficient_data",
                            notes=(fascia["why"],)))

    if gara is None:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = (
            "Non c'è nessuna gara futura dichiarata. Il coach non la inventa: "
            "va aggiunta a coach/gare.md con data, distanza e ambiente.")
    else:
        specifico = _specific_work(connection, gara, until)
        packet.add(evidence("open_water_km_8w", specifico["km"], n=specifico["sessions"],
                            notes=(specifico["display"],)))
        packet.period = (until, gara.race_date)
        packet.links = [{"kind": "race", "display": gara.name,
                         "date": gara.race_date.isoformat()}]

        packet.status = Status.INFORMATIVE
        packet.observation = (
            f"{gara.name}, {gara.distance}, fra {gara.days_away} giorni "
            f"({gara.race_date.strftime('%d/%m/%Y')}). {specifico['display']}.")
        if 0 <= gara.days_away <= APPROACH_WINDOW_DAYS:
            packet.next_question = (
                "Sei nelle tre settimane finali: che scarico ha previsto "
                "l'allenatore?")
        else:
            packet.next_question = (
                "Cosa c'è nel programma dell'allenatore fra qui e la gara?")

    coppia = critical_speed.current(connection)
    if coppia:
        packet.add(evidence(
            "critical_swim_speed_pace_s_per_100m", coppia.pace_100_s,
            n=2, notes=(_critical_speed_note(coppia),)))
    else:
        packet.add(evidence(
            "critical_swim_speed_pace_s_per_100m", None,
            availability="insufficient_data",
            notes=(critical_speed.why_unavailable(connection),)))

    if gara is not None:
        _passo_obiettivo(packet, connection, gara)

    if prove:
        packet.limitations.append(
            f"Hai confermato {len(prove)} riferimenti a mano, oltre allo "
            "storico della federazione.")
    for cosa, perche in BLOCKED_BY_MISSING_REFERENCES:
        packet.limitations.append(f"**{cosa}**: non calcolabile — {perche}.")

    # Le zone cardiache non sono «non calcolabili»: sono calcolate e sbagliate,
    # che è un'altra cosa e va detta con le prove invece che con una formula.
    zone = heart_rate_zones.assess(connection)
    if zone.reasons and not zone.usable:
        packet.limitations.append(
            "**zone cardiache**: non affidabili. " + zone.reasons[0])

    # Quello che l'archivio contiene non è quello che l'atleta ha fatto, e
    # confonderli è già costato una frase falsa: «il tuo unico 10 km», quando
    # di event02 ne aveva nuotati tre. Da qui in avanti il limite si dichiara.
    lunghe = race_history.long_swims_not_recorded_as_races(connection)
    if lunghe:
        packet.limitations.append(
            f"**{len(lunghe)} nuotate in mare oltre i 5 km** sono in archivio "
            "come allenamenti e non come gare. Se qualcuna era una gara — un "
            "circuito che Icron non cronometra, un event02 all'estero — "
            "scrivila in coach/gare-dichiarate.md: finché non c'è, il coach "
            "conta quello che vede e non quello che hai nuotato.")

    if fascia["available"]:
        packet.limitations.append(
            "La fascia di volume descrive quello che hai già sostenuto, non "
            "quello che puoi sostenere. È un prototipo, e non è un consiglio "
            "di carico: i contenuti li decide il tuo allenatore.")

    packet.chart = None
    return packet
