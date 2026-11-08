"""«Questa prova dove è cambiata, e sto cedendo di ampiezza o di frequenza?»

## Perché i lap non bastano a rispondere

`session_structure.py` legge i lap e sa dire se una serie è stata tenuta. È la
domanda giusta su una serie, e su un lap è l'unica possibile: un lap è un numero
solo, e da un numero non si vede *come* è stato ottenuto.

Ma un nuotatore che rallenta può farlo in due modi opposti, che richiedono due
allenamenti diversi:

- **la bracciata si accorcia** — stessa frequenza, meno metri per bracciata:
  l'acqua scappa, tipicamente per cedimento della trazione;
- **il ritmo cala** — stessa ampiezza, meno bracciate al minuto: è la macchina
  aerobica che rallenta.

E c'è il caso che li contiene entrambi e che si vede solo scomponendo:
**l'ampiezza cala e la frequenza sale a compensare**, con il passo che sembra
tenuto. È il quadro classico dell'affaticamento in una prova lunga, e a livello
di lap è **invisibile**: il tempo sul 100 è identico.

La risposta sta nelle vasche, non nei lap. Il progetto ne ha 173.864 importate,
133.829 con le bracciate, e finora nessuna analisi le usava per questo.

## La scomposizione è un'identità, non un modello

    velocità = ampiezza × frequenza

    (metri/secondo) = (metri/bracciata) × (bracciate/secondo)

Le bracciate si semplificano: è algebra, non una correlazione. Verificato sulle
127.358 vasche dell'archivio che hanno tutti e tre i valori: **errore massimo
2,5 × 10⁻¹⁶**, cioè la precisione della virgola mobile.

Per questo la frequenza qui viene **ricalcolata** da bracciate e tempo invece di
usare `cadence_spm` memorizzato: quel valore è arrotondato all'intero da Garmin
— scarto mediano misurato 0,25 bracciate al minuto, massimo 0,5 — e un
arrotondamento romperebbe l'identità, trasformando un fatto in un'approssimazione.

## La soglia non è una costante, e non poteva esserlo

Sotto quale differenza fra prima e seconda metà è onesto dire «ha ceduto»?

Misurato su 4.329 tratti continui dell'archivio: il tempo di una singola vasca
varia con un CV **mediano del 5,8%** (p90 13,9%), i metri per bracciata
dell'**8,0%** (p90 16,5%). Una vasca più lenta del 5% non è un calo: è una
respirazione, una virata, un compagno da superare.

Ma quel rumore si media via confrontando due **metà** invece di due vasche, e
quanto si media dipende da quante vasche ha la prova. Una soglia fissa sarebbe
troppo severa su una prova lunga e troppo permissiva su una corta.

Qui la soglia si calcola **dalla dispersione della prova stessa**, con l'errore
standard della differenza fra due medie, e viene sempre dichiarata insieme al
verdetto. È la stessa disciplina che la Macro-proposta 5 impone in acque libere,
applicata dove il dato è molto migliore: in vasca la distanza è esatta e non
c'è nessun GPS da cui difendersi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import duckdb

from ..database import table_exists

# Sotto otto vasche le due metà hanno tre tratti ciascuna, e una media di tre
# vasche non descrive una tendenza: descrive tre vasche. Su vasca da 25 sono
# 200 m, su vasca da 50 sono 400 m — cioè le distanze da cui una prova comincia
# a essere una prova.
MIN_LENGTHS_FOR_EFFORT = 8

# Il pavimento della soglia. Anche su una prova lunghissima e regolarissima non
# si rivendica di distinguere mezzo punto percentuale: sotto l'1,5% entrano il
# cronometraggio della piastra dell'orologio e le virate.
MIN_NOISE_PCT = 1.5

# Garmin scrive 0 dove il dato non c'è. Il progetto lo sa dalla Fase 1 e lo
# tratta come mancante ovunque: 6.471 vasche attive hanno zero bracciate, e
# zero bracciate su una vasca nuotata non è una misura.
NOT_MEASURED = None

HELD = "tenuta"
FADING = "in calando"
BUILDING = "in crescendo"

AMPLITUDE = "ampiezza"
FREQUENCY = "frequenza"
BOTH = "entrambe"
COMPENSATED = "ampiezza persa e frequenza alzata a compensare"
MIXED_STROKES = "stili misti"


@dataclass(frozen=True)
class Length:
    """Una vasca nuotata, con le tre grandezze che la descrivono.

    `dps_m` e `rate_hz` mancano insieme, sempre: vengono entrambe dalle
    bracciate. Il passo invece c'è comunque, perché nasce dal tempo.
    """

    index: int
    pool_length_m: float
    duration_s: float
    strokes: float | None
    stroke: str | None

    @property
    def speed_ms(self) -> float:
        return self.pool_length_m / self.duration_s

    @property
    def pace_100_s(self) -> float:
        return self.duration_s / self.pool_length_m * 100

    @property
    def dps_m(self) -> float | None:
        """Metri per bracciata: l'ampiezza."""
        if not self.strokes:
            return NOT_MEASURED
        return self.pool_length_m / self.strokes

    @property
    def rate_hz(self) -> float | None:
        """Bracciate al secondo: la frequenza.

        In hertz e non al minuto perché è così che entra nell'identità senza
        una costante di conversione appiccicata. Per mostrarla si moltiplica
        per 60 nell'ultimo momento utile.
        """
        if not self.strokes:
            return NOT_MEASURED
        return self.strokes / self.duration_s

    @property
    def swolf(self) -> float | None:
        if not self.strokes:
            return NOT_MEASURED
        return self.duration_s + self.strokes


