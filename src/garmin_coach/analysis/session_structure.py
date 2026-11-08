"""«Cosa ho fatto davvero in questa seduta, e come si divide?»

## Il problema che questo file affronta, e che il progetto ha rimandato a lungo

Un lap registrato dall'orologio è un fatto; «8×100 rec 20"» è un'interpretazione.
Il rischio R1 del piano lo dice da sempre, e per questo `activity_laps` conserva
il dato grezzo e nessuno finora ha provato a ricostruirci sopra delle serie: una
ricostruzione sbagliata è peggio di nessuna ricostruzione, perché somiglia a un
allenamento vero.

Quello che è cambiato è che l'atleta ha dichiarato **la struttura che le sue
sedute hanno sempre**: riscaldamento, parte iniziale o attivazione, parte
centrale, parte finale o defaticamento — quest'ultima non sempre presente. Non è
una regola generale del nuoto: è come lavora il suo allenatore, e il fatto che
sia dichiarata la trasforma da ipotesi in vincolo.

Con un vincolo si può inferire. Senza, si tirava a indovinare.

## I due strati, e perché restano due

**Le ripetute** sono quasi un fatto. Lap consecutivi con la stessa distanza e la
stessa nuotata, separati da riposi: «6×100 stile» si legge dai numeri, non si
interpreta. L'unico giudizio è quanti lap uguali di fila servano per chiamarla
serie, e la soglia è scritta qui sotto.

**I blocchi** sono un'interpretazione, e vengono etichettati come tale. Dire
quale gruppo di ripetute sia «la parte centrale» richiede di sapere cosa
intendeva l'allenatore, e l'orologio non lo registra. Qui si applicano le regole
che derivano dalla struttura dichiarata, si dichiara quanto sono solide, e
quando non tornano si risponde **`non riconosciuta`** invece di scegliere a caso.

## Perché non finisce in una tabella

Il piano riservava `swim_sets` a questo. La tabella non è mai stata creata, e non
la creo: il risultato dipende interamente dal metodo, e un metodo che cambia
lascerebbe in archivio righe prodotte da una versione precedente senza che
niente lo dica. Finché il calcolo costa millisecondi su una seduta, farlo al
momento tiene una sola verità invece di due.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from ..database import table_exists

# Sotto tre ripetizioni non è una serie, sono nuotate. Due 100 di fila capitano
# in qualunque riscaldamento; sei no.
MIN_REPS_FOR_SET = 3

# Quanto può variare il tempo di una ripetuta perché il gruppo resti lo stesso
# lavoro. Oltre, dentro lo stesso gruppo stanno succedendo due cose diverse —
# tipicamente una progressione, o un cambio di intenzione a metà serie.
MAX_REP_SPREAD_PCT = 12.0

# Un riposo molto più lungo degli altri dentro un gruppo omogeneo separa due
# serie invece di stare dentro una. Il fattore è sul riposo mediano del gruppo.
LONG_REST_FACTOR = 2.5

# Quanto deve essere breve un blocco finale, in quota sul totale, perché possa
# essere un defaticamento e non l'ultima parte del lavoro.
COOLDOWN_MAX_SHARE = 0.20

NOT_RECOGNISED = "non riconosciuta"


@dataclass(frozen=True)
class Set:
    """Un gruppo di ripetute uguali, letto dai lap."""

    reps: int
    distance_m: int
    stroke: str | None
    times_s: list[float]
    rests_s: list[float]

    @property
    def total_m(self) -> int:
        return self.reps * self.distance_m

    @property
    def best_s(self) -> float:
        return min(self.times_s)

    @property
    def mean_s(self) -> float:
        return sum(self.times_s) / len(self.times_s)

    @property
    def spread_pct(self) -> float:
        """Quanto si allarga la serie fra la ripetuta più veloce e la più lenta."""
        if self.best_s <= 0:
            return 0.0
        return (max(self.times_s) - self.best_s) / self.best_s * 100

    @property
    def pace_100_s(self) -> float:
        return self.mean_s / self.distance_m * 100

    @property
    def median_rest_s(self) -> float | None:
        if not self.rests_s:
            return None
        ordinati = sorted(self.rests_s)
        meta = len(ordinati) // 2
        if len(ordinati) % 2:
            return ordinati[meta]
        return (ordinati[meta - 1] + ordinati[meta]) / 2

    @property
    def label(self) -> str:
        nuotata = self.stroke or "stile non dichiarato"
        return f"{self.reps}×{self.distance_m} {nuotata}"

    @property
    def drift_pct(self) -> float:
        """Quanto rallenta dalla prima metà alla seconda.

        È la domanda che l'atleta fa davvero di una serie: «l'ho tenuta?».
        Positivo vuol dire in calando.
        """
        meta = len(self.times_s) // 2
        if meta == 0:
            return 0.0
        prima = sum(self.times_s[:meta]) / meta
        seconda_lista = self.times_s[meta:]
        seconda = sum(seconda_lista) / len(seconda_lista)
        return (seconda - prima) / prima * 100 if prima else 0.0


@dataclass
class Block:
    """Una parte della seduta, con quanto è solida l'attribuzione."""

    name: str
    sets: list[Set] = field(default_factory=list)
    singles_m: int = 0
    confidence: str = "inferita"

    @property
    def total_m(self) -> int:
        return sum(una.total_m for una in self.sets) + self.singles_m


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "activity_laps")


