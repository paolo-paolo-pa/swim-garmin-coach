"""Il confine fra ciò che si misura e ciò che si giudica.

## Perché esiste un contratto e non una chiamata

Un modello che riceve dati e restituisce testo è utile e non è verificabile. Fra
«HRV nella fascia, volume in crescita, gara fra 42 giorni» e «puoi spingere»
c'è un salto che nessuno può controllare dopo, perché il testo non dice su cosa
si appoggia.

Qui il salto è dichiarato in due pezzi.

``CoachContextPacket`` è **tutto** ciò che il giudizio può usare: fatti già
calcolati, ognuno con la propria identità, unità, finestra e copertura. Se un
numero non è nel pacchetto, non esiste per chi giudica.

``CoachingResponse`` è il giudizio, e ogni sua affermazione porta gli
identificativi delle evidenze su cui poggia. Una risposta che cita un numero
non presente nel pacchetto viene **rifiutata**, non corretta: un modello che
inventa un numero plausibile è più pericoloso di uno che sbaglia in modo
evidente.

## Cosa questo contratto non prova

Non prova che il giudizio sia giusto. Prova che è tracciabile: che ogni cifra
mostrata all'atleta viene da una funzione Python testata, e che si può risalire
da una frase ai fatti che l'hanno prodotta. È meno di quanto si vorrebbe ed è
tutto quello che si può garantire.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date

# Versione del contratto. Cambia quando cambiano i campi obbligatori: una
# risposta prodotta con la versione di ieri non va letta come una di oggi.
VERSION = "2"

CONFIDENCE = ("high", "moderate", "low")


class InvalidResponse(ValueError):
    """La risposta non rispetta il contratto e non viene mostrata.

    Correggerla sarebbe peggio: nasconderebbe che è stata prodotta male, e la
    prossima volta nessuno se ne accorgerebbe.
    """


@dataclass(frozen=True)
class Fact:
    """Un numero, con tutto ciò che serve a sapere cosa significa.

    ``fact_id`` è il nome con cui il giudizio lo cita. ``window`` è la parte che
    veniva dimenticata più spesso: senza, «21,78 km» e «8,9 km» sembrano la
    stessa grandezza e non lo sono (vedi l'audit §A3).
    """

    fact_id: str
    label: str
    value: object
    unit: str
    display: str
    window: str
    availability: str = "available"
    n: int | None = None
    expected_n: int | None = None
    why: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CoachContextPacket:
    """Tutto ciò che il giudizio può usare, e niente di più.

    Non contiene coordinate GPS, non contiene il nome dell'atleta, non contiene
    file grezzi. Contiene numeri già calcolati e le frasi che l'atleta ha scritto
    di suo pugno in ``coach/``.
    """

    question: str
    observation_date: date
    goal: dict = field(default_factory=dict)
    phase: dict = field(default_factory=dict)
    training: dict = field(default_factory=dict)
    recovery: dict = field(default_factory=dict)
    data_quality: dict = field(default_factory=dict)
    historical_analogs: list = field(default_factory=list)
    candidate_actions: list = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.fact_id == fact_id), None)

    @property
    def known_ids(self) -> set[str]:
        return {f.fact_id for f in self.facts}

    def as_dict(self) -> dict:
        corpo = {
            "version": VERSION,
            "question": self.question,
            "observation_date": self.observation_date.isoformat(),
            "goal": self.goal,
            "phase": self.phase,
            "training": self.training,
            "recovery": self.recovery,
            "data_quality": self.data_quality,
            "historical_analogs": self.historical_analogs,
            "candidate_actions": self.candidate_actions,
            "facts": [f.as_dict() for f in self.facts],
            "limitations": self.limitations,
        }
        corpo["digest"] = self.digest
        return corpo

    @property
    def digest(self) -> str:
        """L'impronta del contenuto.

        Serve a due cose che sembrano una: riconoscere una risposta vecchia
        quando i dati sono cambiati, e poter dimostrare su quali fatti esatti è
        stata data. Senza, «il coach aveva detto» non è verificabile.
        """
        materiale = json.dumps(
            {"v": VERSION, "q": self.question,
             "d": self.observation_date.isoformat(),
             "g": self.goal, "p": self.phase, "t": self.training,
             "r": self.recovery, "dq": self.data_quality,
             "h": self.historical_analogs,
             "a": self.candidate_actions,
             "f": [f.as_dict() for f in self.facts],
             "l": self.limitations},
            sort_keys=True, default=str)
        return hashlib.sha256(materiale.encode()).hexdigest()[:16]


@dataclass
class CoachingResponse:
    """Il giudizio, con i suoi appigli.

    I campi non sono decorativi. ``what_to_avoid`` esiste perché un consiglio
    senza il proprio contrario è un'esortazione; ``counterpoints`` perché una
    conclusione senza ciò che la contraddice non è stata pensata;
    ``questions_for_athlete`` perché la cosa che manca più spesso non è un dato
    ma un'informazione che solo l'atleta ha.
    """

    verdict: str
    primary_focus: str
    focus_drift: str = "incerto"          # sì | no | incerto
    focus_drift_why: str = ""
    what_is_working: list[str] = field(default_factory=list)
    what_needs_attention: list[str] = field(default_factory=list)
    actions_next_7_days: list[str] = field(default_factory=list)
    direction_next_21_days: list[str] = field(default_factory=list)
    scenario_next_42_days: list[str] = field(default_factory=list)
    what_to_avoid: list[str] = field(default_factory=list)
    confidence: str = "low"
    why: list[str] = field(default_factory=list)          # fact_id
    counterpoints: list[str] = field(default_factory=list)  # fact_id
    questions_for_athlete: list[str] = field(default_factory=list)
    boundary: list[str] = field(default_factory=list)
    next_check: str = ""
    packet_digest: str = ""
    model: str = ""
    generated_on: date | None = None

    def as_dict(self) -> dict:
        corpo = asdict(self)
        corpo["generated_on"] = (self.generated_on.isoformat()
                                 if self.generated_on else None)
        return corpo


# ── Il validatore ────────────────────────────────────────────────────────

# Le parole con cui una lettura diventa una diagnosi. Il progetto non le usa e
# non le lascia usare: non c'è nessun dato in questo archivio che autorizzi a
# dire a una persona che si sta infortunando.
FORBIDDEN = (
    "infortun", "lesion", "tendinit", "patolog", "diagnos", "sindrome",
    "ti stai facendo male", "rischio di rottura",
)

# Le parole con cui una correlazione diventa una causa. Sono ammesse solo se la
# frase porta anche un'incertezza dichiarata: «probabilmente», «sembra».
CAUSAL = ("perché ha causato", "è la causa di", "ha provocato", "dimostra che")

# I numeri che non hanno bisogno di essere nel pacchetto: sono riferimenti al
# calendario del consiglio stesso, non misure.
ALLOWED_BARE_NUMBERS = {"7", "21", "42", "24", "48", "72"}

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers_in(text: str) -> set[str]:
    return {m.group() for m in _NUMBER.finditer(text or "")}


def _numbers_the_packet_knows(packet: CoachContextPacket) -> set[str]:
    conosciuti: set[str] = set(ALLOWED_BARE_NUMBERS)
    for fatto in packet.facts:
        conosciuti |= _numbers_in(fatto.display)
        conosciuti |= _numbers_in(str(fatto.value))
        conosciuti |= _numbers_in(fatto.window)
    for blocco in (packet.goal, packet.phase, packet.training, packet.recovery,
                   packet.data_quality):
        conosciuti |= _numbers_in(json.dumps(blocco, default=str))
    for voce in packet.historical_analogs + packet.candidate_actions:
        conosciuti |= _numbers_in(json.dumps(voce, default=str))
    for limite in packet.limitations:
        conosciuti |= _numbers_in(limite)
    return conosciuti


def _prose(response: CoachingResponse) -> list[str]:
    return [response.verdict, response.primary_focus, response.focus_drift_why,
            response.next_check, *response.what_is_working,
            *response.what_needs_attention, *response.actions_next_7_days,
            *response.direction_next_21_days, *response.scenario_next_42_days,
            *response.what_to_avoid, *response.questions_for_athlete]


def validate(response: CoachingResponse, packet: CoachContextPacket) -> None:
    """Solleva ``InvalidResponse`` se la risposta non si può mostrare.

    Cinque controlli, in ordine di gravità.
    """
    if not response.verdict.strip() or not response.primary_focus.strip():
        raise InvalidResponse(
            "La risposta non ha un verdetto o non ha un focus. Sono i due campi "
            "per cui esiste: senza, è un riassunto dei dati.")

    if response.confidence not in CONFIDENCE:
        raise InvalidResponse(
            f"Confidenza «{response.confidence}»: le uniche ammesse sono "
            f"{', '.join(CONFIDENCE)}. Un valore libero diventa un punteggio, e "
            "un punteggio suggerisce una precisione che non c'è.")

    testo = " ".join(_prose(response)).lower()
    for vietata in FORBIDDEN:
        if vietata in testo:
            raise InvalidResponse(
                f"La risposta contiene «{vietata}»: è una diagnosi. Questo "
                "progetto non ne produce, e nessun dato qui dentro la "
                "autorizzerebbe.")
    for causale in CAUSAL:
        if causale in testo:
            raise InvalidResponse(
                f"La risposta dice «{causale}»: è una causa dichiarata da una "
                "correlazione. Va riscritta come osservazione.")

    sconosciuti = sorted(set(response.why + response.counterpoints)
                         - packet.known_ids)
    if sconosciuti:
        raise InvalidResponse(
            f"La risposta cita evidenze che non esistono: {sconosciuti}. "
            "Un appiglio inventato è peggio di nessun appiglio, perché sembra "
            "verificabile.")

    inventati = sorted(_numbers_in(" ".join(_prose(response)))
                       - _numbers_the_packet_knows(packet))
    if inventati:
        raise InvalidResponse(
            f"La risposta contiene numeri che non sono nel pacchetto: "
            f"{inventati}. Un numero plausibile e inventato è più pericoloso di "
            "un errore evidente, perché nessuno lo controlla.")

    if not response.why:
        raise InvalidResponse(
            "Nessuna evidenza a sostegno. Un verdetto senza appigli non è "
            "verificabile e non va mostrato.")