@dataclass(frozen=True)
class Effort:
    """Un tratto nuotato di fila, letto vasca per vasca."""

    activity_id: int
    lap_index: int
    lengths: list[Length]

    # ---- ciò che la prova è ------------------------------------------------

    @property
    def distance_m(self) -> float:
        return sum(una.pool_length_m for una in self.lengths)

    @property
    def duration_s(self) -> float:
        return sum(una.duration_s for una in self.lengths)

    @property
    def pace_100_s(self) -> float:
        return self.duration_s / self.distance_m * 100

    @property
    def stroke(self) -> str | None:
        """Lo stile, se è uno solo. Altrimenti niente, e non «misto»."""
        stili = {una.stroke for una in self.lengths if una.stroke}
        return stili.pop() if len(stili) == 1 else None

    @property
    def single_stroke(self) -> bool:
        return self.stroke is not None

    # ---- le due metà, e perché la prima vasca resta fuori -------------------

    @property
    def compared(self) -> list[Length]:
        """Le vasche che entrano nel confronto: tutte tranne la prima.

        La prima vasca contiene la partenza — una spinta dal muro o dal blocco
        che nessun'altra vasca ha. Non è prestazione, è un metro di vantaggio
        meccanico, e lasciarla dentro fa sembrare «in calando» ogni prova
        nuotata bene.

        L'ultima invece resta. In gara si toglie perché contiene la volata, che
        è un artefatto della corsia; in una prova, un finale più veloce non è
        un artefatto: è una scelta di distribuzione, ed è esattamente ciò che
        si vuole poter leggere.
        """
        return self.lengths[1:]

    def _halves(self) -> tuple[list[Length], list[Length]]:
        dentro = self.compared
        meta = len(dentro) // 2
        return dentro[:meta], dentro[meta:]

    def _noise_for(self, valore) -> float:
        """Sotto quale differenza questa grandezza, in questa prova, tace.

        Errore standard della differenza fra le medie delle due metà, espresso
        in percentuale: `CV × sqrt(2/n)`. Cresce quando la prova è irregolare e
        cala quando è lunga — che è esattamente come dovrebbe comportarsi.

        Si calcola **per grandezza** e non una volta sola, perché passo e metri
        per bracciata non hanno la stessa dispersione: misurati sull'archivio,
        CV mediano 5,8% il primo e 8,0% i secondi. Usare la soglia del passo
        per giudicare l'ampiezza la dichiarerebbe ferma più spesso di quanto
        sia vero.
        """
        serie = [valore(una) for una in self.compared]
        serie = [uno for uno in serie if uno is not None]
        if len(serie) < 4:
            return 100.0
        media = sum(serie) / len(serie)
        if media <= 0:
            return 100.0
        varianza = sum((uno - media) ** 2 for uno in serie) / (len(serie) - 1)
        cv = math.sqrt(varianza) / media * 100
        return max(cv * math.sqrt(2 / (len(serie) / 2)), MIN_NOISE_PCT)

    @property
    def noise_pct(self) -> float:
        """Sotto quale differenza di passo questa prova non dice niente."""
        return self._noise_for(lambda una: una.pace_100_s)

    def _change_pct(self, valore) -> float | None:
        """Quanto cambia una grandezza dalla prima alla seconda metà, in %."""
        prima, seconda = self._halves()
        a = [valore(una) for una in prima if valore(una) is not None]
        b = [valore(una) for una in seconda if valore(una) is not None]
        if not a or not b:
            return None
        media_a = sum(a) / len(a)
        if media_a <= 0:
            return None
        return (sum(b) / len(b) - media_a) / media_a * 100

    @property
    def pace_change_pct(self) -> float | None:
        """Positivo vuol dire più lento nella seconda metà."""
        return self._change_pct(lambda una: una.pace_100_s)

    @property
    def dps_change_pct(self) -> float | None:
        return self._change_pct(lambda una: una.dps_m)

    @property
    def rate_change_pct(self) -> float | None:
        return self._change_pct(lambda una: una.rate_hz)

    # ---- i due verdetti ----------------------------------------------------

    @property
    def verdict(self) -> str:
        cambio = self.pace_change_pct
        if cambio is None:
            return HELD
        if abs(cambio) < self.noise_pct:
            return HELD
        return FADING if cambio > 0 else BUILDING

    @property
    def attribution(self) -> str | None:
        """Di cosa ha ceduto: ampiezza, frequenza, entrambe, o compensazione.

        Restituisce `None` quando la domanda non si può porre — bracciate
        assenti, oppure stili diversi nella stessa prova. Confrontare i metri
        per bracciata di un delfino con quelli di uno stile libero misura il
        cambio di nuotata, non la stanchezza.
        """
        if not self.single_stroke:
            return MIXED_STROKES
        ampiezza, frequenza = self.dps_change_pct, self.rate_change_pct
        if ampiezza is None or frequenza is None:
            return None

        soglia_ampiezza = self._noise_for(lambda una: una.dps_m)
        soglia_frequenza = self._noise_for(lambda una: una.rate_hz)
        cede_ampiezza = ampiezza < -soglia_ampiezza
        cede_frequenza = frequenza < -soglia_frequenza

        # Il caso che i lap non vedono: la bracciata si accorcia e il ritmo sale
        # per tenere il passo. Va riconosciuto prima degli altri, perché
        # altrimenti si legge come «ha ceduto solo l'ampiezza» e si perde il
        # fatto che l'atleta stava già pagando per restare lì.
        if cede_ampiezza and frequenza > soglia_frequenza:
            return COMPENSATED
        if cede_ampiezza and cede_frequenza:
            return BOTH
        if cede_ampiezza:
            return AMPLITUDE
        if cede_frequenza:
            return FREQUENCY
        return None


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "pool_lengths")


