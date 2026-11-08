"""Il formato unico di ogni osservazione (Macro-proposta 4, §4).

## Perché un formato solo

Il progetto ha due bocche — i sette strumenti MCP e l'applicazione locale — e
una sola testa. Se l'app ricalcolasse anche solo la soglia con cui colorare una
riga, esisterebbero due verità che divergono in silenzio: è il Rilievo 2
dell'audit principale.

Qui vive l'oggetto che entrambe serializzano. Nessuna delle due lo costruisce:
lo ricevono già fatto dai servizi di ``analysis/``.

## Osservazione e interpretazione non sono la stessa cosa

``observation`` è deterministica e descrittiva: la produce Python, è sempre
uguale a parità di dati, e non dice mai *perché*. «HRV sotto la fascia personale
da tre giorni, sonno e FC a riposo nella norma» è un'osservazione.

``interpretation`` è il giudizio di un modello, arriva soltanto se qualcuno la
chiede, ed è etichettata come tale. Non sostituisce mai l'osservazione: se il
modello non è disponibile, la pagina resta utile senza di lui.

Tenerle in due campi diversi è ciò che permette all'app di funzionare offline
senza diventare muta.

## Le evidenze non sono note a piè di pagina

Un numero senza unità, numerosità e copertura è un numero su cui si può
sbagliare in silenzio. Ogni valore mostrabile passa da :func:`evidence`, che
unisce due cose che vivevano separate:

- la **definizione** della metrica — unità, formula, sorgente, versione del
  metodo — che sta nel catalogo e non cambia fra due chiamate;
- la **disponibilità in questa risposta** — valore, N, copertura, e perché
  manca quando manca — che sta in ``MetricValue`` e cambia sempre.

## I testi già formattati

Ogni evidenza porta ``display``, la stringa da mostrare. Non è una comodità:
è ciò che permette al test «nessuna formula nei template» di essere vero.
Dividere per mille per ottenere i chilometri dentro una pagina HTML sarebbe una
formula in un template, e da lì a due verità il passo è breve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ..metrics.catalog import BY_COLUMN
from ..metrics.evidence import Availability, MetricValue

# Spazio fine: separa le migliaia senza sembrare un punto decimale.
THIN_SPACE = " "

# Unità che descrivono una **scala**, non una grandezza. «21 stress Garmin
# 0-100» non è una frase: la scala si dichiara nell'etichetta e nel catalogo,
# il valore si mostra nudo.
SCALE_UNITS = {
    "punteggio Garmin 0-100", "Body Battery 0-100", "stress Garmin 0-100",
    "etichetta Garmin", "vero/falso", "elenco", "SWOLF", "rapporto",
    "carico Garmin",
}


class Status:
    """Che cosa l'osservazione chiede all'atleta di fare.

    Tre stati e non cinque: ogni stato in più è una sfumatura che l'atleta deve
    imparare a distinguere, e nessuna delle tre domande vere («è normale?»,
    «devo guardarla?», «non lo so ancora») ha bisogno di una quarta.
    """

    INFORMATIVE = "informative"              # normale variabilità personale
    WATCH = "watch"                          # segnali concordi, da osservare
    INSUFFICIENT_DATA = "insufficient_data"  # i dati non bastano per rispondere

    ITALIANO = {
        INFORMATIVE: "normale",
        WATCH: "da osservare",
        INSUFFICIENT_DATA: "dati insufficienti",
    }


def format_measure(value: object, unit: str | None) -> str:
    """Il numero come lo legge una persona, non come lo scrive un database.

    È l'unico posto in cui un valore diventa testo. Sta qui e non nelle pagine
    perché convertire secondi in ore dentro un template sarebbe una formula in
    un template, e il progetto ha una regola contro quello.
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, str):
        return value
    # Un passo non è un numero di secondi: è «1:12,49/100 m», ed è così che
    # l'atleta lo legge sul tabellone e sul cronometro da bordo vasca.
    # Mostrarlo come «72.49 secondi per 100 m» costringe chi guarda a fare la
    # divisione a mente, che è esattamente il lavoro che questo progetto deve
    # togliere.
    if unit == "secondi per 100 m" and isinstance(value, (int, float)):
        centesimi = round(value * 100)
        minuti, resto = divmod(centesimi, 6000)
        return f"{minuti}:{resto / 100:05.2f}/100 m".replace(".", ",")

    if unit == "secondi" and isinstance(value, (int, float)):
        total = int(round(value))
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}h {minutes:02d}m" if hours else f"{minutes}:{seconds:02d}"

    if isinstance(value, float):
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        return str(value)
    text = text.replace(",", THIN_SPACE)
    if not unit or unit in SCALE_UNITS:
        return text
    return f"{text} {unit}"


def format_range(low: object, high: object, unit: str | None) -> str:
    """Un intervallo, con l'unità scritta una volta sola quando si può.

    «30,1 ms – 40,9 ms» dice due volte la stessa cosa. Ma «20 792,2 – 8h 25m» è
    peggio: nasconde che i due estremi sono nella stessa unità e costringe a
    convertire a mente. La regola è quindi una sola — si formattano **entrambi**
    gli estremi, e l'unità si toglie dal primo soltanto se è un suffisso che si
    ripete identico.
    """
    left, right = format_measure(low, unit), format_measure(high, unit)
    if unit and left.endswith(f" {unit}") and right.endswith(f" {unit}"):
        left = left[: -len(unit) - 1]
    return f"{left}–{right}"


