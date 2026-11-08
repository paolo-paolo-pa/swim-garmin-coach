"""«Qual è il passo che riesco a tenere davvero?»

## Perché per nove mesi la risposta è stata "non lo so"

`coach/riferimenti.md` dichiara bloccate tre cose finché non esiste una prova
massimale: la velocità critica, gli intervalli di passo di una serie, e ogni
previsione di gara. Il motivo era giusto — la media di una seduta con i recuperi
dentro non è un tempo prestativo — ma la conseguenza era che il coach non sapeva
dire a che ritmo far nuotare l'atleta.

Lo storico della federazione l'ha sbloccata senza che nessuno se ne accorgesse:
il 24/05/2026, nella stessa vasca e nello stesso pomeriggio, ci sono un 400 e un
200 stile cronometrati da una piastra. Sono esattamente i due ingressi che il
protocollo chiede.

## Cos'è la velocità critica, e cosa non è

    CSS = (400 − 200) / (t400 − t200)

La pendenza della retta fra due prove massimali su distanze diverse. È la
velocità che in teoria si può sostenere a lungo senza accumulo: nella pratica
allenante è il riferimento di soglia, il passo attorno a cui si costruiscono le
serie lunghe.

**Non è una previsione.** Dice a che ritmo allenarsi, non che tempo si farà in
gara. E non attraversa gli ambienti: una velocità critica misurata in vasca
resta un fatto della vasca. Metterla accanto a un obiettivo in mare è un
confronto fra due fatti; ricavare il secondo dal primo, su una distanza molte
volte più lunga, in acqua salata e senza muro, sarebbe una previsione che
nessun modello di questo progetto autorizza.

## Perché una gara vale come prova massimale

Lo ha deciso l'atleta, ed è la decisione giusta: in gara si nuota a tutta per
definizione, mentre un test in allenamento dipende da come ci si sente quel
giorno. Con una precisazione che l'atleta ha fatto per primo e che il codice
verifica da sé: **quando fra il 200 e il 400 ci sono altre gare**, le due prove
non sono fresche allo stesso modo, e la velocità critica che ne esce è
**prudente** — il passo vero è più veloce di quello calcolato.

Il conto delle gare in mezzo non è una nota scritta a mano: si legge
dall'archivio, gara per gara, e compare accanto al risultato.

## Perché solo la vasca

`pool_races` significa piscina certificata, distanza misurata, stile noto. In
mare la distanza è una dichiarazione dell'organizzazione — vedi la migrazione
0009 — e una velocità critica costruita su due distanze dichiarate misurerebbe
la fantasia degli organizzatori.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

from ..database import table_exists

# Le due distanze del protocollo classico. Non sono configurabili: cambiarle
# cambia il significato del numero, e un CSS calcolato su 800 e 400 non si
# confronta con uno calcolato su 400 e 200.
LONG_M = 400
SHORT_M = 200

# Quanto lontane possono essere le due prove. Ventuno giorni è un blocco di
# gare: dentro quella finestra la forma è ragionevolmente la stessa, fuori si
# stanno confrontando due condizioni diverse e la pendenza non descrive più una
# persona sola. **Scelta, non misurata**: va guardata in audit.
PAIR_WINDOW_DAYS = 21

# Oltre questa velocità non c'è un nuotatore, c'è un errore nei dati. È la
# stessa soglia che il criterio C12 applica alle attività dell'orologio.
MAX_HUMAN_SWIM_SPEED_MS = 3.0


@dataclass(frozen=True)
class Pair:
    """Le due prove che producono una velocità critica, e come stavano insieme."""

    pool_length_m: int
    long_race_id: str
    long_day: date
    long_time_s: float
    short_race_id: str
    short_day: date
    short_time_s: float
    races_between: int

    @property
    def gap_days(self) -> int:
        return abs((self.long_day - self.short_day).days)

    @property
    def day(self) -> date:
        """Quando è stata misurata: la più recente delle due prove."""
        return max(self.long_day, self.short_day)

    @property
    def speed_ms(self) -> float:
        return (LONG_M - SHORT_M) / (self.long_time_s - self.short_time_s)

    @property
    def pace_100_s(self) -> float:
        """Il passo di soglia per 100 m.

        È metà della differenza fra i due tempi, e non per caso: con 200 metri
        di differenza fra le due prove, `100 / CSS` si semplifica in
        `(t400 − t200) / 2`. Il conto resta scritto nella forma generale perché
        la scorciatoia vale solo per questa coppia di distanze.
        """
        return 100 / self.speed_ms

    @property
    def plausible(self) -> bool:
        """Una coppia impossibile non produce un numero prudente: non ne produce.

        Se il 400 non è più lento del 200 la pendenza è negativa o infinita, e
        se la velocità che ne esce supera quella umana i due tempi non
        descrivono la stessa persona nello stesso stato.
        """
        if self.long_time_s <= self.short_time_s:
            return False
        return 0 < self.speed_ms < MAX_HUMAN_SWIM_SPEED_MS


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "races")


def pairs(connection: duckdb.DuckDBPyConnection,
          stroke: str = "stile", until: date | None = None) -> list[Pair]:
    """Tutte le coppie 400/200 utilizzabili, dalla più recente.

    Ogni 400 viene accoppiato al 200 **più vicino nel tempo** nella stessa
    vasca, e non al 200 più veloce: la velocità critica descrive uno stato, e
    prendere il miglior 200 di sempre insieme a un 400 di quest'anno
    misurerebbe la distanza fra due epoche.
    """
    if not available(connection):
        return []

    def prove(distanza: int) -> list[tuple]:
        return connection.execute("""
            SELECT race_id, pool_length_m, race_date, time_s
            FROM pool_races
            WHERE distance_m = ? AND stroke = ? AND (? IS NULL OR race_date<=?)
            ORDER BY race_date DESC
        """, [distanza, stroke, until, until]).fetchall()

    lunghe, corte = prove(LONG_M), prove(SHORT_M)

    trovate: list[Pair] = []
    for id_lungo, vasca, giorno_lungo, tempo_lungo in lunghe:
        candidate = [una for una in corte
                     if una[1] == vasca
                     and abs((una[2] - giorno_lungo).days) <= PAIR_WINDOW_DAYS]
        if not candidate:
            continue
        id_corto, _, giorno_corto, tempo_corto = min(
            candidate, key=lambda una: abs((una[2] - giorno_lungo).days))

        coppia = Pair(
            pool_length_m=vasca,
            long_race_id=id_lungo, long_day=giorno_lungo,
            long_time_s=tempo_lungo,
            short_race_id=id_corto, short_day=giorno_corto,
            short_time_s=tempo_corto,
            races_between=_races_between(
                connection, giorno_lungo, giorno_corto, id_lungo, id_corto))
        if coppia.plausible:
            trovate.append(coppia)

    trovate.sort(key=lambda una: una.day, reverse=True)
    return trovate


def _races_between(connection: duckdb.DuckDBPyConnection,
                   primo: date, secondo: date,
                   id_lungo: str, id_corto: str) -> int:
    """Quante altre gare ci sono fra le due prove, la coppia esclusa.

    Il 24/05/2026 l'atleta ha nuotato anche un 100 stile fra il 200 e il 400.
    Non è un dettaglio: cambia il significato del risultato, perché il 400 è
    stato nuotato su gambe già usate. È la ragione per cui questa funzione
    esiste invece di una nota scritta a mano — una nota vale per un giorno, il
    conteggio vale per ogni coppia che l'archivio produrrà da qui in avanti.
    """
    dal, al = min(primo, secondo), max(primo, secondo)
    quante = connection.execute("""
        SELECT count(*) FROM pool_races
        WHERE race_date BETWEEN ? AND ?
          AND race_id NOT IN (?, ?)
    """, [dal, al, id_lungo, id_corto]).fetchone()[0]
    return int(quante)


def current(connection: duckdb.DuckDBPyConnection,
            stroke: str = "stile", until: date | None = None) -> Pair | None:
    """La velocità critica di adesso: la coppia più recente."""
    trovate = pairs(connection, stroke, until)
    return trovate[0] if trovate else None


def why_unavailable(connection: duckdb.DuckDBPyConnection,
                    stroke: str = "stile") -> str:
    """Perché non c'è, detto in modo che si sappia cosa manca.

    Un blocco che dice soltanto «non calcolabile» è indistinguibile da un
    guasto. Questo dice quale delle due prove manca, o se ci sono entrambe ma
    troppo lontane: sono tre situazioni diverse e portano a tre azioni diverse.
    """
    if not available(connection):
        return ("Lo storico gare non è ancora in archivio: si importa con "
                "«garmin_coach ingest», leggendo coach/aquatime/.")

    quante = connection.execute("""
        SELECT count(*) FILTER (WHERE distance_m = ?),
               count(*) FILTER (WHERE distance_m = ?)
        FROM pool_races WHERE stroke = ?
    """, [LONG_M, SHORT_M, stroke]).fetchone()
    lunghe, corte = quante

    if not lunghe and not corte:
        return (f"Non c'è nessun {LONG_M} né {SHORT_M} {stroke} in vasca "
                "nell'archivio gare.")
    if not lunghe:
        return (f"Ci sono {corte} prove sui {SHORT_M} {stroke} e nessuna sui "
                f"{LONG_M}: senza la distanza lunga la pendenza non esiste.")
    if not corte:
        return (f"Ci sono {lunghe} prove sui {LONG_M} {stroke} e nessuna sui "
                f"{SHORT_M}: senza la distanza corta la pendenza non esiste.")
    return (f"Ci sono {lunghe} prove sui {LONG_M} e {corte} sui {SHORT_M}, ma "
            f"nessuna coppia nella stessa vasca entro {PAIR_WINDOW_DAYS} "
            "giorni: due prove lontane descrivono due condizioni diverse.")