def efforts(connection: duckdb.DuckDBPyConnection,
            activity_id: int,
            min_lengths: int = MIN_LENGTHS_FOR_EFFORT) -> list[Effort]:
    """I tratti continui di una seduta che sono abbastanza lunghi da leggersi.

    Il raggruppamento è per `lap_index`, cioè per come l'orologio ha segnato la
    seduta: non è un'interpretazione, è il dato. Le vasche di riposo e quelle
    con durata non positiva restano fuori — non sono nuotate.
    """
    if not available(connection):
        return []

    righe = connection.execute("""
        SELECT l.lap_index, l.length_index, a.pool_length_m,
               l.duration_s, l.total_strokes, l.stroke
        FROM pool_lengths l
        JOIN canonical_activities a ON a.activity_id = l.activity_id
        WHERE l.activity_id = ? AND l.is_active
          AND l.duration_s > 0 AND a.pool_length_m > 0
        ORDER BY l.lap_index, l.length_index
    """, [activity_id]).fetchall()

    per_lap: dict[int, list[Length]] = {}
    for lap_index, length_index, vasca, durata, bracciate, stile in righe:
        per_lap.setdefault(lap_index, []).append(Length(
            index=length_index,
            pool_length_m=float(vasca),
            duration_s=float(durata),
            # Lo zero di Garmin diventa assenza qui e non più a valle: ogni
            # lettura successiva riceve già `None` e non deve ricordarsene.
            strokes=float(bracciate) if bracciate else NOT_MEASURED,
            stroke=stile))

    return [Effort(activity_id=activity_id, lap_index=lap, lengths=vasche)
            for lap, vasche in sorted(per_lap.items())
            if len(vasche) >= min_lengths]


def longest(connection: duckdb.DuckDBPyConnection,
            activity_id: int) -> Effort | None:
    """Il tratto continuo più lungo: quasi sempre è «la prova» della seduta."""
    trovati = efforts(connection, activity_id)
    return max(trovati, key=lambda uno: uno.distance_m) if trovati else None


# --------------------------------------------------------------------------
# Presentazione: ogni stringa nasce qui, mai in una pagina.
# --------------------------------------------------------------------------

def _pace(seconds_per_100: float) -> str:
    centesimi = round(seconds_per_100 * 100)
    minuti, resto = divmod(centesimi, 6000)
    return f"{minuti}:{resto / 100:05.2f}/100 m".replace(".", ",")


