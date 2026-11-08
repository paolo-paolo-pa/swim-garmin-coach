"""«Ho fatto quello che dovevo fare?»

## La metà che mancava

Il secondo audit ha registrato A6 come **PARTIAL** per una ragione precisa: il
ciclo previsto → eseguito → risposta era fermo a due terzi. L'*eseguito* c'è —
lo registra l'orologio — e la *risposta* c'è, nei tre assi di `adaptation.py`.
Il **previsto** non c'era, e non per un limite tecnico: nessun dato al mondo
contiene l'intenzione di chi scrive l'allenamento.

Adesso c'è un posto dove scriverla, `coach/programma-settimanale.md`, e questo
modulo la confronta con quello che è successo davvero.

## Cosa confronta, e cosa no

**Confronta la presenza e il volume.** La seduta prevista per martedì c'è stata?
Con quanti metri rispetto a quelli previsti? Sono due domande a cui i dati
rispondono senza interpretare niente.

**Non confronta l'intensità.** «Era prevista soglia, l'hai fatta a soglia?»
richiederebbe di sapere in che zona si è nuotato, e le zone cardiache di questo
atleta non sono affidabili — lo dimostra `heart_rate_zones.py`. Quello che si
può fare, e si fa, è **attribuire l'intento alla seduta reale**, così che
«com'è andata la soglia di martedì» diventi una domanda con una risposta invece
che una ricerca a memoria.

**Non giudica il programma.** Uno scarto fra previsto ed eseguito è un fatto da
guardare con l'allenatore, non un errore. Il progetto non genera programmi e non
sostituisce chi li scrive.

## Perché l'accoppiamento è per giorno e non per somiglianza

Perché il giorno è l'unica cosa che l'allenatore e l'orologio scrivono allo
stesso modo. Accoppiare per volume o per struttura significherebbe decidere che
la seduta da 2.800 m di mercoledì «era» quella da 3.000 prevista martedì — e
quella decisione, presa da un programma, diventa invisibile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from .. import athlete_files

# Sotto questa quota di metri la seduta prevista si considera non svolta invece
# che ridotta. Un terzo del previsto non è la stessa seduta più corta: è
# un'altra cosa, tipicamente un ripiego o un'interruzione.
DONE_MIN_SHARE = 0.5

# Quanto può scostarsi il volume perché la seduta valga come «fatta come
# prevista». Il ±15% copre il fatto che nessuno nuota esattamente i metri
# scritti su un foglio.
ON_PLAN_TOLERANCE = 0.15


@dataclass(frozen=True)
class Comparison:
    """Una seduta prevista e ciò che le è successo."""

    day: date
    planned_m: int | None
    planned_purpose: str
    planned_detail: str
    done_m: int | None
    activity_id: int | None
    # Il giorno è ancora in corso? Una seduta prevista per stasera e non ancora
    # nuotata non è una seduta saltata: è una seduta che deve ancora arrivare.
    # Senza questa distinzione il briefing del pomeriggio accusa l'atleta di
    # aver mancato un allenamento che ha in programma fra tre ore.
    still_open: bool = False

    @property
    def status(self) -> str:
        if self.done_m is None:
            return "ancora da fare" if self.still_open else "non svolta"
        if self.planned_m is None:
            return "svolta"
        quota = self.done_m / self.planned_m
        if quota < DONE_MIN_SHARE:
            return "molto ridotta"
        if abs(quota - 1) <= ON_PLAN_TOLERANCE:
            return "come prevista"
        return "più lunga" if quota > 1 else "più corta"

    @property
    def delta_m(self) -> int | None:
        if self.done_m is None or self.planned_m is None:
            return None
        return self.done_m - self.planned_m

    @property
    def display(self) -> str:
        if self.done_m is None and self.still_open:
            quanto = "il giorno non è finito"
        elif self.done_m is None:
            quanto = "nessuna nuotata registrata"
        elif self.planned_m is None:
            quanto = f"{self.done_m} m nuotati, nessun volume previsto"
        else:
            quanto = (f"{self.done_m} m su {self.planned_m} previsti "
                      f"({self.delta_m:+d} m)")
        return f"{self.planned_purpose} — {quanto}"


def available() -> bool:
    """C'è un programma da confrontare?"""
    return bool(athlete_files.planned_sessions())


