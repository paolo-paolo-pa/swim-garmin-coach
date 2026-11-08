"""«Come distribuiresti tu la settimana?»

## Una tensione dichiarata, non aggirata

Il piano di questo progetto elenca fra i **non obiettivi**: «non genera come
funzione centrale calendari o programmi completi e non sostituisce l'allenatore
umano». Questo modulo si avvicina a quel confine più di qualunque altro, e
l'atleta l'ha chiesto esplicitamente come alternativa allo scrivere lui il
programma del suo allenatore.

Il confine si tiene così: **si propone una distribuzione, non un allenamento.**
Quante sedute, quanti metri, in che ambiente, a che passo — e nient'altro. Che
serie nuotare dentro quella distribuzione lo decide una persona.

La differenza non è formale. «Tre sedute aerobiche da 3.500 m attorno a
1:20/100» è una cornice dentro cui un allenatore lavora; «8×400 rec 30" a
1:18» è il suo mestiere.

## Da dove viene ogni numero

| Cosa | Da dove |
|---|---|
| quante sedute e quanti metri | dalla **sua** storia: la fascia che ha già sostenuto |
| quanto lavoro specifico | dall'obiettivo dichiarato in `coach/gare.md` |
| i passi | dalla **sua** velocità critica, con gli scarti della prassi [CSS-5] |
| quanto lavoro intenso | dalla distribuzione polarizzata, il grosso in aerobico |

Nessuno di questi numeri è inventato qui. Se manca la velocità critica, i passi
non compaiono; se manca la storia di volume, la proposta non si fa.

## Quello che questo modulo non sa

Non sa cosa ha fatto l'atleta ieri con il suo allenatore, non sa se una spalla
tira, non sa che questa settimana lavora di notte. Per questo la proposta esce
sempre con l'etichetta di **proposta**, e la pagina la mette accanto al
programma vero invece che al posto suo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb

from .. import athlete_files
from . import critical_speed, races, volume as volume_module

# Gli scarti in secondi per 100 m rispetto al passo di soglia. Sono **prassi
# allenatoriale concordante** fra le scuole [CSS-5], non un risultato
# sperimentale, e la scheda `knowledge/01-fondamenti/zone-di-intensita.md` li
# riporta con la stessa origine.
PACE_OFFSETS = {
    "recupero": (8, 12),
    "aerobico": (4, 8),
    "soglia": (-2, 2),
    "vo2max": (-6, -3),
}

# Come si distribuisce una settimana di fondo: il grosso del volume in
# aerobico, una quota piccola e protetta di lavoro intenso. Le quote sono
# **scelte** e coerenti con la scheda sulle zone; non vengono da uno studio su
# questo atleta.
DISTRIBUTION = (
    ("aerobico", 0.60),
    ("specifico gara", 0.25),
    ("soglia", 0.10),
    ("recupero", 0.05),
)

# Sotto questo numero di settimane osservate non si propone niente: la fascia
# di volume descriverebbe un periodo e non l'atleta.
MIN_WEEKS_OBSERVED = 30


@dataclass(frozen=True)
class ProposedSession:
    """Una seduta proposta: quanto, dove, a che passo. Non cosa."""

    purpose: str
    distance_m: int
    environment: str
    pace_band: tuple[float, float] | None
    pace_note: str = ""

    @property
    def pace_display(self) -> str:
        """Il passo, o il motivo giusto per cui non c'è.

        I motivi sono due e vanno distinti: «manca la velocità critica» e «il
        passo di questo lavoro non si ricava dalla velocità critica». Il
        secondo è il caso del lavoro specifico in mare, dove usare il passo di
        soglia in vasca sarebbe l'errore che tutta la scheda
        `dal-passo-in-vasca-al-passo-in-mare` esiste per impedire.
        """
        if self.pace_band:
            veloce, lento = self.pace_band
            return f"{_pace(veloce)} – {_pace(lento)}"
        return self.pace_note or "passo non proponibile"


@dataclass
class Proposal:
    available: bool = False
    why: str = ""
    weekly_km: float = 0.0
    sessions: list[ProposedSession] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def _pace(seconds_per_100: float) -> str:
    centesimi = round(seconds_per_100 * 100)
    minuti, resto = divmod(centesimi, 6000)
    return f"{minuti}:{resto / 100:05.2f}/100 m".replace(".", ",")


def propose(connection: duckdb.DuckDBPyConnection,
            today: date | None = None) -> Proposal:
    """La distribuzione della settimana, dalla sua storia e dal suo obiettivo.

    Il volume proposto è quello che l'atleta **ha già sostenuto di recente**,
    non quello che potrebbe sostenere: la differenza è fra una descrizione
    dell'archivio e un consiglio di carico, e questo prodotto fa la prima.
    """
    oggi = today or date.today()
    quadro = Proposal()

    fascia = races.tolerated_volume_band(connection, oggi)
    if not fascia["available"]:
        quadro.why = (
            "Non c'è abbastanza storia di volume per proporre una "
            f"distribuzione: {fascia['why']}.")
        return quadro

    # Il riferimento è ciò che ha nuotato nelle ultime quattro settimane, non
    # la mediana di nove anni: una mediana storica riporterebbe indietro un
    # atleta che nel frattempo si è costruito addosso un volume più alto.
    recenti = [una.km for una in volume_module.weeks_until(connection, oggi,
                                                           weeks=4)
               if una.km > 0]
    if not recenti:
        quadro.why = ("Nelle ultime quattro settimane non risultano nuotate: "
                      "non c'è un volume da cui partire.")
        return quadro

    settimanali = round(sum(recenti) / len(recenti), 1)
    quadro.weekly_km = settimanali
    quadro.basis.append(
        f"Volume: {settimanali} km, la tua media delle ultime "
        f"{len(recenti)} settimane con nuotate. La tua mediana di sempre è "
        f"{fascia['median_km']} km e il massimo {fascia['max_km']} km.")

    coppia = critical_speed.current(connection)
    if coppia:
        quadro.basis.append(
            f"Passi: dalla tua velocità critica, {_pace(coppia.pace_100_s)}.")
    else:
        quadro.caveats.append(
            "Senza velocità critica i passi non compaiono: la distribuzione "
            "resta in metri.")

    gare = athlete_files.upcoming_races(today=oggi)
    gara = gare[0] if gare else None
    ambiente_gara = ("acque libere" if gara and "acque libere"
                     in (gara.environment or "").lower() else "vasca")
    if gara:
        quadro.basis.append(
            f"Specificità: {gara.name} fra {(gara.race_date - oggi).days} giorni, "
            f"in {ambiente_gara}.")

    metri_totali = settimanali * 1000
    for intento, quota in DISTRIBUTION:
        metri = int(round(metri_totali * quota / 100.0) * 100)
        if metri < 500:
            continue
        ambiente = ambiente_gara if intento == "specifico gara" else "vasca"
        quadro.sessions.append(ProposedSession(
            purpose=intento, distance_m=metri, environment=ambiente,
            pace_band=_band(coppia, intento),
            pace_note=_pace_note(coppia, intento, ambiente)))

    quadro.available = True
    quadro.caveats.append(
        "**È una proposta di distribuzione, non un allenamento.** Quante "
        "sedute, quanti metri, dove e a che passo. Che serie nuotare dentro "
        "questa cornice lo decide il tuo allenatore, ed è il suo mestiere.")
    quadro.caveats.append(
        "Non so cosa hai fatto ieri con lui, se una spalla tira, o se questa "
        "settimana lavori di notte. Se il suo programma esiste, quello vince: "
        "scrivilo in coach/programma-settimanale.md e questa proposta diventa "
        "un confronto invece che un'alternativa.")
    if gara and ambiente_gara == "acque libere":
        quadro.caveats.append(
            "Il passo per il lavoro specifico in mare **non** è quello di "
            "soglia in vasca: nelle tue gare in mare hai tenuto una quota più "
            "bassa della tua velocità critica, e la pagina Gare lo misura.")
    return quadro


def _pace_note(coppia, intento: str, ambiente: str) -> str:
    if intento == "specifico gara":
        if ambiente == "acque libere":
            return ("al passo obiettivo di gara, che si misura sulle tue gare "
                    "in mare e non sulla velocità critica in vasca")
        return "al passo obiettivo di gara"
    if not coppia:
        return "manca la velocità critica"
    return ""


def _band(coppia, intento: str) -> tuple[float, float] | None:
    scarti = PACE_OFFSETS.get(intento)
    if not coppia or not scarti:
        return None
    veloce, lento = scarti
    return coppia.pace_100_s + veloce, coppia.pace_100_s + lento


def as_page_dict(connection: duckdb.DuckDBPyConnection,
                 today: date | None = None) -> dict:
    quadro = propose(connection, today)
    if not quadro.available:
        return {"available": False, "why": quadro.why}
    return {
        "available": True,
        "headline": (f"{quadro.weekly_km} km distribuiti così, su "
                     f"{len(quadro.sessions)} tipi di lavoro"),
        "sessions": [{
            "purpose": una.purpose,
            "distance": f"{una.distance_m:,} m".replace(",", "."),
            "environment": una.environment,
            "pace": una.pace_display,
        } for una in quadro.sessions],
        "basis": list(quadro.basis),
        "caveats": list(quadro.caveats),
    }