def _pct(valore: float) -> str:
    return f"{valore:+.1f}%".replace(".", ",")


def _num(valore: float, decimali: int = 1) -> str:
    """Un numero con la virgola decimale, senza toccare la punteggiatura.

    La scorciatoia `f"...".replace(".", ",")` su una frase intera mangia anche
    il punto finale: è successo, ed è il genere di difetto che si nota solo
    leggendo l'output vero.
    """
    return f"{valore:.{decimali}f}".replace(".", ",")


def _stroke_label(stroke: str | None) -> str:
    nomi = {"freestyle": "stile libero", "backstroke": "dorso",
            "breaststroke": "rana", "butterfly": "delfino", "drill": "esercizio"}
    return nomi.get(stroke or "", stroke or "stile non dichiarato")


def _explain(uno: Effort) -> str:
    """Il verdetto in una frase, con dentro i numeri che lo giustificano."""
    cambio = uno.pace_change_pct
    if cambio is None:
        return "Non ci sono abbastanza vasche confrontabili per dire come è andata."

    if uno.verdict == HELD:
        return (f"Passo tenuto: fra prima e seconda metà {_pct(cambio)}, dentro "
                f"il rumore di questa prova ({_num(uno.noise_pct)}%).")

    testa = (f"Passo {uno.verdict} del {_num(abs(cambio))}%, oltre il rumore "
             f"di questa prova ({_num(uno.noise_pct)}%).")

    causa = uno.attribution
    ampiezza, frequenza = uno.dps_change_pct, uno.rate_change_pct

    if causa == MIXED_STROKES:
        return (testa + " Non dico di cosa: la prova contiene stili diversi, e "
                "i metri per bracciata di due nuotate diverse non si confrontano.")
    if causa is None and (ampiezza is None or frequenza is None):
        return (testa + " Non dico di cosa: su queste vasche l'orologio non ha "
                "registrato le bracciate.")
    if causa == COMPENSATED:
        return (testa + f" L'ampiezza è calata ({_pct(ampiezza)}) e la frequenza "
                f"è salita ({_pct(frequenza)}) a compensare: stavi già pagando "
                "per restare su quel passo.")
    if causa == BOTH:
        return (testa + f" Hanno ceduto entrambe: ampiezza {_pct(ampiezza)}, "
                f"frequenza {_pct(frequenza)}.")
    if causa == AMPLITUDE:
        return (testa + f" Ha ceduto l'ampiezza ({_pct(ampiezza)}), con la "
                f"frequenza sostanzialmente ferma ({_pct(frequenza)}): la "
                "bracciata si è accorciata.")
    if causa == FREQUENCY:
        return (testa + f" Ha ceduto la frequenza ({_pct(frequenza)}), con "
                f"l'ampiezza ferma ({_pct(ampiezza)}): hai rallentato il ritmo "
                "tenendo la bracciata.")
    return (testa + " Né ampiezza né frequenza cambiano oltre il rumore: il "
            "passo si è mosso per una combinazione che questa prova non separa.")


def as_page_dict(connection: duckdb.DuckDBPyConnection,
                 activity_id: int) -> dict:
    """La lettura vasca per vasca, già in parole."""
    trovati = efforts(connection, activity_id)
    if not trovati:
        if not available(connection):
            return {"available": False,
                    "why": ("Il dettaglio vasca per vasca non è ancora stato "
                            "importato: si ottiene con «garmin_coach details».")}
        return {"available": False,
                "why": (f"Questa seduta non ha nessun tratto nuotato di almeno "
                        f"{MIN_LENGTHS_FOR_EFFORT} vasche di fila. Può essere "
                        "una seduta tutta a ripetute corte, oppure in acque "
                        "libere, dove le vasche non esistono.")}

    return {
        "available": True,
        "efforts": [{
            "label": (f"{int(uno.distance_m)} m {_stroke_label(uno.stroke)}"
                      if uno.single_stroke
                      else f"{int(uno.distance_m)} m a stili misti"),
            "pace": _pace(uno.pace_100_s),
            "verdict": uno.verdict,
            "explanation": _explain(uno),
            "lengths": [{
                "index": vasca.index,
                "pace": _pace(vasca.pace_100_s),
                "dps": (f"{vasca.dps_m:.2f} m".replace(".", ",")
                        if vasca.dps_m else "—"),
                "rate": (f"{vasca.rate_hz * 60:.0f}/min" if vasca.rate_hz else "—"),
                "swolf": (f"{vasca.swolf:.0f}" if vasca.swolf else "—"),
            } for vasca in uno.lengths],
        } for uno in trovati],
    }
