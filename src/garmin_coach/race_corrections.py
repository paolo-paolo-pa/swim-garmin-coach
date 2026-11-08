"""Le decisioni dell'atleta sulle gare, da ``coach/correzioni-gare.md``.

## La domanda dell'atleta

*«Questa gara è la nuotata che ho sull'orologio, o sono due cose diverse?»*

Il volume conta le gare in mare come nuotate vere, perché in mare l'orologio
spesso non è ammesso. Serve allora sapere, gara per gara, se quella gara **è**
una nuotata già registrata: altrimenti i suoi metri finirebbero nel conto due
volte.

## Perché non lo decide il programma

Per un giorno il criterio è stato: se quel giorno l'orologio ha registrato una
nuotata, la gara non conta. L'atleta l'ha smontato il 25/08/2026 con un esempio
che nessuna regola sul giorno può salvare — la gara era a place04 la mattina,
l'allenamento a place03 alle [orario], cento chilometri più in là.

E il criterio sul giorno sbagliava anche al contrario: il 19/05/2018 ci sono due
gare e una sola nuotata registrata, il 18/05/2019 tre gare e una sola. Una
nuotata può essere al massimo **una** gara; le altre restano nuotate a sé.

Luogo, ora e durata li guarda una persona. Questo modulo si limita a portare
quella decisione dentro il database, e a non applicarne nessuna che non capisce.

## Il gemello

``corrections.py`` fa la stessa cosa per le **attività** dell'orologio, leggendo
``coach/correzioni-dati.md``. I due file sono separati perché le due entità
hanno chiavi diverse — ``activity_id`` e ``race_id`` — e problemi diversi: di
un'attività si corregge una misura sbagliata, di una gara si stabilisce se è già
stata contata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import duckdb

from . import paths

FILE = "correzioni-gare.md"

# I tre verdetti che il progetto sa applicare. Sono gli stessi che l'atleta
# legge in cima al proprio file.
LINKED = "linked"        # la gara È quella nuotata: già contata una volta
SEPARATE = "separate"    # una nuotata a sé, anche se quel giorno ce n'era altra
EXCLUDE = "exclude"      # fuori dal volume e dai confronti

KNOWN = {LINKED, SEPARATE, EXCLUDE}

# Una distanza che l'atleta sa sbagliata ma di cui non conosce il valore vero.
# Non è un numero e non deve diventarlo: senza questa parola l'unico modo di
# correggere sarebbe inventarlo (R5).
UNKNOWN_DISTANCE = {"sconosciuta", "sconosciuto", "non nota", "ignota"}


class UnknownDecision(ValueError):
    """Un verdetto che il progetto non sa applicare.

    Non si può ignorare: una riga scritta per togliere una gara dal volume, se
    non viene capita, lascia quella gara dentro le medie — e l'atleta crede di
    averla tolta.
    """


@dataclass(frozen=True)
class RaceCorrection:
    race_id: str
    verdict: str
    activity_id: int | None
    counted_distance_m: float | None
    distance_is_unknown: bool
    reason: str
    confirmed_on: date | None

    @property
    def excludes(self) -> bool:
        return self.verdict == EXCLUDE

    @property
    def is_linked(self) -> bool:
        return self.verdict == LINKED


def parse_counted_distance(text: str) -> tuple[float | None, bool]:
    """«1900» → 1900. «1,9 km» → 1900. «sconosciuta» → mancante.

    Restituisce la distanza e se è dichiarata sconosciuta: sono due cose
    diverse, e comprimerle in un ``None`` solo perderebbe la differenza fra
    «non ho corretto niente» e «so che il numero in archivio è sbagliato».

    Un valore che non si legge non diventa ``None`` in silenzio: sarebbe come
    non averlo scritto, e chi l'ha scritto crederebbe di aver corretto.
    """
    pulito = (text or "").strip().lower().replace(",", ".")
    if not pulito or pulito in {"-", "—"}:
        return None, False
    if pulito in UNKNOWN_DISTANCE:
        return None, True

    chilometri = re.fullmatch(r"(\d+(?:\.\d+)?)\s*km", pulito)
    if chilometri:
        return float(chilometri.group(1)) * 1000, False

    metri = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m?", pulito)
    if metri:
        return float(metri.group(1)), False

    raise UnknownDecision(
        f"In coach/{FILE} la distanza corretta «{text.strip()}» non si legge. "
        "Si scrive come «1900», «1,9 km», oppure «sconosciuta». Il file non "
        "viene interpretato a metà: una correzione non capita lascerebbe nei "
        "conti il numero che credi di aver sostituito.")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _clean(text: str) -> str:
    """Toglie il markup che serve a leggere e non a decidere."""
    return text.strip().strip("`").strip()


def _iso(text: str) -> date | None:
    trovato = re.search(r"\d{4}-\d{2}-\d{2}", text or "")
    return date.fromisoformat(trovato.group()) if trovato else None


def declared() -> list[RaceCorrection]:
    """Le decisioni scritte nel file dell'atleta.

    Lista vuota se il file non c'è: un progetto senza correzioni sulle gare è lo
    stato normale, non un errore.
    """
    percorso = paths.COACH / FILE
    if not percorso.exists():
        return []

    trovate: list[RaceCorrection] = []
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        if not riga.strip().startswith("|"):
            continue
        celle = _cells(riga)
        if len(celle) < 6:
            continue
        race_id = _clean(celle[0])
        # Le altre tabelle del file — l'intestazione, le distanze da recuperare
        # — non hanno un race id nella prima colonna e si riconoscono da qui.
        if not race_id.startswith(("icron-", "aquatime-", "declared-")):
            continue

        verdetto = _clean(celle[1])
        if verdetto not in KNOWN:
            raise UnknownDecision(
                f"In coach/{FILE} la gara {race_id} ha stato «{verdetto}», che "
                "questo progetto non sa applicare. Quelli previsti sono: "
                f"{', '.join(sorted(KNOWN))}. Il file non viene interpretato a "
                "metà: una decisione non capita lascerebbe nei conti una gara "
                "che credi di aver tolto.")

        seduta = _clean(celle[3])
        activity_id = int(seduta) if seduta.isdigit() else None
        if verdetto == LINKED and activity_id is None:
            raise UnknownDecision(
                f"In coach/{FILE} la gara {race_id} è dichiarata «{LINKED}» ma "
                "non dice a quale seduta. Un collegamento senza la seduta non "
                "toglie il doppio conteggio: dice solo che qualcuno ci ha "
                "pensato. Scrivi l'identificativo nella colonna «Seduta "
                "Garmin», o usa «separate».")

        distanza, sconosciuta = parse_counted_distance(celle[4])
        trovate.append(RaceCorrection(
            race_id=race_id,
            verdict=verdetto,
            activity_id=activity_id,
            counted_distance_m=distanza,
            distance_is_unknown=sconosciuta,
            reason=_clean(celle[5]),
            confirmed_on=_iso(celle[6]) if len(celle) > 6 else None))
    return trovate


def apply(connection: duckdb.DuckDBPyConnection) -> dict:
    """Porta le decisioni dell'atleta dentro ``race_quality``.

    Idempotente e completa: la tabella viene rifatta dal file, così togliere una
    riga dal markdown toglie davvero la correzione. Le decisioni su gare non
    ancora importate restano scritte lo stesso — se l'import le porta domani, la
    correzione è già in attesa invece di arrivare dopo che quei metri sono già
    passati dentro una media.
    """
    decisioni = declared()
    adesso = datetime.now()

    connection.execute("DELETE FROM race_quality WHERE decided_by = 'athlete'")
    for una in decisioni:
        connection.execute(
            "INSERT OR REPLACE INTO race_quality (race_id, verdict, "
            " activity_id, counted_distance_m, distance_is_unknown, reason, "
            " confirmed_on, decided_by, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'athlete', ?)",
            [una.race_id, una.verdict, una.activity_id, una.counted_distance_m,
             una.distance_is_unknown, una.reason, una.confirmed_on, adesso])

    return {
        "decisioni": len(decisioni),
        "collegate": sum(1 for una in decisioni if una.is_linked),
        "escluse": sum(1 for una in decisioni if una.excludes),
        "distanze_corrette": sum(1 for una in decisioni
                                 if una.counted_distance_m is not None),
    }


def unexamined(connection: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Le gare in mare che condividono il giorno con una nuotata, senza verdetto.

    Sono i casi in cui il programma **non può sapere** se la gara è già stata
    contata: c'è una nuotata quel giorno, ma nessuno ha guardato se è quella
    gara o un'altra cosa. Il criterio C19 pretende che siano zero, così un caso
    nuovo emerge invece di essere indovinato in silenzio.
    """
    return connection.execute("""
        SELECT r.race_id, r.race_date, r.meet, r.venue
        FROM races r
        LEFT JOIN race_quality q ON q.race_id = r.race_id
        WHERE r.environment = 'acque libere'
          AND r.activity_id IS NULL
          AND q.race_id IS NULL
          AND EXISTS (SELECT 1 FROM canonical_activities a
                      WHERE a.is_swim AND a.activity_date = r.race_date)
        ORDER BY r.race_date
    """).fetchall()
