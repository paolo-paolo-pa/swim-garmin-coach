"""«Qual è il mio tempo vero, e come distribuisco una gara?»

## Perché questo file esiste

Fino a qui il progetto sapeva quanto l'atleta aveva **nuotato**, non quanto
andasse **forte**. `races.py` lo dichiara da sempre: senza riferimenti confermati
non esiste una curva prestativa, e senza curva una previsione è un numero
decorativo. Lo storico della federazione — 114 gare dal 2014 al 2026, 103 con
cronometraggio automatico — è quella curva.

## Tre letture, e nessuna previsione

1. **I record**, per distanza, stile e vasca. Un 25 e un 50 non si confrontano:
   in vasca corta ci sono il doppio delle virate, e su un 400 valgono secondi.
2. **La progressione** su una specialità: gli stessi metri, negli anni.
3. **La distribuzione della gara**, dai passaggi: apertura, deriva fra prima e
   seconda metà, chiusura. È la cosa che l'orologio non saprà mai fare, perché
   in allenamento non esiste una gara.

Nessuna di queste prevede un tempo. Il passo di riferimento su 1500 e il passo
obiettivo dichiarato per una gara in mare sono **due fatti**, e metterli uno
accanto all'altro è un confronto; dedurre il secondo dal primo sarebbe una
previsione, e su 6,7 volte la distanza, in acqua salata e senza muro, non
esiste nessun modello in questo progetto che la autorizzi.

## Le staffette non sono qui

`personal_races` le lascia fuori. Il tempo è della squadra e i passaggi
descrivono quattro frazioni senza dire quale sia dell'atleta; e anche sapendolo,
chi parte da un cambio parte lanciato e nuota qualche decimo più veloce di
quanto sappia fare da fermo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb

from ..database import table_exists

POOL = "piscina"
OPEN_WATER = "acque libere"

# Sotto questo numero di passaggi non si può parlare di distribuzione: con due
# metà e nient'altro, «deriva» è la differenza fra due numeri.
MIN_SPLITS_FOR_PACING = 4

# Quanto deve cambiare il passo fra prima e seconda metà perché valga la pena
# dirlo. **Scelta, non misurata**, e va guardata in audit: con l'1% che c'era
# prima, il 1500 del 15/02/2026 — trenta parziali fra 35,99 e 39,62, chiuso
# accelerando — usciva «in calando», e una gara nuotata bene descritta come una
# gara nuotata male insegna a non leggere il verdetto. Il 2% lascia «regolare»
# quel 1500 (+1,8%) e il 400 del 02/06 (+1,1%), e tiene «in calando» il 400 del
# 24/05 (+6,2%), che si era davvero sfaldato.
NOISE_PACING_PCT = 2.0

# La stagione del nuoto non è l'anno solare: comincia a settembre e finisce ad
# agosto. Non è una preferenza estetica — le gare invernali e quelle primaverili
# della stessa preparazione cadono in due anni solari diversi, e spezzarle
# separerebbe il Christmas Swim di dicembre dal Regionale di febbraio, che sono
# lo stesso inverno di lavoro.
SEASON_START_MONTH = 9

# Sotto questa differenza due tempi non sono un miglioramento, sono lo stesso
# tempo nuotato due volte. **Scelta, non misurata su questo atleta**: viene
# dall'ordine di grandezza della variabilità individuale in vasca, e va
# sostituita con un valore documentato quando `knowledge/` avrà la scheda sulla
# variabilità della prestazione. Fino ad allora resta dichiarata come scelta.
SEASON_NOISE_PCT = 0.8

# Sotto questi numeri una progressione è un aneddoto: due punti in due stagioni
# diverse non descrivono una direzione.
MIN_SEASONS_FOR_PROGRESSION = 2
MIN_RACES_FOR_PROGRESSION = 3

# Oltre questa distanza una nuotata in mare è abbastanza rara da meritare la
# domanda «era una gara?». Sotto, sono uscite di allenamento e chiederlo a ogni
# apertura sarebbe rumore.
LONG_OPEN_WATER_M = 5000

# Luoghi dove l'atleta ha dichiarato, il 23/08/2026, di allenarsi abitualmente
# in mare aperto — non gare, per quanto lunga sia stata la nuotata quel giorno.
# place01 l'aveva già prodotto un candidato falso, 8.761 m il 02/06/2018.
#
# Il confronto è sul campo `name` che Garmin assegna in base alla posizione di
# partenza: è un dato, non un'istruzione, e qui viene letto come tale — la
# stessa distinzione per cui i nomi delle attività non vengono mai eseguiti
# come comandi vale anche al contrario, per non trattarli con più sospetto del
# necessario quando servono solo a filtrare un luogo.
#
# place03 si aggiunge il 24/08/2026, stessa dichiarazione esplicita, dopo che il
# rilevatore aveva prodotto quattro candidati lì (26/08/2023, 28/07/2024,
# 03/08/2024, 04/08/2024, tutti 5-6 km).
#
# Questa è una dichiarazione dell'atleta, non un'euristica: se un giorno farà
# una gara vera a place01, place02 o place03, la scrive in
# gare-dichiarate.md e il rilevatore la ignora comunque — il rilevatore serve
# solo a trovare gare perse, non a bloccarne l'inserimento manuale.
KNOWN_TRAINING_LOCATIONS = ("place01", "place02", "place03")

# Quanto può essere più veloce, in mare, del proprio miglior 1500 in vasca.
#
# In acque libere si nuota di norma **più piano** che in piscina: niente muri da
# spingere, acqua mossa, traiettoria mai perfetta. Una corrente favorevole o una
# muta possono ribaltarlo, ma non di molto. Oltre questo margine il numero non
# descrive più una nuotata: descrive un percorso più corto di quanto l'abbiano
# chiamato.
#
# **Scelta, non misurata.** Ma la conclusione a cui porta è verificata: dei
# diciannove percorsi con una distanza dichiarata, ne segnala tre, e su due di
# quelli il passo che ne uscirebbe è più veloce del miglior 100 m in vasca di
# questa persona.
OPEN_WATER_FASTER_MARGIN = 0.10

CREDIBLE = "credibile"
SUSPECT = "sospetta"
IMPOSSIBLE = "impossibile"
UNVERIFIABLE = "non verificabile"


def _show_time(seconds: float | None) -> str:
    """Il tempo come lo scrive la federazione: 1'08"46 e 25"97, non 68.46.

    I centesimi si separano con le virgolette e non con il punto, perché è così
    che l'atleta li ha letti sul tabellone per dodici anni. Un tempo di nuoto
    scritto in notazione decimale si legge come una misura qualsiasi, e non lo è.
    """
    if seconds is None:
        return "—"
    minuti, resto = divmod(round(seconds, 2), 60)
    secondi, centesimi = divmod(round(resto * 100), 100)
    if minuti:
        return f"{int(minuti)}'{int(secondi):02d}\"{int(centesimi):02d}"
    return f"{int(secondi)}\"{int(centesimi):02d}"


def _show_pace(seconds_per_100: float | None) -> str:
    if seconds_per_100 is None:
        return "—"
    centesimi = round(seconds_per_100 * 100)
    minuti, resto = divmod(centesimi, 6000)
    return f"{minuti}:{resto / 100:05.2f}/100 m"


@dataclass(frozen=True)
class Best:
    distance_m: int
    stroke: str
    pool_length_m: int
    time_s: float
    day: date
    meet: str
    races: int

    @property
    def pace_per_100(self) -> float:
        return self.time_s / self.distance_m * 100

    @property
    def label(self) -> str:
        return f"{self.distance_m} {self.stroke}, vasca da {self.pool_length_m} m"

    @property
    def display(self) -> str:
        return _show_time(self.time_s)


@dataclass(frozen=True)
class Pacing:
    """Come è stata distribuita una gara, dai passaggi ufficiali."""

    race_id: str
    day: date
    label: str
    time_s: float
    opening: float          # passo del primo tratto, per 100 m
    first_half: float       # passo medio della prima metà, esclusi primo e ultimo
    second_half: float
    closing: float
    splits: int

    @property
    def drift_pct(self) -> float:
        if not self.first_half:
            return 0.0
        return (self.second_half - self.first_half) / self.first_half * 100

    @property
    def verdict(self) -> str:
        if abs(self.drift_pct) < NOISE_PACING_PCT:
            return "regolare"
        return "in calando" if self.drift_pct > 0 else "in crescendo"


@dataclass(frozen=True)
class Season:
    """Il miglior tempo di una stagione su una specialità."""

    label: str              # «2025/26», come lo dice un nuotatore
    started: int            # l'anno in cui la stagione è cominciata
    best_s: float
    races: int
    day: date               # il giorno del miglior tempo
    meet: str
    last_day: date          # l'ultima gara della stagione su questa distanza

    # I due giorni sono diversi e servono a due cose diverse: `day` risponde a
    # «quando l'ho fatto», `last_day` a «quando l'ho nuotata l'ultima volta».
    # Confonderli fa dire «l'ultima gara è del 10/01» quando quel giorno è
    # soltanto il migliore e l'ultima è di quattro mesi dopo.


@dataclass(frozen=True)
class Progression:
    """Gli stessi metri, nella stessa vasca, stagione dopo stagione."""

    distance_m: int
    stroke: str
    pool_length_m: int
    seasons: list[Season]

    @property
    def label(self) -> str:
        return f"{self.distance_m} {self.stroke}, vasca da {self.pool_length_m} m"

    @property
    def races(self) -> int:
        return sum(una.races for una in self.seasons)

    @property
    def best(self) -> Season:
        return min(self.seasons, key=lambda una: una.best_s)

    @property
    def latest(self) -> Season:
        return self.seasons[-1]

    @property
    def previous(self) -> Season | None:
        return self.seasons[-2] if len(self.seasons) > 1 else None

    @property
    def delta_s(self) -> float | None:
        """Quanto è cambiata l'ultima stagione rispetto a quella prima.

        Negativo vuol dire più veloce. Non è la distanza dal record: quella la
        dice `gap_to_best_s`, ed è un'altra domanda.
        """
        prima = self.previous
        return None if prima is None else self.latest.best_s - prima.best_s

    @property
    def gap_to_best_s(self) -> float:
        return self.latest.best_s - self.best.best_s

    @property
    def verdict(self) -> str:
        """Migliorata, stabile o peggiorata — e «non confrontabile» se manca il prima.

        Le stagioni saltate non fanno testo: il confronto è sempre fra le due
        stagioni **presenti** più recenti, e quante ce ne sono in mezzo lo dice
        l'etichetta.
        """
        scarto = self.delta_s
        if scarto is None:
            return "non confrontabile"
        prima = self.previous
        if abs(scarto) / prima.best_s * 100 < SEASON_NOISE_PCT:
            return "stabile"
        return "migliorata" if scarto < 0 else "peggiorata"


@dataclass(frozen=True)
class OpenWaterRace:
    """Una gara in mare: il tempo è misurato, la distanza è dichiarata.

    Il campo `credibility` non giudica la nuotata, giudica il **denominatore**.
    L'atleta l'aveva detto prima di vedere i dati: «i tempi non possono essere
    precisi a causa delle distanze quasi mai precise con quelle indicate dalla
    gara». Il metro di paragone è lui stesso, e non una costante universale:
    nessuno nuota due chilometri in mare al passo del proprio miglior 100 in
    vasca, e se il conto dice di sì il conto ha il numeratore giusto e il
    denominatore sbagliato.
    """

    day: date
    meet: str
    venue: str | None
    event_label: str
    time_s: float
    distance_m: int | None
    distance_source: str
    overall_place: int | None
    category_place: int | None
    credibility: str = UNVERIFIABLE
    credibility_reason: str = ""
    conditions: dict | None = None

    @property
    def speed_ms(self) -> float | None:
        if not self.distance_m:
            return None
        return self.distance_m / self.time_s

    @property
    def pace_100_s(self) -> float | None:
        """Il passo, quando c'è una distanza **e** quella distanza regge.

        Quando non regge il passo non viene calcolato più prudente: non viene
        calcolato. È la stessa scelta del criterio C12 sulle velocità massime
        dell'orologio — una velocità impossibile non è una velocità — e il
        tempo, che è misurato, resta comunque visibile.
        """
        if not self.distance_m or self.credibility == IMPOSSIBLE:
            return None
        return self.time_s / self.distance_m * 100


@dataclass
class RaceHistory:
    bests: list[Best] = field(default_factory=list)
    last: dict | None = None
    pacings: list[Pacing] = field(default_factory=list)
    endurance: Best | None = None
    progressions: list[Progression] = field(default_factory=list)
    open_water: list[OpenWaterRace] = field(default_factory=list)
    coverage: str = ""
    limitations: list[str] = field(default_factory=list)


def available(connection: duckdb.DuckDBPyConnection) -> bool:
    return table_exists(connection, "races")


def bests(connection: duckdb.DuckDBPyConnection, until: date | None = None) -> list[Best]:
    """Il tempo migliore per ogni specialità, con quando e dove.

    Raggruppa anche per vasca: un 400 in vasca da 25 ha sette virate in più di
    uno in vasca da 50, e confonderli renderebbe un record una media di due cose.

    Legge `pool_races` e non `personal_races`: le gare in mare hanno una
    distanza dichiarata dall'organizzazione, e un «record sui 3.000» costruito
    su due percorsi diversi chiamati entrambi 3.000 non è un record.
    """
    righe = connection.execute("""
        WITH migliori AS (
            SELECT distance_m, stroke, pool_length_m, min(time_s) AS tempo,
                   count(*) AS quante
            FROM pool_races
              WHERE (? IS NULL OR race_date<=?)
            GROUP BY 1, 2, 3
        )
        SELECT m.distance_m, m.stroke, m.pool_length_m, m.tempo,
               min(r.race_date), min(r.meet), m.quante
        FROM migliori m
        JOIN pool_races r
          ON r.distance_m = m.distance_m AND r.stroke = m.stroke
         AND r.pool_length_m = m.pool_length_m AND r.time_s = m.tempo
          WHERE (? IS NULL OR r.race_date<=?)
        GROUP BY 1, 2, 3, 4, 7
        ORDER BY m.pool_length_m, m.stroke, m.distance_m
    """,[until,until,until,until]).fetchall()
    return [Best(*riga) for riga in righe]


def last_race(connection: duckdb.DuckDBPyConnection,
              today: date | None = None) -> dict | None:
    """L'ultima gara vera, e quanto tempo fa.

    Serve al coach più del record: un record di otto anni fa non dice come si
    sta adesso, mentre «hai gareggiato dodici settimane fa» sì.
    """
    riga = connection.execute("""
        SELECT race_id, race_date, distance_m, stroke, pool_length_m, time_s,
               meet, environment, event_label, distance_source
        FROM personal_races WHERE race_date<=? ORDER BY race_date DESC, time_s LIMIT 1
    """,[today or date.today()]).fetchone()
    if not riga:
        return None
    (race_id, giorno, distanza, stile, vasca, tempo, dove, ambiente,
     etichetta, origine_distanza) = riga
    quando = today or date.today()

    if ambiente == OPEN_WATER:
        # In mare la frase non può avere la forma «400 stile in vasca da 25»:
        # non c'è vasca, spesso non c'è distanza, e lo stile non è dichiarato.
        # Dire «None stile in vasca da None m» sarebbe il modo più veloce di
        # far smettere di credere a tutto il resto della pagina.
        quanto = f"{distanza} m dichiarati" if distanza else "distanza non dichiarata"
        display = f"{dove} in acque libere, {quanto}, {_show_time(tempo)}"
    else:
        display = f"{distanza} {stile} in vasca da {vasca} m, {_show_time(tempo)}"

    return {
        "race_id": race_id, "day": giorno, "distance_m": distanza,
        "stroke": stile, "pool_length_m": vasca, "time_s": tempo, "meet": dove,
        "environment": ambiente, "event_label": etichetta,
        "distance_source": origine_distanza,
        "days_ago": (quando - giorno).days,
        "display": display,
        "pace_display": _show_pace(tempo / distanza * 100) if distanza else "—",
    }


def endurance_reference(connection: duckdb.DuckDBPyConnection, until: date | None = None) -> Best | None:
    """La prova più lunga a stile: il riferimento più vicino al fondo.

    Non è il 10 km in mare e non lo diventa. È il passo che questa persona ha
    dimostrato di saper tenere sulla distanza più lunga che ha nuotato in gara,
    e serve a mettere un numero accanto a un obiettivo invece di lasciarlo solo.
    """
    # `bests` legge già soltanto la vasca: il riferimento di fondo resta una
    # misura in piscina anche quando l'obiettivo è in mare, e la pagina lo dice.
    candidati = [uno for uno in bests(connection,until=until)
                 if uno.stroke == "stile" and uno.distance_m >= 400]
    return max(candidati, key=lambda uno: uno.distance_m) if candidati else None


def pacing(connection: duckdb.DuckDBPyConnection,
           limit: int = 6) -> list[Pacing]:
    """Come sono state distribuite le gare che hanno abbastanza passaggi.

    Il primo tratto e l'ultimo escono dal confronto fra le due metà. Il primo
    contiene il tuffo e il secondo la volata: sono i due tratti che non
    descrivono il ritmo, e lasciarli dentro farebbe sembrare «in calando» ogni
    gara nuotata bene.

    **I misti restano fuori.** In un 200 misti le quattro frazioni sono quattro
    stili diversi, e la rana è sempre la più lenta: il confronto fra prima e
    seconda metà misura l'ordine delle bracciate, non il ritmo. Sul 200 misti
    del 15/02/2026 dava «in calando del 26%», che non descrive niente di quella
    gara.
    """
    gare = connection.execute(f"""
        SELECT r.race_id, r.race_date, r.distance_m, r.stroke, r.pool_length_m,
               r.time_s, count(*) AS passaggi
        FROM race_splits sp
        JOIN personal_races r USING (race_id)
        WHERE sp.split_s IS NOT NULL AND r.stroke <> 'misti'
        GROUP BY 1, 2, 3, 4, 5, 6
        HAVING count(*) >= {MIN_SPLITS_FOR_PACING}
        ORDER BY r.race_date DESC
        LIMIT {int(limit)}
    """).fetchall()

    trovate: list[Pacing] = []
    for race_id, giorno, distanza, stile, vasca, tempo, quanti in gare:
        parziali = connection.execute("""
            SELECT split_m, split_s FROM race_splits
            WHERE race_id = ? AND split_s IS NOT NULL ORDER BY split_m
        """, [race_id]).fetchall()
        if len(parziali) < MIN_SPLITS_FOR_PACING:
            continue

        # Ogni parziale diventa un passo per 100 m, così un 400 diviso in otto
        # tratti da 50 e uno diviso in quattro da 100 si leggono allo stesso modo.
        lunghezza = parziali[1][0] - parziali[0][0] if len(parziali) > 1 else None
        if not lunghezza:
            continue
        passi = [secondi / lunghezza * 100 for _, secondi in parziali]

        centrali = passi[1:-1] or passi
        meta = len(centrali) // 2 or 1
        trovate.append(Pacing(
            race_id=race_id, day=giorno,
            label=f"{distanza} {stile}, vasca da {vasca} m", time_s=tempo,
            opening=passi[0],
            first_half=sum(centrali[:meta]) / meta,
            second_half=sum(centrali[meta:]) / max(len(centrali[meta:]), 1),
            closing=passi[-1], splits=len(parziali)))
    return trovate


def season_of(day: date) -> tuple[int, str]:
    """A quale stagione appartiene un giorno. Settembre apre, agosto chiude.

    Restituisce l'anno d'inizio e l'etichetta come la scrive un nuotatore:
    il 14/12/2025 e il 15/02/2026 sono tutti e due «2025/26», perché sono lo
    stesso inverno di lavoro.
    """
    inizio = day.year if day.month >= SEASON_START_MONTH else day.year - 1
    return inizio, f"{inizio}/{(inizio + 1) % 100:02d}"


def progressions(connection: duckdb.DuckDBPyConnection,
                 min_seasons: int = MIN_SEASONS_FOR_PROGRESSION,
                 min_races: int = MIN_RACES_FOR_PROGRESSION) -> list[Progression]:
    """Gli stessi metri, negli anni. La lettura che l'archivio prometteva.

    Il record dice il giorno migliore di sempre e non dice se si sta andando
    avanti o indietro: un 25"97 del 2018 non racconta niente del 2026. La
    progressione mette in fila le stagioni e lascia vedere la direzione.

    **Una stagione, un tempo.** Dentro una stagione conta il migliore, non la
    media: la media di una stagione con quattro gare e una con una sola non si
    confrontano, e nessun nuotatore pensa alla propria stagione come a una media.

    Restano fuori le specialità con poche gare o una stagione sola. Non per
    prudenza formale: con due punti in una stagione sola non esiste una
    direzione da leggere, ed esporla come se ci fosse è il modo in cui una
    dashboard comincia a mentire.
    """
    if not available(connection):
        return []

    righe = connection.execute("""
        SELECT distance_m, stroke, pool_length_m, race_date, time_s, meet
        FROM pool_races
        ORDER BY distance_m, stroke, pool_length_m, race_date
    """).fetchall()

    per_specialita: dict[tuple, dict[int, list]] = {}
    for distanza, stile, vasca, giorno, tempo, dove in righe:
        inizio, _ = season_of(giorno)
        stagioni = per_specialita.setdefault((distanza, stile, vasca), {})
        stagioni.setdefault(inizio, []).append((tempo, giorno, dove))

    trovate: list[Progression] = []
    for (distanza, stile, vasca), stagioni in per_specialita.items():
        if len(stagioni) < min_seasons:
            continue
        if sum(len(gare) for gare in stagioni.values()) < min_races:
            continue

        elenco = []
        for inizio in sorted(stagioni):
            gare = stagioni[inizio]
            tempo, giorno, dove = min(gare, key=lambda una: una[0])
            elenco.append(Season(
                label=season_of(giorno)[1], started=inizio, best_s=tempo,
                races=len(gare), day=giorno, meet=dove,
                last_day=max(una[1] for una in gare)))
        trovate.append(Progression(distanza, stile, vasca, elenco))

    # Prima le specialità più frequentate: sono quelle su cui l'atleta ha
    # davvero una storia, e quindi quelle su cui la direzione significa qualcosa.
    trovate.sort(key=lambda una: (-una.races, una.distance_m))
    return trovate


def open_water(connection: duckdb.DuckDBPyConnection,
               limit: int | None = None) -> list[OpenWaterRace]:
    """Le gare in mare, dalla più recente.

    Sono la storia che conta di più verso un obiettivo in acque libere, ed è
    anche quella che l'orologio non sa raccontare: una traccia GPS dice dove sei
    passato, non contro chi stavi nuotando.

    Il passo, quando c'è, nasce da una distanza **dichiarata**. Resta utile e va
    letto come tale.
    """
    if not available(connection):
        return []
    righe = connection.execute("""
        SELECT race_date, meet, venue, event_label, time_s, distance_m,
               distance_source, overall_place, category_place
        FROM open_water_races
        ORDER BY race_date DESC
    """).fetchall()
    metro = _own_speed_limits(connection)
    meteo = _conditions_by_day(connection)
    gare = [_judged(OpenWaterRace(*riga, conditions=meteo.get(riga[0])), metro)
            for riga in righe]
    return gare[:limit] if limit else gare


def _conditions_by_day(connection: duckdb.DuckDBPyConnection) -> dict:
    """Le condizioni del giorno, per le gare che hanno una nuotata collegata.

    L'aggancio passa da `races.activity_id`: senza quel collegamento — che è
    esistito solo come riga di markdown fino alla migrazione 0011 — non ci
    sarebbe modo di sapere dove chiedere che tempo faceva.

    Le gare di Icron restano senza: nessuno ha dichiarato quale nuotata le
    registri, e indovinarlo per data è la scorciatoia che il progetto ha già
    deciso di non prendere.
    """
    if not table_exists(connection, "race_conditions"):
        return {}
    righe = connection.execute("""
        SELECT r.race_date, c.air_temperature_c, c.water_temperature_c,
               c.wind_speed_kmh, c.wind_direction_deg, c.wave_height_m
        FROM races r
        JOIN race_conditions c ON c.activity_id = r.activity_id
        WHERE r.environment = ?
    """, [OPEN_WATER]).fetchall()
    return {riga[0]: {"air_c": riga[1], "water_c": riga[2],
                      "wind_kmh": riga[3], "wind_from_deg": riga[4],
                      "wave_m": riga[5]} for riga in righe}


# I punti cardinali, per dire «da nord-ovest» invece di «da 323 gradi». Un
# numero in gradi è esatto e non si legge; un nuotatore che ricorda quella gara
# ricorda da che parte veniva il vento, non un azimut.
COMPASS = ("nord", "nord-est", "est", "sud-est",
           "sud", "sud-ovest", "ovest", "nord-ovest")


def compass_of(degrees: float | None) -> str | None:
    """Il settore da cui soffia, in parole."""
    if degrees is None:
        return None
    return COMPASS[int((degrees % 360) / 45 + 0.5) % 8]


def conditions_display(conditions: dict | None) -> str:
    """Le condizioni in una riga, saltando quello che il modello non copre.

    Sul lake01 acqua e onda restano vuote perché il modello marino non
    copre i laghi. È un'assenza legittima e non un guasto: si tace su quelle
    due e si dice il resto, invece di scrivere «non disponibile» tre volte.
    """
    if not conditions:
        return ""
    pezzi = []
    if conditions.get("water_c") is not None:
        pezzi.append(f"acqua {conditions['water_c']:.0f} °C")
    if conditions.get("air_c") is not None:
        pezzi.append(f"aria {conditions['air_c']:.0f} °C")
    if conditions.get("wind_kmh") is not None:
        vento = f"vento {conditions['wind_kmh']:.0f} km/h"
        direzione = compass_of(conditions.get("wind_from_deg"))
        pezzi.append(f"{vento} da {direzione}" if direzione else vento)
    if conditions.get("wave_m") is not None:
        pezzi.append(f"onda {conditions['wave_m']:.2f} m".replace(".", ","))
    return " · ".join(pezzi)


def _own_speed_limits(connection: duckdb.DuckDBPyConnection) -> tuple:
    """Le due velocità di questa persona che fanno da metro in mare.

    Il miglior 100 in vasca è il tetto assoluto: è la velocità più alta che
    questo atleta abbia mai tenuto per più di un minuto, e nessun percorso in
    mare la supera per venti minuti. Il miglior 1500 è il riferimento
    ragionevole: è il passo di fondo dimostrato, e in mare ci si sta sotto.

    Se manca l'una o l'altra il giudizio non viene dato. Un metro assente non
    diventa un metro generico.
    """
    riga = connection.execute("""
        SELECT max(CASE WHEN distance_m = 100 THEN 100.0 / time_s END),
               max(CASE WHEN distance_m = 1500 THEN 1500.0 / time_s END)
        FROM pool_races WHERE stroke = 'stile'
    """).fetchone()
    return riga if riga else (None, None)


def _judged(gara: OpenWaterRace, metro: tuple) -> OpenWaterRace:
    from dataclasses import replace

    tetto, fondo = metro
    velocita = gara.speed_ms
    if velocita is None:
        return replace(gara, credibility=UNVERIFIABLE,
                       credibility_reason="La gara non dichiara una distanza.")
    if tetto is None or fondo is None:
        return replace(
            gara, credibility=UNVERIFIABLE,
            credibility_reason=("Manca un 100 o un 1500 stile in vasca con cui "
                                "confrontare: senza metro non do un giudizio."))

    if velocita > tetto:
        return replace(
            gara, credibility=IMPOSSIBLE,
            credibility_reason=(
                f"{gara.distance_m} m in {_show_time(gara.time_s)} vorrebbe dire "
                f"{_show_pace(gara.time_s / gara.distance_m * 100)}, più veloce "
                f"del tuo miglior 100 stile in vasca. Il tempo è cronometrato: "
                "è la distanza dichiarata a non reggere."))
    if velocita > fondo * (1 + OPEN_WATER_FASTER_MARGIN):
        return replace(
            gara, credibility=SUSPECT,
            credibility_reason=(
                f"Il passo che ne esce è più veloce del tuo miglior 1500 in "
                f"vasca di oltre il {OPEN_WATER_FASTER_MARGIN:.0%}. Può essere "
                "corrente a favore, può essere un percorso più corto del "
                "dichiarato: da qui non si distingue."))
    return replace(gara, credibility=CREDIBLE, credibility_reason="")


def long_swims_not_recorded_as_races(
        connection: duckdb.DuckDBPyConnection) -> list[dict]:
    """Nuotate lunghe in mare che in archivio non risultano gare.

    ## Perché questa funzione esiste

    Il 23/08/2026 il coach ha scritto «il tuo unico 10 km», e l'atleta ha
    risposto di averne nuotati almeno tre: place23, place05 e place21.
    Icron ne espone uno solo, perché le gare fuori dal proprio circuito non le
    cronometra. Il coach non aveva sbagliato un conto — aveva scambiato
    **quello che l'archivio contiene** per **quello che l'atleta ha fatto**.

    L'orologio però quelle nuotate le ha viste. Questa funzione le mette in
    fila e lascia che sia l'atleta a dire quali erano gare: è la stessa forma
    dello strato delle correzioni confermate — la macchina segnala dove
    guardare, la persona decide cos'è successo.

    Non promuove niente da sola. Una nuotata di dieci chilometri in mare può
    essere una gara o una domenica.
    """
    if not table_exists(connection, "canonical_activities"):
        return []

    giorni_gara = {riga[0] for riga in connection.execute(
        "SELECT race_date FROM races WHERE environment = ?",
        [OPEN_WATER]).fetchall()} if available(connection) else set()

    righe = connection.execute("""
        SELECT activity_date, activity_id, distance_m, duration_s, name
        FROM canonical_activities
        WHERE is_swim AND pool_length_m IS NULL AND distance_m >= ?
        ORDER BY activity_date DESC
    """, [LONG_OPEN_WATER_M]).fetchall()

    def in_zona_di_allenamento(nome: str | None) -> bool:
        basso = (nome or "").lower()
        return any(luogo in basso for luogo in KNOWN_TRAINING_LOCATIONS)

    return [{
        "day": giorno,
        "activity_id": activity_id,
        "distance_m": int(metri),
        "duration_s": durata,
        "display": (f"{giorno.strftime('%d/%m/%Y')} — "
                    f"{int(metri):,} m in {int(durata // 3600)}h"
                    f"{int(durata % 3600 // 60):02d}'").replace(",", "."),
    } for giorno, activity_id, metri, durata, nome in righe
        if giorno not in giorni_gara and durata and not in_zona_di_allenamento(nome)]


def history(connection: duckdb.DuckDBPyConnection,
            today: date | None = None) -> RaceHistory:
    """Tutto quello che le gare ufficiali dicono, in un oggetto solo."""
    quadro = RaceHistory()
    if not available(connection):
        quadro.limitations.append(
            "Lo storico gare non è ancora stato importato. Si ottiene con "
            "«garmin_coach ingest», leggendo coach/aquatime/.")
        return quadro

    quadro.bests = bests(connection)
    quadro.last = last_race(connection, today)
    quadro.pacings = pacing(connection)
    quadro.endurance = endurance_reference(connection)
    quadro.progressions = progressions(connection)
    quadro.open_water = open_water(connection)

    conteggi = connection.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE is_relay),
               count(*) FILTER (WHERE status = 'disqualified'),
               count(*) FILTER (WHERE status = 'invalid'),
               count(*) FILTER (WHERE timing = 'M'),
               min(race_date), max(race_date)
        FROM races
    """).fetchone()
    totali, staffette, squalifiche, non_valide, manuali, primo, ultimo = conteggi
    if not totali:
        quadro.limitations.append("Nessuna gara in archivio.")
        return quadro

    in_vasca, in_mare = connection.execute("""
        SELECT count(*) FILTER (WHERE environment = 'piscina'),
               count(*) FILTER (WHERE environment = 'acque libere')
        FROM races
    """).fetchone()

    quadro.coverage = (
        f"{totali} risultati dal {primo.strftime('%d/%m/%Y')} al "
        f"{ultimo.strftime('%d/%m/%Y')}: {in_vasca} in vasca e {in_mare} in "
        f"acque libere. Di quelli in vasca, {staffette} sono staffette e "
        f"{squalifiche} squalifiche: non entrano in nessun record.")

    senza_distanza = sum(1 for una in quadro.open_water if una.distance_m is None)
    if senza_distanza:
        quadro.limitations.append(
            f"{senza_distanza} gare in mare non dichiarano una distanza: Icron "
            "espone la categoria («MASTER», «AGONISTI») al posto dei metri. "
            "Restano in archivio con il loro tempo e senza passo, perché "
            "sceglierne uno vorrebbe dire inventarlo.")

    non_credibili = [una for una in quadro.open_water
                     if una.credibility in (IMPOSSIBLE, SUSPECT)]
    if non_credibili:
        quadro.limitations.append(
            f"{len(non_credibili)} gare in mare hanno una distanza dichiarata "
            "che non regge al confronto con i tuoi tempi in vasca. Il tempo è "
            "cronometrato e resta; il passo, dove è impossibile, non viene "
            "calcolato.")

    if non_valide:
        quadro.limitations.append(
            f"{non_valide} risultati hanno un tempo assente o in un formato "
            "non riconosciuto: restano tracciati come non validi e non "
            "entrano nei record.")

    if manuali:
        quadro.limitations.append(
            f"{manuali} risultati hanno cronometraggio manuale, che vale qualche "
            "decimo in meno di quello automatico. Restano in archivio con la "
            "loro etichetta.")
    quadro.limitations.append(
        "Vasca da 25 e da 50 restano separate: su un 400 le virate in più "
        "valgono secondi, e mescolarle farebbe di un record una media.")
    quadro.limitations.append(
        "Record e progressioni leggono solo la vasca. In mare la distanza è "
        "quella che l'organizzazione ha dichiarato, non una misura: due "
        "percorsi chiamati entrambi 3.000 non si confrontano.")
    return quadro


