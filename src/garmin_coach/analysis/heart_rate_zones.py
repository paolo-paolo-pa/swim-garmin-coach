"""«Le mie zone cardiache descrivono qualcosa?»

## La risposta breve è no, e qui c'è il perché misurato

Non è un'opinione sulla frequenza cardiaca in acqua: sono tre fatti che
l'archivio contiene già, e ognuno da solo basterebbe.

**1. L'orologio tiene due definizioni di zone, e non concordano.** In
`hr_zones` ci sono due righe: una `DEFAULT` costruita sulla riserva cardiaca,
con la terza zona che comincia a una certa soglia, e una `SWIMMING` costruita sulla
percentuale del massimo, con la terza zona che comincia molto più in basso. La stessa seduta
cade in zone diverse a seconda di quale si guarda. Una scala che dà due risposte
non è una scala.

**2. Il massimo è stimato, e le zone ne ereditano l'errore.** `220 − età` ha un
errore tipico di ±10-12 bpm sulla singola persona [FC-2]. Ogni confine di zona è
una percentuale di quel numero: se il massimo è sbagliato di dieci battiti,
tutti i confini si spostano insieme.

**3. In acqua il massimo è più basso, e le zone non lo sanno.** La FC massima in
nuoto è 6,7 ± 5,3 bpm più bassa che nella corsa in nuotatori allenati [FC-1], e
a parità di consumo di ossigeno la FC in acqua è 10-15 bpm più bassa [FC-3]. Una
scala tarata a secco colloca sistematicamente una nuotata in una zona più bassa
di quella in cui il corpo sta davvero lavorando.

## Cosa resta utilizzabile

Non niente. La frequenza cardiaca **cambia** in modo informativo anche quando il
suo valore assoluto non è collocabile: a parità di passo e di vasca, una FC più
alta di dieci battiti su una serie che si ripete uguale è un segnale, e non
dipende da dove passa il confine fra la zona 2 e la zona 3.

È la differenza fra «in che zona ero» — non lo sappiamo — e «oggi mi è costato
di più di tre settimane fa», che si può misurare.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from ..database import table_exists

# Quanto vale l'errore tipico della formula «220 − età» su una singola persona.
# Non è una scelta: è l'ordine di grandezza riportato in letteratura [FC-2].
ESTIMATED_MAX_ERROR_BPM = 12

# Di quanto la FC massima in nuoto sta sotto quella a secco [FC-1].
SWIMMING_MAX_OFFSET_BPM = 7

# Oltre questo valore una lettura al polso in acqua è un artefatto, non un
# battito: la stessa soglia oltre cui l'atleta stesso ha dichiarato di non
# credere ai 214 bpm registrati.
IMPLAUSIBLE_MAX_BPM = 200


@dataclass(frozen=True)
class Definition:
    """Una delle definizioni di zone memorizzate sull'orologio."""

    sport: str
    method: str
    max_bpm: float
    rest_bpm: float
    boundaries: tuple[float, ...]

    @property
    def label(self) -> str:
        metodo = ("riserva cardiaca" if "RESERVE" in (self.method or "")
                  else "percentuale del massimo")
        return f"{self.sport.lower()}, su {metodo}"


@dataclass
class Assessment:
    """Il verdetto sulle zone, con le prove che lo sostengono."""

    usable: bool = False
    definitions: list[Definition] = field(default_factory=list)
    observed_max_bpm: float | None = None
    plausible_max_bpm: float | None = None
    configured_max_bpm: float | None = None
    sessions_with_hr: int = 0
    reasons: list[str] = field(default_factory=list)
    what_still_works: list[str] = field(default_factory=list)


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "hr_zones")


def definitions(connection: duckdb.DuckDBPyConnection) -> list[Definition]:
    if not available(connection):
        return []
    righe = connection.execute("""
        SELECT sport, method, max_hr_used, resting_hr_used,
               zone1_floor, zone2_floor, zone3_floor, zone4_floor, zone5_floor
        FROM hr_zones ORDER BY sport
    """).fetchall()
    return [Definition(sport=r[0], method=r[1], max_bpm=r[2], rest_bpm=r[3],
                       boundaries=tuple(v for v in r[4:] if v is not None))
            for r in righe]


def disagree(elenco: list[Definition]) -> bool:
    """Due definizioni discordano se collocano lo stesso battito altrove."""
    confini = {una.boundaries for una in elenco}
    return len(confini) > 1


def zone_of(definizione: Definition, bpm: float) -> int:
    """In quale zona cade un battito, secondo una definizione.

    Serve a mostrare il disaccordo con un esempio invece che con una tabella:
    «136 bpm è zona 0 secondo una e zona 2 secondo l'altra» si capisce subito.
    """
    return sum(1 for confine in definizione.boundaries if bpm >= confine)


def observed_max(connection: duckdb.DuckDBPyConnection) -> tuple:
    """Il massimo osservato nuotando, e quello plausibile.

    Sono due numeri diversi e vanno tenuti separati: il massimo assoluto
    contiene gli artefatti della lettura al polso in acqua, il 95° percentile
    no. Mostrare solo il primo esagera, mostrare solo il secondo nasconde.
    """
    riga = connection.execute("""
        SELECT max(max_hr_bpm),
               quantile_cont(max_hr_bpm, 0.95),
               count(*)
        FROM canonical_activities
        WHERE is_swim AND max_hr_bpm IS NOT NULL
    """).fetchone()
    return riga if riga else (None, None, 0)


