"""Il pacchetto: tutti i fatti che il giudizio può usare, e nessun altro.

Costruito dai servizi deterministici che esistono già — ``analysis/volume``,
``analysis/today``, ``athlete_files`` — e mai da una query scritta qui. Se una
grandezza serve e non c'è, si aggiunge al servizio che la possiede: una seconda
definizione dentro questo file sarebbe la quarta verità sul volume, dopo che ne
sono già state unificate tre.

## Cosa non entra, e perché

Coordinate GPS, nome dell'atleta, identificativi Garmin, righe grezze, nomi
delle attività. Le prime tre perché non servono a giudicare e uscirebbero dal
computer; le ultime due perché sono **testo non fidato** — un nome di attività
lo scrive chi vuole, e in un pacchetto destinato a un modello un nome è un
posto dove qualcuno può scrivere un'istruzione.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from .. import athlete_files
from ..analysis import volume as volume_service
from .contract import CoachContextPacket, Fact

# Finestre del pacchetto. Dichiarate qui una volta: erano il punto in cui la
# stessa etichetta finiva su grandezze diverse (audit §A3).
RECENT_DAYS = 7
BLOCK_DAYS = 28
SPECIFIC_DAYS = 56          # otto settimane: la specificità si costruisce lunga

ENVIRONMENT_KEYS = {
    "acque libere": "open_water",
    "acqua libera": "open_water",
    "mare": "open_water",
    "open water": "open_water",
    "open_water": "open_water",
    "piscina": "pool",
    "vasca": "pool",
    "pool": "pool",
}


def _environment_key(value: str) -> str | None:
    """Traduce la descrizione umana nell'ambiente usato dalle attività."""
    normalizzato = " ".join((value or "").strip().lower().split())
    return ENVIRONMENT_KEYS.get(normalizzato)


def _fact(fact_id: str, label: str, value, unit: str, window: str,
          display: str | None = None, n: int | None = None,
          why: str = "") -> Fact:
    disponibile = "available" if value is not None else "insufficient_data"
    if display is None:
        display = "—" if value is None else f"{value:,.2f} {unit}".strip()
    return Fact(fact_id=fact_id, label=label, value=value, unit=unit,
                display=display, window=window,
                availability=disponibile, n=n, why=why)


def build(connection: duckdb.DuckDBPyConnection, question: str,
          today: date | None = None) -> CoachContextPacket:
    """Il quadro completo, alla data dell'osservazione."""
    oggi = today or date.today()
    packet = CoachContextPacket(question=question, observation_date=oggi)

    _obiettivo(packet, oggi)
    _allenamento(packet, connection, oggi)
    _prestazione(packet, connection, oggi)
    _recupero(packet, connection, oggi)
    _qualita(packet, connection)
    _limiti(packet)
    return packet


def _prestazione(packet: CoachContextPacket, connection, oggi: date) -> None:
    """I tempi ufficiali: gli unici numeri che non vengono da un orologio.

    Fino a qui il pacchetto conteneva **quanto** l'atleta aveva nuotato e niente
    su **quanto forte**. Il cervello locale lo diceva a ogni risposta — «quello
    che l'archivio non dimostra è una prova recente al passo obiettivo» — e
    aveva ragione: non c'era. Adesso c'è, e viene da una piastra.

    Entrano due fatti e non di più. Il passo sulla distanza di gara più lunga,
    che è il riferimento più vicino al fondo; e da quanti giorni non si gareggia,
    che dice se quel riferimento descrive ancora questa persona. I record sulle
    distanze brevi restano fuori: sono veri e non modificano una decisione su un
    10 km in mare.
    """
    from ..analysis import race_history

    if not race_history.available(connection):
        return

    riferimento = race_history.endurance_reference(connection,until=oggi)
    if riferimento:
        packet.add(_fact(
            "race_endurance_pace_s_per_100m",
            f"Passo in gara sul {riferimento.distance_m} {riferimento.stroke}",
            round(riferimento.pace_per_100, 2), "s/100 m",
            f"gara del {riferimento.day.strftime('%d/%m/%Y')}, "
            f"vasca da {riferimento.pool_length_m} m",
            display=(f"{riferimento.display} sul {riferimento.distance_m} "
                     f"{riferimento.stroke}, cioè "
                     f"{race_history._show_pace(riferimento.pace_per_100)}"),
            n=riferimento.races,
            why="cronometraggio della federazione, non dell'orologio"))
        giorni_riferimento = (oggi - riferimento.day).days
        packet.add(_fact(
            "days_since_endurance_reference",
            "Giorni dal riferimento di fondo",
            giorni_riferimento, "giorni",
            f"riferimento del {riferimento.day.strftime('%d/%m/%Y')}",
            display=f"{giorni_riferimento} giorni",
            why="è l'età del tempo di fondo citato nel verdetto"))

    ultima = race_history.last_race(connection, oggi)
    if ultima:
        packet.add(_fact(
            "days_since_last_race", "Giorni dall'ultima gara",
            ultima["days_ago"], "giorni",
            f"ultima gara il {ultima['day'].strftime('%d/%m/%Y')}",
            display=f"{ultima['days_ago']} giorni",
            why="descrive la recenza dell'archivio gare, non l'età del riferimento di fondo"))

    _velocita_critica(packet, connection)

    packet.limitations.append(
        "Il passo di gara qui sopra è misurato in piscina. Metterlo accanto a "
        "un obiettivo in acque libere è un confronto fra due fatti; ricavare il "
        "secondo dal primo sarebbe una previsione, e su una distanza molte "
        "volte più lunga, in mare e senza muro, nessun modello di questo "
        "progetto la autorizza.")