def evidence(column: str, value: object = None, *,
             availability: str = Availability.AVAILABLE,
             n: int | None = None, expected_n: int | None = None,
             period: tuple[date, date] | None = None,
             data_through: date | None = None,
             notes: tuple[str, ...] = ()) -> dict:
    """Un numero con tutto ciò che serve a sapere se ci si può contare.

    ``column`` è il nome nel catalogo delle metriche. Se non c'è, l'evidenza si
    costruisce lo stesso ma senza definizione: è il caso di un valore calcolato
    al volo per una domanda specifica, e va dichiarato, non nascosto.
    """
    metric = BY_COLUMN.get(column)
    measure = MetricValue(
        value=value,
        unit=metric.unit if metric else None,
        data_class=metric.data_class if metric else "calculated",
        availability=availability,
        n=n, expected_n=expected_n, period=period, data_through=data_through,
        method_id=column,
        method_version=metric.method_version if metric else "1",
        notes=notes,
    )
    entry = measure.as_dict()
    entry["field"] = column
    entry["display"] = format_measure(value, measure.unit)

    if metric:
        entry["label"] = metric.label
        entry["origin"] = metric.origin
        entry["formula"] = metric.formula
        entry["source"] = metric.source
        if metric.caveat:
            entry["caveat"] = metric.caveat
    else:
        entry["label"] = column
        entry["source"] = "calcolo di questa domanda"
        entry["formula"] = "dichiarata nella funzione che produce l'osservazione"
    return entry


def missing_evidence(column: str, reason: str, note: str = "") -> dict:
    """Un numero che non c'è, col motivo per cui non c'è.

    Mai zero al suo posto, mai una riga assente: l'assenza va vista, altrimenti
    l'atleta legge la pagina come se il dato fosse stato considerato.
    """
    return evidence(column, None, availability=reason,
                    notes=(note,) if note else ())


@dataclass(frozen=True)
class Freshness:
    """Quanto sono vecchi i dati su cui è costruita questa risposta."""

    data_through: date | None
    generated_at: datetime
    days_behind: int | None

    @property
    def is_stale(self) -> bool:
        return self.days_behind is not None and self.days_behind > 3

    def as_dict(self) -> dict:
        return {
            "data_through": self.data_through.isoformat() if self.data_through else None,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "days_behind": self.days_behind,
            "is_stale": self.is_stale,
            "display": (
                "nessun dato" if self.data_through is None
                else "aggiornato a oggi" if self.days_behind == 0
                else f"ieri, {self.data_through.strftime('%d/%m/%Y')}"
                if self.days_behind == 1
                else f"i dati si fermano al {self.data_through.strftime('%d/%m/%Y')}, "
                     f"{self.days_behind} giorni fa"
            ),
        }


@dataclass
class InsightPacket:
    """Una domanda dell'atleta e la risposta che i dati reggono davvero.

    Si costruisce solo dentro ``analysis/``. MCP e app la serializzano e basta.
    """

    question: str
    observation: str
    status: str = Status.INFORMATIVE
    period: tuple[date, date] | None = None
    evidence: list[dict] = field(default_factory=list)
    comparisons: list[dict] = field(default_factory=list)
    counter_evidence: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_question: str | None = None
    links: list[dict] = field(default_factory=list)
    freshness: Freshness | None = None
    interpretation: dict | None = None
    # La geometria di un eventuale grafico, gia calcolata. Sta qui e non nella
    # pagina perche l'altezza di una barra e una divisione, e le divisioni nei
    # template sono vietate dalla Regola Aurea n.8.
    chart: object | None = None

    def add(self, entry: dict) -> None:
        self.evidence.append(entry)

    def against(self, entry: dict) -> None:
        """Un fatto che **non** concorda con l'osservazione.

        Una pagina che mostra solo ciò che conferma la propria conclusione è una
        pagina che convince, non una che informa.
        """
        self.counter_evidence.append(entry)

    def as_dict(self) -> dict:
        answer = {
            "question": self.question,
            "observation": self.observation,
            "status": self.status,
            "status_it": Status.ITALIANO.get(self.status, self.status),
            "evidence": self.evidence,
            "comparisons": self.comparisons,
            "counter_evidence": self.counter_evidence,
            "limitations": self.limitations,
            "next_question": self.next_question,
            "links": self.links,
        }
        if self.period:
            answer["period"] = {"start": self.period[0].isoformat(),
                                "end": self.period[1].isoformat()}
        if self.freshness:
            answer["freshness"] = self.freshness.as_dict()
        # `interpretation` compare solo se qualcuno l'ha chiesta a un modello.
        # Assente per definizione nel percorso offline: non è un campo vuoto da
        # riempire, è una cosa che non è stata fatta.
        if self.interpretation:
            answer["interpretation"] = self.interpretation
        if self.chart is not None:
            answer["chart"] = self.chart
        return answer


# Per i due strumenti che non restituiscono numeri. Un elenco di evidenze vuoto
# senza spiegazione sembra una dimenticanza; con la spiegazione è una scelta.
NO_NUMBERS = {
    "athlete_context": (
        "Questo strumento restituisce il markdown scritto dall'atleta, non "
        "misure: non ci sono numeri da coprire con un'evidenza."),
    "log_write": (
        "Questo strumento scrive e restituisce l'esito della scrittura: non "
        "produce misure."),
}