def _work_laps(connection: duckdb.DuckDBPyConnection,
               activity_id: int) -> list[tuple]:
    """I lap nuotati, con il riposo che li segue.

    I lap di riposo non sono lavoro e non sono ripetute: diventano la distanza
    fra due ripetute, che è l'informazione che serve per capire se due nuotate
    uguali appartengono alla stessa serie.
    """
    righe = connection.execute("""
        SELECT lap_index, distance_m, duration_s, stroke, is_rest
        FROM activity_laps
        WHERE activity_id = ?
        ORDER BY lap_index
    """, [activity_id]).fetchall()

    lavoro: list[tuple] = []
    riposo_accumulato = 0.0
    for _, distanza, durata, nuotata, e_riposo in righe:
        if e_riposo or not distanza or durata is None or durata <= 0:
            riposo_accumulato += durata or 0.0
            continue
        lavoro.append((int(distanza), float(durata), nuotata, riposo_accumulato))
        riposo_accumulato = 0.0
    return lavoro


def sets(connection: duckdb.DuckDBPyConnection, activity_id: int) -> list[Set]:
    """Le serie riconosciute in una seduta, nell'ordine in cui sono state nuotate.

    Un gruppo si chiude quando cambia la distanza, cambia la nuotata, il tempo
    esce dalla fascia del gruppo, o compare un riposo molto più lungo degli
    altri: sono i quattro modi in cui una serie finisce davvero.
    """
    if not available(connection):
        return []

    trovate: list[Set] = []
    corrente: list[tuple] = []

    def chiudi() -> None:
        if len(corrente) < MIN_REPS_FOR_SET:
            corrente.clear()
            return
        trovate.append(Set(
            reps=len(corrente),
            distance_m=corrente[0][0],
            stroke=corrente[0][2],
            times_s=[una[1] for una in corrente],
            # Il riposo prima della prima ripetuta appartiene a ciò che c'era
            # prima, non a questa serie.
            rests_s=[una[3] for una in corrente[1:]]))
        corrente.clear()

    for distanza, durata, nuotata, riposo in _work_laps(connection, activity_id):
        if corrente:
            uguale = (distanza == corrente[0][0] and nuotata == corrente[0][2])
            tempi = [una[1] for una in corrente] + [durata]
            dentro_fascia = (max(tempi) - min(tempi)) / min(tempi) * 100 \
                <= MAX_REP_SPREAD_PCT if min(tempi) > 0 else False
            riposi = [una[3] for una in corrente[1:]]
            mediano = sorted(riposi)[len(riposi) // 2] if riposi else None
            stacco = (mediano is not None and mediano > 0
                      and riposo > mediano * LONG_REST_FACTOR)
            if not uguale or not dentro_fascia or stacco:
                chiudi()
        corrente.append((distanza, durata, nuotata, riposo))
    chiudi()
    return trovate


def blocks(connection: duckdb.DuckDBPyConnection,
           activity_id: int) -> list[Block]:
    """La seduta divisa nella struttura che l'atleta ha dichiarato.

    Le regole, in quest'ordine, e ognuna vale solo perché la struttura è
    dichiarata — su una seduta di chiunque altro sarebbero congetture:

    1. **Il riscaldamento è il primo blocco.** Non perché sia più lento — a volte
       non lo è — ma perché l'atleta dice che c'è sempre e viene sempre prima.
    2. **La parte centrale è la serie con più metri.** È la definizione pratica
       di «centrale» in una seduta costruita così: il lavoro principale è quello
       su cui si è speso più volume.
    3. **Il defaticamento è l'ultimo blocco, se è breve.** Sopra un quinto della
       seduta non è un defaticamento, è ancora lavoro — e l'atleta ha detto che
       non sempre lo fa, quindi l'assenza è normale e non un dato mancante.
    4. **Quello che sta fra il riscaldamento e la parte centrale è
       l'attivazione.** Per esclusione, che è onesto dichiarare.

    Quando le serie riconosciute sono meno di due, la divisione non si fa:
    restituisce un blocco solo con `confidence` a ``non riconosciuta``. Una
    seduta continua o troppo frammentata non ha una struttura da leggere, e
    inventargliene una sarebbe il difetto che R1 descrive.
    """
    riconosciute = sets(connection, activity_id)
    if len(riconosciute) < 2:
        totale = sum(una.total_m for una in riconosciute)
        return [Block(name=NOT_RECOGNISED, sets=riconosciute,
                      singles_m=0, confidence=NOT_RECOGNISED)] if totale else []

    centrale = max(range(len(riconosciute)),
                   key=lambda i: riconosciute[i].total_m)
    metri_totali = sum(una.total_m for una in riconosciute)

    # Il defaticamento esiste solo se c'è qualcosa dopo la parte centrale, ed è
    # abbastanza piccolo da esserlo.
    coda = riconosciute[centrale + 1:]
    metri_coda = sum(una.total_m for una in coda)
    ha_defaticamento = bool(coda) and metri_coda <= metri_totali * COOLDOWN_MAX_SHARE

    divisi: list[Block] = [
        Block("riscaldamento", [riconosciute[0]], confidence="dichiarata"),
    ]
    attivazione = riconosciute[1:centrale]
    if attivazione:
        divisi.append(Block("attivazione", attivazione, confidence="per esclusione"))
    divisi.append(Block("parte centrale", [riconosciute[centrale]],
                        confidence="inferita"))

    if ha_defaticamento:
        divisi.append(Block("defaticamento", coda, confidence="inferita"))
    elif coda:
        # Troppo grande per essere un defaticamento: resta lavoro, e dirlo è
        # più utile che chiamarlo con il nome sbagliato.
        divisi.append(Block("lavoro dopo la parte centrale", coda,
                            confidence="inferita"))

    # Il riscaldamento non può essere anche la parte centrale: se la serie con
    # più metri è la prima, la struttura dichiarata non regge su questa seduta.
    if centrale == 0:
        return [Block(name=NOT_RECOGNISED, sets=riconosciute,
                      confidence=NOT_RECOGNISED)]
    return divisi


def as_page_dict(connection: duckdb.DuckDBPyConnection,
                 activity_id: int) -> dict:
    """La struttura come la riceve una pagina: già in parole."""
    divisi = blocks(connection, activity_id)

    if not divisi:
        # Due situazioni diverse, e chiamarle con lo stesso nome è un errore
        # che si paga: «non ci sono lap» manda a guardare l'import, «i lap non
        # formano serie» manda a guardare la seduta.
        quanti = len(_work_laps(connection, activity_id))
        if not quanti:
            return {"available": False,
                    "why": ("Questa seduta non ha lap dettagliati: senza, non "
                            "c'è niente da cui leggere le serie.")}
        return {"available": False,
                "why": (f"Questa seduta ha {quanti} tratti nuotati, e nessun "
                        f"gruppo di almeno {MIN_REPS_FOR_SET} ripetute uguali "
                        "di fila. Può essere una nuotata continua, un lavoro "
                        "vario, o una registrazione frammentata: da qui non si "
                        "distingue, e inventare una divisione sarebbe peggio.")}

    if divisi[0].confidence == NOT_RECOGNISED:
        return {
            "available": False,
            "why": ("Le serie si riconoscono, ma non si dispongono nella "
                    "struttura riscaldamento → attivazione → parte centrale: "
                    "il lavoro più lungo è il primo. Le serie restano qui "
                    "sotto; la divisione no, perché sarebbe inventata."),
            "sets": [_set_dict(una) for una in divisi[0].sets],
        }

    return {
        "available": True,
        "blocks": [{
            "name": blocco.name,
            "confidence": blocco.confidence,
            "total_m": blocco.total_m,
            "sets": [_set_dict(una) for una in blocco.sets],
        } for blocco in divisi],
    }


def _set_dict(una: Set) -> dict:
    riposo = una.median_rest_s
    return {
        "label": una.label,
        "total_m": una.total_m,
        "pace": _pace(una.pace_100_s),
        "best": _clock(una.best_s),
        "spread": f"{una.spread_pct:.1f}%".replace(".", ","),
        "rest": f"{round(riposo)}\"" if riposo else "senza riposo registrato",
        "held": _tenuta(una),
    }


def _tenuta(una: Set) -> str:
    """«L'hai tenuta?» — la domanda vera su una serie."""
    deriva = una.drift_pct
    if abs(deriva) < 1.5:
        return "tenuta"
    segno = "in calando" if deriva > 0 else "in crescendo"
    return f"{segno} del {abs(deriva):.1f}%".replace(".", ",")


def _clock(seconds: float) -> str:
    minuti, resto = divmod(round(seconds, 1), 60)
    if minuti:
        return f"{int(minuti)}'{resto:04.1f}\"".replace(".", ",")
    return f"{resto:.1f}\"".replace(".", ",")


def _pace(seconds_per_100: float) -> str:
    centesimi = round(seconds_per_100 * 100)
    minuti, resto = divmod(centesimi, 6000)
    return f"{minuti}:{resto / 100:05.2f}/100 m".replace(".", ",")