def compare(connection: duckdb.DuckDBPyConnection,
            weeks: int = 4, today: date | None = None) -> list[Comparison]:
    """Il previsto contro l'eseguito, giorno per giorno."""
    oggi = today or date.today()
    previste = [una for una in athlete_files.planned_sessions(weeks, oggi)
                if una.day <= oggi]
    if not previste:
        return []

    inizio = min(una.day for una in previste)
    righe = connection.execute("""
        SELECT activity_date, activity_id, distance_m
        FROM canonical_activities
        WHERE is_swim AND activity_date BETWEEN ? AND ?
        ORDER BY activity_date, distance_m DESC
    """, [inizio, oggi]).fetchall()

    # Una sola seduta per giorno: la più lunga. Quando in un giorno ce ne sono
    # due, il programma ne prevedeva una, e accoppiare la prevista con la più
    # corta darebbe «molto ridotta» su una giornata in cui si è nuotato di più.
    per_giorno: dict[date, tuple] = {}
    for giorno, activity_id, metri in righe:
        per_giorno.setdefault(giorno, (activity_id, metri))

    confronti = []
    for una in previste:
        fatta = per_giorno.get(una.day)
        confronti.append(Comparison(
            day=una.day,
            planned_m=una.distance_m,
            planned_purpose=una.purpose,
            planned_detail=una.detail,
            done_m=int(fatta[1]) if fatta and fatta[1] else None,
            activity_id=int(fatta[0]) if fatta else None,
            still_open=una.day == oggi))
    return confronti


def purpose_of(connection: duckdb.DuckDBPyConnection,
               activity_id: int) -> str | None:
    """L'intento dichiarato per una seduta reale, se il programma lo contiene.

    È la funzione che trasforma «com'è andata martedì» in «com'è andata la
    soglia di martedì», e non richiede nessuna inferenza: l'allenatore l'ha
    scritto, il giorno coincide.
    """
    riga = connection.execute("""
        SELECT activity_date FROM canonical_activities WHERE activity_id = ?
    """, [activity_id]).fetchone()
    if not riga:
        return None
    for una in athlete_files.planned_sessions(weeks=520, today=riga[0]
                                              + timedelta(days=1)):
        if una.day == riga[0] and una.purpose != "non dichiarato":
            return una.purpose
    return None


def summary(connection: duckdb.DuckDBPyConnection,
            weeks: int = 4, today: date | None = None) -> dict:
    """Il quadro per la pagina, già in parole."""
    confronti = compare(connection, weeks, today)
    if not confronti:
        return {
            "available": False,
            "why": ("Il programma dell'allenatore non è ancora scritto. È in "
                    "coach/programma-settimanale.md, bastano tre colonne, e "
                    "senza di esso «ho fatto quello che dovevo?» non ha "
                    "risposta — non per un limite dei dati, ma perché "
                    "l'intenzione non la registra nessun orologio."),
        }

    # La seduta di stasera non entra nel conteggio finché non è stata nuotata:
    # contarla fra le previste mentre è ancora in programma farebbe leggere
    # «3 su 4» a chi non ha ancora mancato niente. Resta però in «sessions»,
    # perché all'atleta serve vederla. Appena la nuotata arriva — anche in
    # ritardo, quando il sync di Garmin recupera la sera stessa — la seduta
    # rientra nel conteggio come tutte le altre: escluderla anche da nuotata
    # farebbe sparire i suoi metri dal totale della settimana.
    contate = [una for una in confronti if una.status != "ancora da fare"]
    svolte = [una for una in contate if una.done_m is not None]
    previsti = sum(una.planned_m or 0 for una in contate)
    fatti = sum(una.done_m or 0 for una in svolte)

    return {
        "available": True,
        "weeks": weeks,
        "planned": len(contate),
        "done": len(svolte),
        "planned_m": previsti,
        "done_m": fatti,
        "headline": (
            "Niente da confrontare: l'unica seduta prevista è quella di oggi"
            if not contate else
            f"{len(svolte)} sedute su {len(contate)} previste, "
            f"{fatti:,} m su {previsti:,} previsti".replace(",", ".")
            if previsti else
            f"{len(svolte)} sedute su {len(contate)} previste"),
        "sessions": [{
            "day": una.day.strftime("%d/%m/%Y"),
            "purpose": una.planned_purpose,
            "planned": una.planned_detail or "—",
            "status": una.status,
            "display": una.display,
            "activity_id": una.activity_id,
        } for una in confronti],
        "caveat": (
            "Il confronto riguarda presenza e volume. **Non** riguarda "
            "l'intensità: dire se la soglia era davvero soglia richiederebbe "
            "zone cardiache affidabili, e non lo sono."),
    }