def _velocita_critica(packet: CoachContextPacket, connection) -> None:
    """Il passo di soglia nel pacchetto: è il numero su cui si costruisce una serie.

    Senza, il coach può dire «tieni il volume dov'è» e non può dire a che ritmo.
    È la differenza fra un commento e un allenamento.
    """
    from ..analysis import critical_speed, race_history

    coppia = critical_speed.current(connection,until=packet.observation_date)
    if not coppia:
        return

    packet.add(_fact(
        "critical_swim_speed_pace_s_per_100m",
        "Passo di soglia (velocità critica)",
        round(coppia.pace_100_s, 2), "s/100 m",
        f"dal 400 e dal 200 in vasca da {coppia.pool_length_m} m, "
        f"{coppia.day.strftime('%d/%m/%Y')}",
        display=race_history._show_pace(coppia.pace_100_s),
        n=2,
        why=("è il riferimento attorno a cui si costruiscono le serie lunghe; "
             "nasce da due gare, quindi da due prove massimali vere")))

    if coppia.races_between:
        packet.limitations.append(
            f"Il passo di soglia nasce da un 400 e un 200 fra i quali hai "
            f"nuotato altre {coppia.races_between} gare: è prudente, e da "
            "fresco il passo vero è più veloce.")


def _obiettivo(packet: CoachContextPacket, oggi: date) -> None:
    """La gara e l'obiettivo, come li ha dichiarati l'atleta.

    ``days_away`` si calcola qui rispetto alla data di osservazione, e non nel
    tipo ``Race``: quello usava ``date.today()`` e ignorava la data passata,
    quindi un'osservazione datata rispondeva con i giorni di oggi.
    """
    gare = [g for g in athlete_files.races() if g.race_date >= oggi]
    gare.sort(key=lambda g: g.race_date)
    if not gare:
        packet.goal = {"event_name": None,
                       "why_missing": "nessuna gara futura dichiarata in "
                                      "coach/gare.md"}
        return

    prossima = gare[0]
    packet.goal = {
        "event_name": prossima.name,
        "event_date": prossima.race_date.isoformat(),
        "days_to_event": (prossima.race_date - oggi).days,
        "distance": prossima.distance,
        "environment": prossima.environment,
        "environment_key": _environment_key(prossima.environment),
        "priority": prossima.priority,
        "declared_target": prossima.goal,
    }
    packet.phase = {
        "name": "avvicinamento" if (prossima.race_date - oggi).days <= 42
                else "costruzione",
        "why": "distanza in giorni dalla gara dichiarata",
    }


def _allenamento(packet: CoachContextPacket, connection, oggi: date) -> None:
    recente = volume_service.of_period(
        connection, oggi - timedelta(days=RECENT_DAYS - 1), oggi)
    blocco = volume_service.of_period(
        connection, oggi - timedelta(days=BLOCK_DAYS - 1), oggi)
    ambiente = packet.goal.get("environment_key")
    specifico = (volume_service.of_period(
        connection, oggi - timedelta(days=SPECIFIC_DAYS - 1), oggi,
        environment=ambiente) if ambiente else None)
    totale_specifico = volume_service.of_period(
        connection, oggi - timedelta(days=SPECIFIC_DAYS - 1), oggi)

    packet.training = {
        "recent_days": RECENT_DAYS,
        "block_days": BLOCK_DAYS,
        "specific_days": SPECIFIC_DAYS,
    }

    packet.add(_fact("swim_km_7d", "Nuoto, ultimi 7 giorni", recente.distance_km,
                     "km", f"{RECENT_DAYS} giorni",
                     n=recente.sessions))
    packet.add(_fact("swim_sessions_7d", "Sedute, ultimi 7 giorni",
                     recente.sessions, "sedute", f"{RECENT_DAYS} giorni",
                     display=f"{recente.sessions} sedute"))
    packet.add(_fact("swim_km_28d", "Nuoto, ultimi 28 giorni",
                     blocco.distance_km, "km", f"{BLOCK_DAYS} giorni",
                     n=blocco.sessions))
    if specifico is not None:
        fact_id = ("open_water_km_8w" if ambiente == "open_water"
                   else "pool_km_8w")
        etichetta = ("Nuoto in acque libere, 8 settimane"
                     if ambiente == "open_water"
                     else "Nuoto in piscina, 8 settimane")
        packet.add(_fact(fact_id, etichetta, specifico.distance_km, "km",
                         f"{SPECIFIC_DAYS} giorni", n=specifico.sessions))
    else:
        packet.add(_fact(
            "specific_environment_km_8w",
            "Nuoto nell'ambiente della gara, 8 settimane", None, "km",
            f"{SPECIFIC_DAYS} giorni",
            why="l'ambiente dichiarato per la gara non è riconosciuto"))

    quota = (specifico.distance_km / totale_specifico.distance_km
             if specifico is not None and totale_specifico.distance_km else None)
    packet.add(_fact(
        "specific_share", "Quota di lavoro nell'ambiente della gara",
        round(quota, 3) if quota is not None else None, "quota",
        f"{SPECIFIC_DAYS} giorni",
        display=f"{quota:.0%}" if quota is not None else "—",
        n=specifico.sessions if specifico is not None else None,
        why=("ambiente della gara non riconosciuto" if ambiente is None
             else "nessun metro nuotato nelle otto settimane"
             if quota is None else "")))


