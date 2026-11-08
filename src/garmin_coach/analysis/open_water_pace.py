"""«A che passo ha senso partire nella gara in mare?»

## Perché questo file esiste, e perché non risponde

Il progetto ha rifiutato per nove mesi di collegare i tempi in piscina a un
obiettivo in acque libere, e aveva ragione: senza una misura di quel salto,
ricavare il secondo dal primo era un'invenzione.

Adesso la misura esiste. Ai Mondiali 2023, su 65 uomini, i primi dieci hanno
tenuto la 10 km al **92,3% della propria velocità critica** ricavata dai tempi in
vasca, e il tempo stimato dalla piscina risultava ~9,5% più veloce di quello
vero [OW-1]. Sembrerebbe la formula che mancava.

**Non lo è, e la prova sta nell'archivio di questo atleta.**

## Cosa dicono i suoi dati

Misurando le sue gare in mare contro la sua velocità critica più vicina nel
tempo, la quota non è il 92%: è fra il 78% e l'85% sulle distanze medie, e
sull'unica 10 km **presente in archivio** — event02 place05 2019 — scende al
71%. E cala con la distanza, che è quello che la fisiologia prevede e che nei
dati d'élite non si vede, perché un professionista tiene la propria soglia molto
più a lungo.

**«Presente in archivio» non vuol dire «unica nuotata».** L'atleta ha corso
almeno tre event02 sui 10 km — place23, place05 e place21 — e Icron ne
espone una sola: le gare fuori dal circuito che quella piattaforma cronometra
semplicemente non ci sono. È la ragione per cui esiste
`ingest/declared_races.py`, e la ragione per cui ogni frase di questo modulo
dice **quante gare ha visto**, non quante l'atleta ne abbia nuotate. Le due cose
non coincidono e confonderle è il modo più veloce di fargli perdere fiducia in
un numero giusto.

Applicargli il 92% produrrebbe un passo obiettivo di circa un quarto più veloce
di qualunque cosa abbia mai tenuto in mare. Sarebbe un numero con una
bibliografia sotto, e sarebbe sbagliato.

## Cosa fa questo modulo, allora

Tre cose, in ordine di onestà decrescente:

1. **Misura la quota che questo atleta ha davvero tenuto**, gara per gara,
   accettando solo gli accoppiamenti in cui la velocità critica è abbastanza
   vicina nel tempo da descrivere la stessa persona.
2. **Mostra la banda della letteratura accanto**, etichettata come élite, così
   si vede la distanza fra le due — che è essa stessa un'informazione.
3. **Rifiuta di produrre un passo obiettivo** quando le condizioni non ci sono,
   e dice quali sono. Oggi non ci sono: le uniche quote utilizzabili vengono dal
   2016-17 e nessuna riguarda una distanza vicina ai 10 km.

La conseguenza pratica non è una frase di circostanza: c'è una prova precisa da
fare, ed è scritta in `why_unavailable`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

import duckdb

from . import critical_speed, race_history

# La banda della letteratura, e da dove viene.
#
# 92,3% è la quota tenuta dai primi dieci della 10 km ai Mondiali 2023 [OW-1].
# La banda 90-93% la allarga di poco attorno a quel valore. **Non è la banda di
# questo atleta**, ed è tenuta separata proprio per non confonderla con la sua:
# è un metro per capire quanto lontano sia, non un obiettivo da assegnargli.
LITERATURE_BAND = (0.90, 0.93)
LITERATURE_SOURCE = "primi dieci della 10 km ai Mondiali 2023 [OW-1]"

# Quanto può distare nel tempo la velocità critica dalla gara in mare perché il
# rapporto fra le due significhi qualcosa.
#
# Un anno è già molto — la forma cambia — ed è il massimo accettabile qui solo
# perché le coppie 400/200 in archivio sono sette in undici anni. Oltre, il
# numeratore e il denominatore descrivono due atleti diversi: il 10 km del 2019
# diviso per la velocità critica del 2016 dà 71,4%, e quel numero non misura il
# mare, misura tre anni di distanza.
MAX_PAIRING_GAP_DAYS = 365

# Quanto devono essere simili due distanze perché la quota dell'una dica
# qualcosa dell'altra. La quota cala con la distanza: usare un 1.500 per
# impostare un 10.000 significa partire troppo forte.
DISTANCE_TOLERANCE = 0.5

# Sotto questo numero di osservazioni non si propone una banda personale: due
# gare non sono una popolazione, e una banda costruita su due punti sembra una
# misura senza esserlo.
MIN_OBSERVATIONS = 3


@dataclass(frozen=True)
class Observation:
    """Una gara in mare, e a che frazione della propria soglia è stata nuotata."""

    day: date
    meet: str
    distance_m: int
    speed_ms: float
    css_day: date
    css_speed_ms: float
    gap_days: int

    @property
    def fraction(self) -> float:
        return self.speed_ms / self.css_speed_ms

    @property
    def usable(self) -> bool:
        return self.gap_days <= MAX_PAIRING_GAP_DAYS


def observations(connection: duckdb.DuckDBPyConnection) -> list[Observation]:
    """Ogni gara in mare credibile, accostata alla velocità critica più vicina.

    Entrano solo le gare con una distanza che regge — vedi `race_history` — e
    quindi con un passo che sia un passo. Una gara la cui distanza dichiarata è
    smentita dai tempi in vasca dell'atleta produrrebbe una quota inventata, e
    la quota è tutto ciò che questo modulo misura.
    """
    coppie = critical_speed.pairs(connection)
    if not coppie:
        return []

    trovate = []
    for gara in race_history.open_water(connection):
        if gara.credibility != race_history.CREDIBLE or not gara.speed_ms:
            continue
        vicina = min(coppie, key=lambda una: abs((una.day - gara.day).days))
        trovate.append(Observation(
            day=gara.day, meet=gara.meet, distance_m=gara.distance_m,
            speed_ms=gara.speed_ms,
            css_day=vicina.day, css_speed_ms=vicina.speed_ms,
            gap_days=abs((vicina.day - gara.day).days)))
    return sorted(trovate, key=lambda una: una.day, reverse=True)


def usable(connection: duckdb.DuckDBPyConnection,
           distance_m: int | None = None) -> list[Observation]:
    """Le osservazioni su cui ci si può appoggiare per una distanza data."""
    valide = [una for una in observations(connection) if una.usable]
    if distance_m is None:
        return valide
    minimo = distance_m * (1 - DISTANCE_TOLERANCE)
    massimo = distance_m * (1 + DISTANCE_TOLERANCE)
    return [una for una in valide if minimo <= una.distance_m <= massimo]


def personal_band(connection: duckdb.DuckDBPyConnection,
                  distance_m: int) -> tuple[float, float] | None:
    """La banda di quota che **questo** atleta ha tenuto su distanze simili.

    Il minimo e il massimo osservati, non una media: con tre o quattro gare la
    media nasconde quanto il mare cambi da un giorno all'altro, e la banda no.
    """
    valide = usable(connection, distance_m)
    if len(valide) < MIN_OBSERVATIONS:
        return None
    quote = [una.fraction for una in valide]
    return min(quote), max(quote)


def target_pace(connection: duckdb.DuckDBPyConnection,
                distance_m: int) -> tuple[float, float] | None:
    """Il passo obiettivo, in secondi per 100 m, come banda. `None` se non si sa.

    Il passo esce **solo** dalla banda personale. La banda della letteratura non
    viene mai usata per produrre un numero da dare all'atleta: serve a dire
    quanto è distante da quella d'élite, che è un'informazione diversa.
    """
    coppia = critical_speed.current(connection)
    banda = personal_band(connection, distance_m)
    if not coppia or not banda:
        return None
    lenta = 100 / (coppia.speed_ms * banda[0])
    veloce = 100 / (coppia.speed_ms * banda[1])
    return veloce, lenta


def why_unavailable(connection: duckdb.DuckDBPyConnection,
                    distance_m: int) -> str:
    """Perché non c'è un passo obiettivo, e quale prova lo produrrebbe.

    Un blocco che dice soltanto «dati insufficienti» è indistinguibile da un
    guasto e non si può sbloccare. Questo dice cosa manca e cosa fare, perché è
    l'unica forma in cui «non lo so ancora» resta una risposta utile.
    """
    if not critical_speed.current(connection):
        return ("Manca la velocità critica: senza un 400 e un 200 in vasca "
                "vicini nel tempo non c'è un denominatore.")

    tutte = observations(connection)
    if not tutte:
        return ("Non c'è nessuna gara in mare con una distanza che regga: "
                "senza distanza non c'è un passo da confrontare.")

    vicine = usable(connection, distance_m)
    if len(vicine) >= MIN_OBSERVATIONS:
        return ""

    lontane = [una for una in tutte if not una.usable]
    a_distanza_giusta = [una for una in tutte
                         if abs(una.distance_m - distance_m) / distance_m
                         <= DISTANCE_TOLERANCE]

    pezzi = [f"Servono almeno {MIN_OBSERVATIONS} gare in mare su una distanza "
             f"vicina ai {distance_m} m, ognuna con una velocità critica "
             f"misurata entro un anno. Adesso ce ne sono {len(vicine)}."]
    if a_distanza_giusta and not vicine:
        pezzi.append(
            f"Su distanze paragonabili hai gareggiato "
            f"{len(a_distanza_giusta)} volte, ma la velocità critica più "
            "vicina è di anni prima o dopo: il rapporto misurerebbe il tempo "
            "passato, non il mare.")
    elif lontane:
        pezzi.append(
            f"{len(lontane)} gare in mare restano fuori perché la velocità "
            "critica più vicina dista più di un anno.")
    pezzi.append(
        "La prova che lo sbloccherebbe: un 400 e un 200 a tutta in vasca — o "
        "una gara che li contenga — nella stessa stagione di una lunga in mare.")
    return " ".join(pezzi)


def summary(connection: duckdb.DuckDBPyConnection, distance_m: int) -> dict:
    """Tutto in una volta, per la pagina e per il pacchetto del coach."""
    coppia = critical_speed.current(connection)
    valide = usable(connection)
    quote = [una.fraction for una in valide]

    return {
        "available": target_pace(connection, distance_m) is not None,
        "why_unavailable": why_unavailable(connection, distance_m),
        "css_speed_ms": coppia.speed_ms if coppia else None,
        "observations": [{
            "day": una.day.strftime("%d/%m/%Y"),
            "meet": una.meet,
            "distance_m": una.distance_m,
            "fraction_pct": round(una.fraction * 100, 1),
            "gap_days": una.gap_days,
            "usable": una.usable,
        } for una in observations(connection)],
        "personal_median_pct": (round(statistics.median(quote) * 100, 1)
                                if quote else None),
        "literature_band_pct": (round(LITERATURE_BAND[0] * 100),
                                round(LITERATURE_BAND[1] * 100)),
        "literature_source": LITERATURE_SOURCE,
        "target_s_per_100m": target_pace(connection, distance_m),
    }
