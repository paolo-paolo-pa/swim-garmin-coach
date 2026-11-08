"""«Che cosa è successo davvero in questa seduta?» (fase 4.3).

## Un lap non è una serie, e questo file non finge il contrario

Il file FIT registra due cose: i **lap**, cioè i momenti in cui l'orologio ha
segnato un giro, e le **vasche**. Non registra l'intenzione dell'allenatore.
«8×100» è un'interpretazione; un lap è un fatto.

Qui i lap vengono raggruppati per stile e distanza, e il gruppo si chiama
``ripetute confrontabili``, non «serie». Lo stato del raggruppamento è
dichiarato — ``riconosciuta``, ``incerta``, ``non riconosciuta`` — e quando è
incerto il coach lo dice invece di scegliere per l'atleta.

## Perché il passo si confronta solo dentro un gruppo omogeneo

Un 100 a stile e un 100 a delfino non sono lo stesso sforzo. Un 100 in vasca da
50 ha metà delle virate di uno in vasca da 25. Un lap con le palette ha un passo
che non appartiene alla stessa distribuzione di uno a mani nude — e l'attrezzo
il FIT non lo registra, per questo il profilo dell'atleta dice che è la prima
spiegazione alternativa da considerare.

Il gruppo confrontabile è quindi: stessa seduta, stesso stile, stessa distanza,
almeno tre ripetute. Sotto le tre, non si parla di andamento.

## Il calo si osserva, non si interpreta

Se il passo peggiora dall'inizio alla fine, questo file scrive «il passo è
passato da X a Y». Non scrive «cedimento», che presuppone di sapere se quella
serie doveva essere tenuta a ritmo costante — e la finalità la sa l'allenatore,
non l'orologio. Se l'atleta la scrive in ``coach/``, il coach la usa; altrimenti
resta un'osservazione.

## In mare le vasche non esistono

Non sono un dato mancante da recuperare: è il concetto che non si applica. E i
lap in acque libere li ha premuti l'atleta a mano, quindi la loro lunghezza non
è un'unità di misura costante e i passi fra lap diversi non sono confrontabili
allo stesso modo.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

import duckdb

from .. import athlete_files, corrections
from ..database import table_exists
from ..metrics.evidence import Availability
from . import freshness as freshness_module
from .insight import (InsightPacket, Status, evidence, format_measure,
                      format_range, missing_evidence)

# Sotto questo numero di ripetute uguali non si parla di andamento: tre punti
# sono il minimo per distinguere una tendenza da due valori qualsiasi.
MIN_REPEATS_FOR_TREND = 3

# Quanto deve cambiare il passo, in percentuale, perché valga la pena dirlo.
# Sotto, è la variabilità normale di una vasca e di una virata.
NOTABLE_PACE_DRIFT_PCT = 3.0

# Quante sedute omogenee servono perché «questa seduta è anomala» sia una frase
# con un significato invece che un confronto con due casi.
MIN_COMPARABLE_SESSIONS = 8

# Le vasche sotto questa soglia di secondi sono recuperi mal registrati più
# spesso che nuotate: il campo `is_rest` del FIT non è sempre valorizzato.
STROKE_ITALIANO = {
    "freestyle": "stile libero", "backstroke": "dorso",
    "breaststroke": "rana", "butterfly": "delfino",
    "drill": "esercizio", "mixed": "misto", "im": "misti",
}


def _stroke(name: str | None) -> str:
    if not name:
        return "stile non registrato"
    return STROKE_ITALIANO.get(name, name)


@dataclass(frozen=True)
class RepeatGroup:
    """Ripetute confrontabili dentro una seduta: stesso stile, stessa distanza.

    **Non** è una serie. È l'insieme dei lap che si assomigliano abbastanza da
    poter essere messi in fila senza mentire.
    """

    stroke: str | None
    distance_m: float
    paces: tuple[float, ...]

    @property
    def count(self) -> int:
        return len(self.paces)

    @property
    def median_pace(self) -> float:
        return statistics.median(self.paces)

    @property
    def first(self) -> float:
        return self.paces[0]

    @property
    def last(self) -> float:
        return self.paces[-1]

    @property
    def drift_pct(self) -> float:
        """Quanto è cambiato il passo dal primo all'ultimo, in percentuale.

        Positivo significa più lento. Non si chiama «calo»: un passo che
        rallenta in una serie di scarico è quello che doveva succedere.
        """
        return 100.0 * (self.last - self.first) / self.first if self.first else 0.0

    @property
    def spread_pct(self) -> float:
        """La regolarità, come dispersione dei passi attorno alla loro mediana."""
        if self.count < 2:
            return 0.0
        return 100.0 * statistics.stdev(self.paces) / self.median_pace

    @property
    def recognition(self) -> str:
        """Quanto ci si può fidare di considerarli un gruppo unico.

        Non è la qualità del dato: i lap sono fatti. È la qualità
        dell'**interpretazione** che li mette insieme.
        """
        if self.count >= MIN_REPEATS_FOR_TREND and self.spread_pct < 8:
            return "riconosciuta"
        if self.count >= MIN_REPEATS_FOR_TREND:
            return "incerta"
        return "non riconosciuta"

    @property
    def label(self) -> str:
        return (f"{self.count}×{self.distance_m:,.0f} m a {_stroke(self.stroke)}"
                .replace(",", " "))


def _groups(connection: duckdb.DuckDBPyConnection, activity_id: int) -> list[RepeatGroup]:
    """I gruppi di ripetute confrontabili, dal più numeroso al meno.

    I recuperi sono esclusi: una riga con ``is_rest`` serve a ricostruire i tempi
    di partenza, non è una ripetuta andata male.
    """
    rows = connection.execute("""
        SELECT stroke, round(distance_m) AS distanza, lap_index, pace_per_100m_s
        FROM activity_laps
        WHERE activity_id = ? AND NOT is_rest
          AND pace_per_100m_s IS NOT NULL AND distance_m > 0
        ORDER BY stroke, distanza, lap_index
    """, [activity_id]).fetchall()

    raccolti: dict[tuple, list[float]] = {}
    for stroke, distanza, _index, pace in rows:
        raccolti.setdefault((stroke, distanza), []).append(pace)

    gruppi = [RepeatGroup(stroke, distanza, tuple(paces))
              for (stroke, distanza), paces in raccolti.items()
              if len(paces) >= MIN_REPEATS_FOR_TREND]
    return sorted(gruppi, key=lambda g: (-g.count, -g.distance_m))


def _summary(connection: duckdb.DuckDBPyConnection, activity_id: int) -> dict | None:
    row = connection.execute("""
        SELECT activity_id, activity_date, environment, name, distance_m, duration_s,
               pool_length_m, avg_hr_bpm, avg_swolf, rpe, device_id, sport
        FROM canonical_activities WHERE activity_id = ?
    """, [int(activity_id)]).fetchone()
    if row is None:
        return None
    keys = ["activity_id", "date", "environment", "name", "distance_m", "duration_s",
            "pool_length_m", "avg_hr_bpm", "avg_swolf", "rpe", "device_id", "sport"]
    summary = dict(zip(keys, row))
    summary["watch"] = athlete_files.watch_label(summary["date"])
    return summary


def _perche_non_ce(connection: duckdb.DuckDBPyConnection,
                   activity_id: int) -> str:
    """La frase giusta fra due che si somigliano e non sono la stessa cosa."""
    decisione = corrections.about(connection, int(activity_id))
    if decisione is None:
        return "Questa seduta non esiste nell'archivio."
    return (
        f"Questa registrazione è esclusa dalle analisi per tua decisione del "
        f"{decisione.confirmed_on:%d/%m/%Y}. Il motivo che hai confermato: "
        f"{decisione.reason} Resta intatta nelle sorgenti Garmin — l'esclusione "
        f"è uno strato, non una cancellazione — e non contribuisce a "
        f"{decisione.scope}.")


_NO_DETAIL = {
    "unmatched": ("Nessun file FIT corrisponde a questa seduta. Succede a quelle "
                  "arrivate dal sync dopo la data dell'export: i totali ci sono, "
                  "il dettaglio dell'orologio no."),
    "ambiguous": ("Più file FIT sono compatibili con questa seduta e nessuno è "
                  "distinguibile dagli altri. Il dettaglio di un'altra seduta "
                  "sarebbe peggio di nessun dettaglio."),
    "incompatible": ("Il file FIT trovato descrive qualcosa di diverso da questa "
                     "seduta e non è stato usato."),
}


def _intento(packet, activity_id: int) -> None:
    """Che cosa doveva essere questa seduta, secondo chi l'ha fatta.

    Senza l'intento il coach può dire «il passo è rallentato del 10%» e non può
    dire se era previsto: un rallentamento voluto e uno subìto hanno la stessa
    forma nei numeri, e distinguerli non è un problema di analisi ma di
    informazione mancante.

    Quando l'intento non c'è, la domanda successiva lo chiede. È l'unico modo
    perché la volta dopo ci sia — e chiederlo *dopo* aver mostrato cosa è
    successo è diverso da chiederlo prima: l'atleta vede a che cosa serve.
    """
    from .. import athlete_files

    dichiarato = athlete_files.declared_purposes().get(int(activity_id)) or {}
    scopo = dichiarato.get("purpose")
    fatica = dichiarato.get("rpe")

    if scopo and scopo != "non dichiarata":
        pezzi = [f"L'avevi impostata come **{scopo}**"]
        if fatica is not None:
            pezzi.append(f"e l'hai sentita {fatica}/10")
        packet.limitations.append(
            ". ".join([" ".join(pezzi),
                       "Quello che c'è qui sopra è come è andata; se le due "
                       "cose non tornano, è la domanda da portare "
                       "all'allenatore"]) + ".")
        return

    packet.limitations.append(
        "Non hai dichiarato che cosa doveva essere questa seduta. Senza, posso "
        "dire come è andato il passo ma non se è andata come doveva: un passo "
        "che rallenta perché la serie era progressiva e uno che rallenta senza "
        "che fosse previsto hanno la stessa forma nei numeri.")
    # La domanda non si tocca: `_osserva` chiede già fatica e finalità, e in
    # modo più breve. Quello che mancava non era la domanda — era dire cosa
    # cambia se resta senza risposta, che è l'unica cosa che dà un motivo per
    # rispondere.
    if not packet.next_question:
        packet.next_question = (
            "Che cosa doveva essere questa seduta? Scrivilo qui sotto.")


def _dichiara_disaccordo(packet, connection: duckdb.DuckDBPyConnection,
                         activity_id: int) -> None:
    """Se il riepilogo e il file non dicono la stessa distanza, lo si legge qui.

    Il dettaglio c'è ed è vero — il file è proprio questa nuotata — ma i due
    totali non concordano. place03 26/08/2023: 6.000 m dichiarati, 7.446 nel
    file. Chi guarda le ripetute deve sapere che la loro somma non tornerà con
    la distanza in cima alla pagina, altrimenti penserà a un difetto del coach.

    **Se l'atleta ha già deciso, smette di essere una domanda.** «Non ho modo di
    sapere quale sia giusto» resta vero per il codice e non è più vero per la
    pagina: continuare a dirlo dopo che una persona ha risposto è il modo in cui
    un sistema insegna che rispondergli non serve a niente.
    """
    if not table_exists(connection, "activity_source_matches"):
        return
    riga = connection.execute(
        "SELECT reason FROM activity_source_matches "
        "WHERE activity_id = ? AND verdict = 'discordant'",
        [int(activity_id)]).fetchone()
    if not (riga and riga[0]):
        return

    decisione = corrections.about(connection, int(activity_id))
    if decisione and decisione.status == corrections.CORRECT:
        packet.limitations.append(
            f"Il riepilogo Garmin e il file dell'orologio non concordano: "
            f"{riga[0]}. Hai già deciso quale vale: {decisione.reason} "
            "Il dettaglio qui sotto viene comunque dal file.")
        return

    packet.limitations.append(
        f"Il riepilogo Garmin e il file dell'orologio non concordano: "
        f"{riga[0]}. Il dettaglio qui sotto viene dal file, il totale in "
        "cima dal riepilogo, e non ho modo di sapere quale dei due sia "
        "giusto.")


def _why_no_detail(connection: duckdb.DuckDBPyConnection, activity_id: int) -> str:
    if not table_exists(connection, "activity_source_matches"):
        return "Il dettaglio delle sedute non è ancora stato importato."
    row = connection.execute(
        "SELECT verdict, reason FROM activity_source_matches "
        "WHERE activity_id = ? ORDER BY verdict LIMIT 1", [activity_id]).fetchone()
    if row is None:
        return "Questa seduta non è ancora stata esaminata per il dettaglio FIT."
    verdict, reason = row
    testo = _NO_DETAIL.get(verdict, f"Il dettaglio non è disponibile ({verdict}).")
    return f"{testo} ({reason})" if reason else testo


def _comparable_pace(connection: duckdb.DuckDBPyConnection, seduta: dict,
                     group: RepeatGroup) -> tuple[float | None, int]:
    """Il passo tipico dell'atleta su ripetute davvero simili.

    Simili significa: stesso ambiente, **stessa vasca**, **stesso dispositivo**,
    stesso stile, stessa distanza. Le prime due perché una virata in meno cambia
    il passo; la terza perché sensori diversi misurano diversamente, e in un
    anno solo ne convivono fino a quattro.
    """
    rows = connection.execute("""
        SELECT median(l.pace_per_100m_s), count(DISTINCT l.activity_id)
        FROM activity_laps l
        JOIN canonical_activities a ON a.activity_id = l.activity_id
        WHERE NOT l.is_rest AND l.pace_per_100m_s IS NOT NULL
          AND l.stroke IS NOT DISTINCT FROM ?
          AND round(l.distance_m) = ?
          AND a.environment = ?
          AND a.pool_length_m IS NOT DISTINCT FROM ?
          AND a.device_id IS NOT DISTINCT FROM ?
          AND a.activity_id <> ?
          AND a.activity_date <= ?
    """, [group.stroke, group.distance_m, seduta["environment"],
          seduta["pool_length_m"], seduta["device_id"], seduta["activity_id"],
          seduta["date"]]).fetchone()
    return (rows[0], rows[1] or 0) if rows else (None, 0)


def detail(connection: duckdb.DuckDBPyConnection, activity_id: int,
           today: date | None = None) -> InsightPacket:
    """Che cosa è successo dentro una seduta, con quello che i dati reggono."""
    seduta = _summary(connection, activity_id)
    packet = InsightPacket(
        question="Che cosa è successo davvero in questa seduta?",
        observation="",
        freshness=freshness_module.of_database(connection, today))

    if seduta is None:
        # Sparita dalla vista canonica: o non c'è mai stata, o l'atleta l'ha
        # esclusa. Le due cose non si dicono con la stessa frase — una
        # correzione che assomiglia a un buco nei dati verrà scambiata per un
        # difetto, e prima o poi qualcuno la toglierà per «riparare».
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = _perche_non_ce(connection, activity_id)
        return packet

    packet.period = (seduta["date"], seduta["date"])
    packet.links = [{"kind": "session", "activity_id": seduta["activity_id"],
                     "date": seduta["date"].isoformat(),
                     "name": seduta["name"],
                     "environment": seduta["environment"],
                     "display": _titolo(seduta)}]

    packet.add(evidence("swim_distance_m", seduta["distance_m"]))
    packet.add(evidence("session_duration_s", seduta["duration_s"]))
    if seduta["distance_m"] and seduta["duration_s"]:
        passo = seduta["duration_s"] / seduta["distance_m"] * 100
        packet.add(evidence("pace_per_100m_s", round(passo, 1)))

    if seduta["environment"] == "open_water":
        packet.add(evidence("pool_lengths_count", None,
                            availability=Availability.NOT_APPLICABLE,
                            notes=("In acque libere le vasche non esistono: non è "
                                   "un dato mancante da recuperare.",)))
        packet.limitations.append(
            "I lap in mare li hai premuti tu a mano: la loro lunghezza non è "
            "costante, quindi i passi fra un lap e l'altro non si confrontano "
            "come in vasca.")
    else:
        packet.add(evidence("pool_length_m", seduta["pool_length_m"]))

    if seduta["avg_hr_bpm"] is None:
        packet.add(missing_evidence(
            "avg_hr_bpm", Availability.MISSING,
            "la frequenza cardiaca non esiste in questi dati prima del 2021"))
    else:
        packet.add(evidence("avg_hr_bpm", seduta["avg_hr_bpm"]))

    if not table_exists(connection, "activity_laps"):
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = ("Di questa seduta si conoscono solo i totali: il "
                              "dettaglio dell'orologio non è stato importato.")
        return packet

    gruppi = _groups(connection, seduta["activity_id"])
    if not gruppi:
        packet.status = Status.INSUFFICIENT_DATA
        packet.observation = (
            f"{_titolo(seduta)}. Non ci sono ripetute confrontabili: "
            "servono almeno tre lap dello stesso stile e della stessa distanza "
            "per poter dire qualcosa sull'andamento.")
        packet.limitations.append(_why_no_detail(connection, seduta["activity_id"]))
        return packet

    principale = gruppi[0]
    packet.comparisons = [_gruppo_dict(g) for g in gruppi]
    _dichiara_disaccordo(packet, connection, seduta["activity_id"])
    _intento(packet, seduta["activity_id"])

    tipico, quante = _comparable_pace(connection, seduta, principale)
    _osserva(packet, seduta, principale, tipico, quante)
    return packet


def _titolo(seduta: dict) -> str:
    dove = "in mare" if seduta["environment"] == "open_water" else (
        f"in vasca da {seduta['pool_length_m']:,.0f} m".replace(",", " ")
        if seduta["pool_length_m"] else "in vasca")
    return (f"{seduta['date'].strftime('%d/%m/%Y')} · "
            f"{(seduta['distance_m'] or 0):,.0f} m {dove}".replace(",", " "))


def _gruppo_dict(group: RepeatGroup) -> dict:
    return {
        "label": group.label,
        "stroke": group.stroke,
        "distance_m": group.distance_m,
        "repeats": group.count,
        "recognition": group.recognition,
        "median_pace_s": round(group.median_pace, 1),
        "median_pace_display": format_measure(round(group.median_pace, 1), "secondi"),
        "range_display": format_range(round(min(group.paces), 1),
                                      round(max(group.paces), 1), "secondi"),
        "drift_pct": round(group.drift_pct, 1),
        "spread_pct": round(group.spread_pct, 1),
        "note": ("Sono lap raggruppati per stile e distanza, non una serie "
                 "dichiarata dall'allenatore."),
    }


def _osserva(packet: InsightPacket, seduta: dict, group: RepeatGroup,
             tipico: float | None, quante: int) -> None:
    """La frase, e i limiti che la accompagnano sempre."""
    passo_iniziale = format_measure(round(group.first, 1), "secondi")
    passo_finale = format_measure(round(group.last, 1), "secondi")

    if abs(group.drift_pct) >= NOTABLE_PACE_DRIFT_PCT:
        verso = "rallentato" if group.drift_pct > 0 else "accelerato"
        packet.status = Status.INFORMATIVE
        packet.observation = (
            f"{_titolo(seduta)}. Nel gruppo più numeroso — {group.label} — il "
            f"passo è {verso} da {passo_iniziale} a {passo_finale} per 100 m, "
            f"il {abs(group.drift_pct):.0f}% fra la prima e l'ultima.")
        packet.limitations.append(
            "È un'osservazione, non un giudizio: se quella serie doveva essere "
            "progressiva o di scarico, il cambiamento è quello che doveva "
            "succedere. La finalità la sai tu e l'allenatore, l'orologio no.")
    else:
        packet.status = Status.INFORMATIVE
        packet.observation = (
            f"{_titolo(seduta)}. Nel gruppo più numeroso — {group.label} — il "
            f"passo è rimasto regolare attorno a "
            f"{format_measure(round(group.median_pace, 1), 'secondi')} per 100 m.")

    packet.add(evidence("pace_per_100m_s", round(group.median_pace, 1),
                        n=group.count))

    if group.recognition != "riconosciuta":
        packet.limitations.append(
            f"Il raggruppamento è **{group.recognition}**: i lap variano del "
            f"{group.spread_pct:.0f}% fra loro, quindi potrebbero non essere "
            "stati pensati come un'unica serie.")

    # Il confronto con la storia personale esiste solo se ha abbastanza casi.
    if tipico is not None and quante >= MIN_COMPARABLE_SESSIONS:
        packet.comparisons.append({
            "label": f"il tuo passo tipico su {group.distance_m:,.0f} m a "
                     f"{_stroke(group.stroke)}".replace(",", " "),
            "median_pace_display": format_measure(round(tipico, 1), "secondi"),
            "sessions": quante,
            "note": ("Confronto a parità di vasca, dispositivo, stile e "
                     "distanza: sono le uniche condizioni in cui due passi "
                     "vogliono dire la stessa cosa."),
        })
    elif tipico is not None:
        packet.limitations.append(
            f"Non confronto con la tua storia: ci sono solo {quante} sedute "
            f"omogenee con questa, e ne servono almeno {MIN_COMPARABLE_SESSIONS} "
            "perché «anomalo» significhi qualcosa.")

    if seduta["rpe"] is None:
        packet.next_question = (
            "Quanto è stata dura, da 1 a 10? E qual era la finalità della serie?")
    packet.limitations.append(
        "Se hai usato palette, pinne o pull buoy, il passo di questi lap non è "
        "confrontabile con quelli a mani nude — e l'orologio l'attrezzo non lo "
        "registra.")


def listing(connection: duckdb.DuckDBPyConnection, limit: int = 40,
            environment: str | None = None) -> list[dict]:
    """L'elenco delle sedute, con la qualità del dato subito visibile.

    La colonna che conta non è la distanza: è **quanto in profondità si può
    guardare**. Una seduta senza dettaglio non è peggiore, è meno leggibile, e
    saperlo prima di aprirla evita un giro a vuoto.
    """
    filtri = ["is_swim"]
    parametri: list[object] = []
    if environment in ("pool", "open_water"):
        filtri.append("environment = ?")
        parametri.append(environment)

    ha_lap = table_exists(connection, "activity_laps")
    dettaglio = ("(SELECT count(*) FROM activity_laps l "
                 "WHERE l.activity_id = a.activity_id)" if ha_lap else "0")

    rows = connection.execute(f"""
        SELECT a.activity_id, a.activity_date, a.environment, a.name,
               a.distance_m, a.duration_s, a.pool_length_m, a.avg_hr_bpm, a.rpe,
               {dettaglio} AS lap_count
        FROM canonical_activities a
        WHERE {' AND '.join(filtri)}
        ORDER BY a.start_time_utc DESC
        LIMIT ?
    """, parametri + [int(limit)]).fetchall()

    return [{
        "activity_id": r[0],
        "date": r[1].isoformat(),
        "environment": r[2],
        "name": r[3],
        "distance_m": r[4],
        "duration_s": r[5],
        "pool_length_m": r[6],
        "has_heart_rate": r[7] is not None,
        "has_rpe": r[8] is not None,
        "lap_count": r[9],
        "detail_level": "laps" if r[9] else "summary",
        "display": _titolo({"date": r[1], "distance_m": r[4], "environment": r[2],
                            "pool_length_m": r[6]}),
        "detail_display": (f"{r[9]} lap" if r[9] else "solo totali"),
    } for r in rows]