def _recupero(packet: CoachContextPacket, connection, oggi: date) -> None:
    """I segnali di recupero, come modificatori e mai come verdetto.

    Il recupero non decide: cambia quanto ci si può fidare di una decisione
    presa per altri motivi. È la ragione per cui sta in un blocco a parte e non
    fra i fatti dell'allenamento.
    """
    riga = connection.execute("""
        SELECT status_date, hrv_ms, hrv_baseline_28, resting_hr_bpm,
               resting_hr_baseline_28, sleep_total_s, sleep_baseline_28_s,
               body_battery_min, stress_avg
        FROM daily_status WHERE status_date <= ?
        ORDER BY status_date DESC LIMIT 1
    """, [oggi]).fetchone()
    if riga is None:
        packet.recovery = {"summary": None,
                           "why_missing": "nessun giorno in daily_status"}
        return

    (_giorno, hrv, hrv_base, fc, fc_base, sonno, sonno_base,
     batteria, stress) = riga

    identificativi = []
    for fact_id, etichetta, valore, unita, display in (
            ("hrv_ms", "HRV notturna", hrv, "ms",
             f"{hrv:.0f} ms" if hrv is not None else None),
            ("resting_hr_bpm", "FC a riposo", fc, "bpm",
             f"{fc:.0f} bpm" if fc is not None else None),
            ("sleep_total_s", "Sonno", sonno, "s",
             f"{sonno / 3600:.1f} h" if sonno is not None else None),
            ("body_battery_min", "Body Battery minima", batteria,
             "0-100", f"{batteria:.0f}" if batteria is not None else None),
            ("stress_avg", "Stress medio Garmin", stress,
             "0-100", f"{stress:.0f}" if stress is not None else None)):
        packet.add(_fact(fact_id, etichetta, valore, unita, "il giorno stesso",
                         display=display or "—"))
        if valore is not None:
            identificativi.append(fact_id)

    presenti = len(identificativi)
    packet.recovery = {
        "fact_ids": identificativi,
        "signals_available": presenti,
        "summary": (
            f"{presenti} segnali di recupero su 5 sono disponibili oggi."
            if presenti else None),
        "why_missing": None if presenti else "nessun segnale di recupero oggi",
    }


def _qualita(packet: CoachContextPacket, connection) -> None:
    """Quanti record non contano, e quanti aspettano una decisione.

    Sta nel pacchetto e non in fondo alla pagina perché è un modificatore del
    giudizio: una conclusione tratta da un archivio con tre record in attesa di
    verifica non è la stessa conclusione.
    """
    from ..database import table_exists

    if not table_exists(connection, "activity_quality"):
        packet.data_quality = {"excluded": 0, "review": 0}
        return
    righe = dict(connection.execute(
        "SELECT status, count(*) FROM activity_quality GROUP BY 1").fetchall())
    packet.data_quality = {
        "excluded": righe.get("exclude", 0),
        "review": righe.get("review", 0),
        "corrected": righe.get("correct", 0),
    }


def _limiti(packet: CoachContextPacket) -> None:
    if not packet.goal.get("event_name"):
        packet.limitations.append(
            "Senza una gara dichiarata non esiste un riferimento rispetto a cui "
            "parlare di deriva dal focus.")
    quante = packet.data_quality.get("review", 0)
    if quante == 1:
        packet.limitations.append(
            "Una registrazione aspetta una tua decisione e non sostiene "
            "conclusioni forti.")
    elif quante > 1:
        packet.limitations.append(
            f"{quante} registrazioni aspettano una tua decisione e non "
            "sostengono conclusioni forti.")
    packet.limitations.append(
        "Frequenza cardiaca e carico non esistono prima del 2021: nessun "
        "confronto di intensità attraversa quel confine.")
