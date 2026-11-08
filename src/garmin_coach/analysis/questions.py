"""«Posso fare una domanda non prevista dal menu?» (fase 4.5).

## Che cosa fa questo file, e cosa non fa

Prepara **domande** e **pacchetti compatti di evidenza**. Non parla con nessun
modello: l'incarico non autorizza una chat incorporata, e questa esecuzione non
la costruisce nemmeno disattivata.

Il percorso è quello che funziona senza chiavi, senza rete e senza spesa:
l'atleta copia una domanda già scritta, con dentro gli identificativi e il
periodo giusti, e la incolla in Claude — dove i sette strumenti MCP leggono lo
stesso database.

## Perché non si copia il JSON

Incollare un riepilogo grezzo di trecento righe fa due danni: riempie il
contesto di roba che il modello non userà, e porta fuori dal computer più dati
di quanti la domanda ne richieda. Qui si copia una frase con dentro gli
**identificativi**: sarà lo strumento MCP, sul computer dell'atleta, a leggere
il resto.

## Le domande dipendono da dove ti trovi

Una domanda suggerita su una pagina che l'atleta non sta guardando è un menu.
Una domanda che parla della seduta aperta in quel momento è un aiuto. Per
questo ogni area produce le sue, con i propri identificativi già dentro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Question:
    """Una domanda pronta da incollare in Claude."""

    text: str
    why: str
    tool: str

    def as_dict(self) -> dict:
        return {"text": self.text, "why": self.why, "tool": self.tool}


def _giorno(day: date | None) -> str:
    return day.strftime("%d/%m/%Y") if day else "oggi"


def for_today(day: date | None, status: str) -> list[Question]:
    """Le domande che hanno senso guardando la pagina Oggi."""
    domande = [
        Question(
            f"Guarda il briefing del {_giorno(day)} e dimmi se c'è qualcosa che "
            "non torna fra i segnali di recupero e il carico delle ultime due "
            "settimane.",
            "il coach locale confronta i segnali con la tua fascia personale; "
            "Claude può leggerli insieme e dire se raccontano la stessa storia",
            "briefing"),
        Question(
            "Confronta le ultime quattro settimane con le quattro precedenti, e "
            "rifiuta esplicitamente i confronti che i dati non reggono.",
            "compare dichiara da solo quali confronti sono illeciti: "
            "dispositivi diversi, vasche diverse, copertura della frequenza "
            "cardiaca insufficiente",
            "compare"),
    ]
    if status == "watch":
        domande.insert(0, Question(
            f"Il coach ha segnalato qualcosa per il {_giorno(day)}. Leggi il "
            "briefing e dimmi che domanda porterei all'allenatore.",
            "l'osservazione locale è descrittiva; l'interpretazione e la domanda "
            "da girare all'allenatore sono giudizio",
            "briefing"))
    return domande


def for_session(activity_id: int, day: date | None,
                groups: list[dict]) -> list[Question]:
    """Le domande che hanno senso con una seduta aperta."""
    domande = [
        Question(
            f"Apri la seduta {activity_id} del {_giorno(day)} e spiegami come è "
            "andata dentro, lap per lap.",
            "session restituisce i lap veri, non serie ricostruite",
            "session"),
    ]
    principale = next((g for g in groups if "repeats" in g), None)
    if principale:
        domande.append(Question(
            f"Nella seduta {activity_id} il gruppo più numeroso è "
            f"{principale['label']}. Confrontalo con ripetute davvero simili "
            "delle ultime otto settimane.",
            "il confronto è lecito solo a parità di vasca, dispositivo, stile e "
            "distanza: chiedilo esplicitamente",
            "swim_history"))
    return domande


def for_progress(cases: list[dict]) -> list[Question]:
    """Le domande che hanno senso guardando i Progressi."""
    if not cases:
        return [Question(
            "Le ultime quattro settimane non hanno precedenti simili "
            "nell'archivio. Guarda la storia e dimmi se è un volume nuovo per "
            "me o solo un periodo insolito.",
            "swim_history copre nove anni: la risposta esiste anche quando la "
            "somiglianza automatica non trova nulla",
            "swim_history")]
    primo = cases[0]
    return [
        Question(
            f"Nel periodo {primo['display']} avevo un volume simile a quello di "
            "adesso. Guarda cosa è successo nelle quattro settimane dopo e "
            "dimmi in cosa quel periodo era diverso da questo.",
            "il coach locale descrive cosa è successo; le differenze di contesto "
            "sono giudizio",
            "swim_history"),
        Question(
            "Confronta le ultime quattro settimane con "
            f"{primo['display']}, dichiarando i confronti che rifiuti.",
            "attraversa epoche del dato diverse: il rifiuto dei confronti "
            "illeciti è la parte importante",
            "compare"),
    ]


def for_race(race_name: str | None, days_away: int | None,
             has_references: bool) -> list[Question]:
    """Le domande che hanno senso guardando una gara."""
    if not race_name:
        return [Question(
            "Non ho gare dichiarate. Guarda il mio storico e dimmi che tipo di "
            "prova avrebbe senso mettere in calendario.",
            "athlete_context legge profilo e obiettivi scritti da me",
            "athlete_context")]
    domande = [Question(
        f"Preparo {race_name}, fra {days_away} giorni. Guarda il lavoro "
        "specifico delle ultime otto settimane e dimmi cosa è favorevole, cosa "
        "è contrario e cosa non è misurabile.",
        "race_readiness porta i fatti; la lettura di cosa manca è giudizio",
        "race_readiness")]
    if not has_references:
        domande.append(Question(
            "Non ho ancora confermato nessun tempo. Guarda le mie sedute e "
            "proponimi i candidati che ti sembrano prove massimali: li confermo "
            "io.",
            "il coach non promuove da solo una nuotata veloce a prova "
            "massimale, ma può proporla",
            "swim_history"))
    return domande


HOW_IT_WORKS = (
    "Copia la domanda e incollala in Claude, dove il coach ha accesso ai sette "
    "strumenti su questo stesso database. Non parte niente da qui: l'unica cosa "
    "che esce da questo computer è il testo che incolli tu, quando lo incolli."
)
