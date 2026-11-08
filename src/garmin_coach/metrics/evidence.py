"""Un numero non viaggia mai da solo (D7).

## Il problema

`hrv_delta_pct = 8.2` non è un'informazione sufficiente per decidere niente.
Manca tutto quello che serve a sapere se ci si può contare: su quanti giorni è
calcolata la baseline, quanti ne servivano, di che periodo si parla, e se il
metodo è quello di oggi o quello di sei mesi fa.

Senza queste cose il coach può solo credere al numero. Con queste, può dire
*«non lo so ancora»* — che è la risposta giusta più spesso di quanto sembri.

## Le sei ragioni per cui un numero non c'è

`NULL` nel database, ma negli output il vuoto porta la sua causa: «non ce l'ho»
e «non esiste» non sono la stessa risposta, e trattarle allo stesso modo è come
dire che una vasca in mare è un dato mancante.

## L'evidenza non è la copertura

Un dato completo su tre casi resta debole; un dato al 70% su duecento casi è
solido. Il grado di evidenza tiene conto di entrambi, e non diventa mai un
punteggio da zero a cento: sono quattro parole, perché quattro parole non
suggeriscono una precisione che non esiste.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class Availability:
    """Perché un numero c'è o non c'è."""

    AVAILABLE = "available"
    MISSING = "missing"                    # la sorgente poteva contenerlo, non lo contiene
    NOT_APPLICABLE = "not_applicable"      # il concetto non vale qui: vasche in mare
    INSUFFICIENT_DATA = "insufficient_data"  # i dati ci sono, non bastano al calcolo
    INVALID = "invalid"                    # non ha superato i controlli di plausibilità
    STALE = "stale"                        # esiste, ma è troppo vecchio per la domanda

    SPIEGAZIONI = {
        AVAILABLE: "disponibile",
        MISSING: "la sorgente non lo contiene",
        NOT_APPLICABLE: "non si applica in questo contesto",
        INSUFFICIENT_DATA: "i dati non bastano per calcolarlo",
        INVALID: "il valore non ha superato i controlli di plausibilità",
        STALE: "esiste ma è troppo vecchio per questa domanda",
    }


class Evidence:
    """Quanto è sostenuta una conclusione. Non è la stessa cosa della qualità
    dell'aggancio di un file: un match FIT perfetto su tre sedute non rende
    solida una media."""

    STRONG = "solida"
    MODERATE = "discreta"
    WEAK = "debole"
    NONE = "insufficiente"


# Sotto questi numeri di casi comparabili una media personale non descrive
# l'atleta, descrive il caso. Le soglie sono dichiarate qui e non sparse nelle
# query, così cambiarle è una decisione visibile.
MIN_CASES_STRONG = 20
MIN_CASES_MODERATE = 8
MIN_CASES_WEAK = 3

# Sotto questa copertura la media parla di una minoranza dei casi.
MIN_COVERAGE_STRONG = 0.80
MIN_COVERAGE_MODERATE = 0.50


def grade(n: int, expected_n: int | None = None) -> str:
    """Il grado di evidenza da numerosità e copertura."""
    if n < MIN_CASES_WEAK:
        return Evidence.NONE
    coverage = (n / expected_n) if expected_n else 1.0
    if n >= MIN_CASES_STRONG and coverage >= MIN_COVERAGE_STRONG:
        return Evidence.STRONG
    if n >= MIN_CASES_MODERATE and coverage >= MIN_COVERAGE_MODERATE:
        return Evidence.MODERATE
    return Evidence.WEAK


@dataclass(frozen=True)
class MetricValue:
    """Un numero con tutto ciò che serve a sapere se ci si può contare.

    Si serializza in un dizionario piatto perché è ciò che i sette strumenti
    MCP restituiscono: il contratto vive in Python ed è testato, non in una
    tabella da mantenere allineata.
    """

    value: float | int | str | None
    unit: str | None = None
    data_class: str = "calculated"        # measured | garmin_proprietary | calculated | inferred
    availability: str = Availability.AVAILABLE

    n: int | None = None
    expected_n: int | None = None
    period: tuple[date, date] | None = None
    data_through: date | None = None

    method_id: str | None = None
    method_version: str = "1"
    inputs_used: tuple = ()
    notes: tuple = ()

    @property
    def coverage(self) -> float | None:
        if self.n is None or not self.expected_n:
            return None
        return self.n / self.expected_n

    @property
    def evidence_grade(self) -> str:
        if self.availability != Availability.AVAILABLE:
            return Evidence.NONE
        if self.n is None:
            return Evidence.MODERATE   # valore singolo misurato: né solido né debole
        return grade(self.n, self.expected_n)

    def as_dict(self) -> dict:
        answer = {
            "value": self.value,
            "unit": self.unit,
            "data_class": self.data_class,
            "availability": self.availability,
            "evidence_grade": self.evidence_grade,
        }
        if self.availability != Availability.AVAILABLE:
            answer["why"] = Availability.SPIEGAZIONI.get(self.availability, "")
        if self.n is not None:
            answer["n"] = self.n
        if self.expected_n is not None:
            answer["expected_n"] = self.expected_n
            answer["coverage"] = round(self.coverage, 3) if self.coverage else None
        if self.period:
            answer["period"] = [self.period[0].isoformat(), self.period[1].isoformat()]
        if self.data_through:
            answer["data_through"] = self.data_through.isoformat()
        if self.method_id:
            answer["method_id"] = self.method_id
            answer["method_version"] = self.method_version
        if self.inputs_used:
            answer["inputs_used"] = list(self.inputs_used)
        if self.notes:
            answer["notes"] = list(self.notes)
        return answer


def missing(reason: str, unit: str | None = None, **extra) -> MetricValue:
    """Un numero che non c'è, con il motivo. Mai zero al suo posto."""
    return MetricValue(value=None, unit=unit, availability=reason, **extra)


def not_applicable(note: str, **extra) -> MetricValue:
    """Il concetto non vale qui — le vasche in acque libere.

    È diverso da «manca»: non c'è niente da recuperare e nessun difetto da
    correggere.
    """
    return MetricValue(value=None, availability=Availability.NOT_APPLICABLE,
                       notes=(note,), **extra)