def time_in_zones(connection: duckdb.DuckDBPyConnection,
                  days: int = 90, today: date | None = None) -> list[float]:
    """Ore per zona nelle sedute di nuoto recenti, secondo l'orologio."""
    fino = today or date.today()
    riga = connection.execute("""
        SELECT coalesce(sum(hr_zone_0_s), 0) / 3600.0,
               coalesce(sum(hr_zone_1_s), 0) / 3600.0,
               coalesce(sum(hr_zone_2_s), 0) / 3600.0,
               coalesce(sum(hr_zone_3_s), 0) / 3600.0,
               coalesce(sum(hr_zone_4_s), 0) / 3600.0,
               coalesce(sum(hr_zone_5_s), 0) / 3600.0
        FROM canonical_activities
        WHERE is_swim AND activity_date BETWEEN ? AND ?
    """, [fino - timedelta(days=days), fino]).fetchone()
    return list(riga) if riga else [0.0] * 6


def assess(connection: duckdb.DuckDBPyConnection,
           today: date | None = None) -> Assessment:
    """Il verdetto, con le prove. Non dà zone corrette: dice che non ci sono.

    Correggerle richiederebbe un massimo misurato, e questo modulo non lo
    inventa. Dice esattamente cosa manca, perché è l'unica forma in cui «non
    sono affidabili» resta una risposta con cui si può fare qualcosa.
    """
    quadro = Assessment()
    quadro.definitions = definitions(connection)
    if not quadro.definitions:
        # Tabella assente e tabella vuota sono la stessa cosa per chi legge:
        # le zone dell'orologio non ci sono, e non c'è niente da giudicare.
        quadro.reasons.append(
            "Le zone impostate sull'orologio non sono in archivio.")
        return quadro

    assoluto, plausibile, quante = observed_max(connection)
    quadro.observed_max_bpm = assoluto
    quadro.plausible_max_bpm = plausibile
    quadro.sessions_with_hr = int(quante or 0)
    quadro.configured_max_bpm = (quadro.definitions[0].max_bpm
                                 if quadro.definitions else None)

    if len(quadro.definitions) > 1 and disagree(quadro.definitions):
        prima, seconda = quadro.definitions[0], quadro.definitions[1]
        esempio = 136
        quadro.reasons.append(
            f"L'orologio tiene {len(quadro.definitions)} definizioni di zone e "
            f"non concordano: {esempio} bpm è zona "
            f"{zone_of(prima, esempio)} secondo «{prima.label}» e zona "
            f"{zone_of(seconda, esempio)} secondo «{seconda.label}». Una scala "
            "che dà due risposte non è una scala.")

    if quadro.configured_max_bpm:
        quadro.reasons.append(
            f"Il massimo impostato è {quadro.configured_max_bpm:.0f} bpm e non "
            "viene da un test: la formula 220 − età sbaglia tipicamente di "
            f"±{ESTIMATED_MAX_ERROR_BPM} bpm su una persona sola, e ogni "
            "confine di zona è una percentuale di quel numero.")

    quadro.reasons.append(
        f"In acqua il massimo è più basso di circa {SWIMMING_MAX_OFFSET_BPM} "
        "bpm rispetto a secco, e la scala non lo tiene in conto: una nuotata "
        "cade sistematicamente in una zona più bassa di dove sta lavorando.")

    if assoluto and assoluto > IMPLAUSIBLE_MAX_BPM:
        quadro.reasons.append(
            f"Il massimo registrato nuotando è {assoluto:.0f} bpm, che la "
            "lettura al polso in acqua produce come artefatto. Il 95° "
            f"percentile, {plausibile:.0f} bpm, è il numero da guardare.")

    quadro.what_still_works.append(
        "Il confronto della frequenza **a parità di passo e di vasca**: dieci "
        "battiti in più sulla stessa serie ripetuta è un segnale, e non "
        "dipende da dove passa il confine fra due zone.")
    quadro.what_still_works.append(
        "L'andamento della frequenza a riposo e della variabilità notturna, "
        "che non usano le zone.")

    # Le zone sono utilizzabili solo se esiste una definizione sola e un
    # massimo misurato. Nessuna delle due condizioni è vera oggi, e finché
    # restano false il verdetto non cambia.
    quadro.usable = False
    return quadro


def as_page_dict(connection: duckdb.DuckDBPyConnection,
                 today: date | None = None) -> dict:
    quadro = assess(connection, today)
    ore = time_in_zones(connection, today=today)
    totale = sum(ore)
    return {
        "usable": quadro.usable,
        "reasons": list(quadro.reasons),
        "what_still_works": list(quadro.what_still_works),
        "sessions_with_hr": quadro.sessions_with_hr,
        "observed_max": (f"{quadro.observed_max_bpm:.0f} bpm"
                         if quadro.observed_max_bpm else "—"),
        "plausible_max": (f"{quadro.plausible_max_bpm:.0f} bpm"
                          if quadro.plausible_max_bpm else "—"),
        "configured_max": (f"{quadro.configured_max_bpm:.0f} bpm"
                           if quadro.configured_max_bpm else "—"),
        "hours_per_zone": [{
            "zone": indice,
            "hours": round(valore, 1),
            "share": (f"{valore / totale * 100:.0f}%" if totale else "—"),
        } for indice, valore in enumerate(ore)],
        "what_would_fix_it": (
            "Un test massimale — in acqua, non a secco — e una sola "
            "definizione di zone sull'orologio. Finché mancano, il coach "
            "ragiona su passo e fatica percepita."),
    }