def _progression_summary(una: Progression) -> str:
    """La direzione in una frase, con dentro i numeri che la giustificano."""
    ultima, record = una.latest, una.best
    testa = (f"{una.races} gare in {len(una.seasons)} stagioni. "
             f"Meglio di sempre: {_show_time(record.best_s)} nel "
             f"{record.label}.")

    prima = una.previous
    if prima is None:
        return f"{testa} Una stagione sola con questo tempo: non c'è direzione."

    scarto = una.delta_s
    salto = ultima.started - prima.started
    ponte = ("" if salto == 1 else
             f" (con {salto - 1} stagione saltata)" if salto == 2 else
             f" (con {salto - 1} stagioni saltate)")
    verso = ("uguale" if una.verdict == "stabile"
             else f"{abs(scarto):.2f} s {'più veloce' if scarto < 0 else 'più lento'}")
    coda = (f" Nel {ultima.label} sei {verso} rispetto al {prima.label}"
            f"{ponte}: {_show_time(ultima.best_s)} contro "
            f"{_show_time(prima.best_s)}.")

    if ultima.best_s > record.best_s:
        coda += f" Dal record ti separano {una.gap_to_best_s:.2f} s."

    # Senza questa riga «nel 2017/18 sei uguale al 2016/17» si legge come una
    # notizia di adesso, e sono otto anni fa. Una progressione che non dice
    # quando finisce descrive un atleta che non esiste più.
    coda += (f" L'ultima gara su questa distanza è del "
             f"{ultima.last_day.strftime('%d/%m/%Y')}.")
    return testa + coda


def _place_display(una: OpenWaterRace) -> str:
    """Il piazzamento, quando c'è. In mare è l'unico confronto onesto.

    Due percorsi «da 3 km» con corrente diversa danno tempi che non si mettono
    uno accanto all'altro; la posizione, dentro la stessa gara e contro le
    stesse persone, sì. Non è una misura di forma — dipende da chi si è
    presentato — ed è mostrata come fatto.
    """
    pezzi = []
    if una.overall_place:
        pezzi.append(f"{una.overall_place}° assoluto")
    if una.category_place:
        pezzi.append(f"{una.category_place}° di categoria")
    return " · ".join(pezzi)


def as_page_dict(quadro: RaceHistory) -> dict:
    """Il quadro come lo riceve una pagina: solo testo, niente da calcolare.

    Ogni stringa nasce qui e non nel template. Dividere un tempo per una
    distanza dentro una pagina HTML sarebbe una formula in un template, e il
    test `test_app_computes_nothing` legge l'albero sintattico dell'app proprio
    per impedirlo.
    """
    corpo: dict = {"coverage": quadro.coverage,
                   "limitations": list(quadro.limitations)}

    corpo["bests"] = [{
        "label": uno.label,
        "time": uno.display,
        "pace": _show_pace(uno.pace_per_100),
        "day": uno.day.strftime("%d/%m/%Y"),
        "races": (f"{uno.races} gare su questa distanza" if uno.races > 1
                  else "una sola gara su questa distanza"),
    } for uno in quadro.bests]

    if quadro.last:
        ultima = quadro.last
        frase = f"L'ultima gara è di {ultima['days_ago']} giorni fa: {ultima['display']}"
        if ultima["environment"] == OPEN_WATER:
            # La sintesi in cima non deve promuovere senza avvertenza il passo
            # di una distanza che la stessa pagina giudica sospetta più sotto.
            # Per una distanza impossibile/non verificabile il passo sparisce;
            # per una sospetta resta leggibile, ma con la cautela nello stesso
            # periodo e non affidata a una scheda molte righe più in basso.
            giudicata = next((una for una in quadro.open_water
                              if una.day == ultima["day"]
                              and una.meet == ultima["meet"]
                              and una.time_s == ultima["time_s"]
                              and una.distance_m == ultima["distance_m"]), None)
            if giudicata and giudicata.pace_100_s is not None:
                frase += f", cioè {_show_pace(giudicata.pace_100_s)}"
                if giudicata.credibility == SUSPECT:
                    frase += " sulla distanza dichiarata, dato sospetto"
        else:
            frase += f", cioè {ultima['pace_display']}"
        corpo["last"] = frase + "."
    if quadro.endurance:
        corpo["endurance"] = (
            f"Il riferimento più lungo che hai in gara è il "
            f"{quadro.endurance.label}: {quadro.endurance.display}, cioè "
            f"{_show_pace(quadro.endurance.pace_per_100)}. È una misura in "
            "piscina e non una previsione per il mare.")

    corpo["progressions"] = [{
        "label": una.label,
        "verdict": una.verdict,
        "summary": _progression_summary(una),
        "seasons": [{
            "label": stagione.label,
            "time": _show_time(stagione.best_s),
            "pace": _show_pace(stagione.best_s / una.distance_m * 100),
            "races": (f"{stagione.races} gare" if stagione.races > 1
                      else "1 gara"),
            "day": stagione.day.strftime("%d/%m/%Y"),
            "is_best": stagione.best_s == una.best.best_s,
        } for stagione in una.seasons],
    } for una in quadro.progressions]

    corpo["open_water"] = [{
        "day": una.day.strftime("%d/%m/%Y"),
        "meet": una.meet,
        "venue": una.venue or "",
        "time": _show_time(una.time_s),
        "distance": (f"{una.distance_m} m dichiarati" if una.distance_m
                     else "distanza non dichiarata"),
        "pace": (f"{_show_pace(una.pace_100_s)} sulla distanza dichiarata"
                 if una.pace_100_s else "—"),
        "place": _place_display(una),
        "warning": una.credibility_reason,
        "conditions": conditions_display(una.conditions),
    } for una in quadro.open_water]

    corpo["pacings"] = [{
        "day": una.day.strftime("%d/%m/%Y"),
        "label": una.label,
        "verdict": una.verdict,
        "detail": (f"{_show_time(una.time_s)} · apertura "
                   f"{_show_pace(una.opening)} · prima metà "
                   f"{_show_pace(una.first_half)} · seconda metà "
                   f"{_show_pace(una.second_half)} · chiusura "
                   f"{_show_pace(una.closing)} · deriva "
                   f"{una.drift_pct:+.1f}% su {una.splits} passaggi"),
    } for una in quadro.pacings]
    return corpo
