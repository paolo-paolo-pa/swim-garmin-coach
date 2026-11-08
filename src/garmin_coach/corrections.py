"""Le correzioni che l'atleta ha confermato, lette dove l'atleta le scrive.

## La domanda a cui risponde

*«Questo numero descrive davvero quello che ho fatto?»*

Garmin registra fatti su un orologio, non allenamenti. Un'attività può essere
formalmente impeccabile — riepilogo dell'export e file FIT in accordo numerico
esatto — e descrivere un traghetto, una registrazione rimasta accesa, o una
giornata in cui si è nuotato un pezzo e per il resto si è stati trasportati.

Fino a ieri il progetto trattava l'accordo fra JSON e FIT come prova di verità.
Non lo è: prova che due file dicono la stessa cosa.

## Come funziona

La decisione sta in `coach/correzioni-dati.md`, in una tabella markdown che
l'atleta legge e modifica. Non sta nel database perché il database si ricostruisce
da zero e una decisione umana scritta lì dentro sparirebbe alla prima
ricostruzione (Regola Aurea n.3). Non sta nel codice perché un identificativo in
una funzione è una decisione travestita da costante: sopravvive a chi l'ha presa,
non porta con sé il motivo, e la seconda esclusione si fa copiando la prima.

Da qui entra in `activity_quality`, che è derivata, e da lì nella vista
`canonical_activities`, che è ciò che ogni analisi interroga.

## Quello che questo modulo non fa

Non inventa un valore corretto. Per place20 i lap suggerirebbero 4-5 km, ed è
esattamente il genere di stima che sembra prudente e non lo è: sarebbe una
seconda invenzione al posto della prima, con l'aggravante di sembrare misurata.
Un'attività esclusa esce dai conti; se un giorno l'atleta confermerà una
distanza vera, quella sarà `correct` e porterà il proprio numero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import duckdb

from . import paths

FILE = "correzioni-dati.md"

# I quattro stati che il progetto sa applicare, e cosa significano per le
# analisi. Sono gli stessi che l'atleta legge in cima al proprio file.
EXCLUDE = "exclude"      # fuori da ogni metrica e conclusione
CORRECT = "correct"      # valgono solo i valori confermati nella nota
KEEP = "keep"            # anomalia guardata e dichiarata valida
REVIEW = "review"        # non regge conclusioni forti finché non è verificata

KNOWN = {EXCLUDE, CORRECT, KEEP, REVIEW}


class UnknownDecision(ValueError):
    """Uno stato che il progetto non sa applicare.

    Non si può ignorare: una riga che l'atleta ha scritto per escludere
    un'attività, se non viene capita, lascia quell'attività dentro le medie —
    e l'atleta crede di averla tolta.
    """


@dataclass(frozen=True)
class Correction:
    activity_id: int
    status: str
    scope: str
    reason: str
    confirmed_on: date | None
    corrected_distance_m: float | None = None

    @property
    def excludes(self) -> bool:
        return self.status == EXCLUDE


def parse_corrected_distance(text: str) -> float | None:
    """«14 km» → 14000, «6000» → 6000. Una casella vuota resta vuota.

    Il valore corretto è un **numero in una colonna** e non una frase nella
    nota. Fino al 24/08/2026 viveva nella nota, e l'audit lo aveva già
    scritto come limite: nessuna query poteva usarlo, e `canonical_activities`
    continuava a restituire il numero sbagliato mentre il file dell'atleta
    diceva quello giusto.

    Un valore che non si legge non diventa `None` in silenzio: sarebbe come
    non averlo scritto, e chi l'ha scritto crederebbe di aver corretto.
    """
    pulito = (text or "").strip().lower().replace(",", ".")
    if not pulito or pulito in {"-", "—"}:
        return None

    chilometri = re.fullmatch(r"(\d+(?:\.\d+)?)\s*km", pulito)
    if chilometri:
        return float(chilometri.group(1)) * 1000

    metri = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m?", pulito)
    if metri:
        return float(metri.group(1))

    raise UnknownDecision(
        f"In coach/{FILE} la distanza corretta «{text.strip()}» non si legge. "
        "Si scrive come «14 km» oppure «14000». Il file non viene "
        "interpretato a metà: una correzione non capita lascerebbe dentro i "
        "conti il numero che credi di aver sostituito.")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _clean(text: str) -> str:
    """Toglie il markup che serve a leggere e non a decidere."""
    return text.strip().strip("`").strip()


def declared() -> list[Correction]:
    """Le decisioni scritte nel file dell'atleta.

    Restituisce una lista vuota se il file non c'è: un progetto senza correzioni
    è lo stato normale, non un errore.
    """
    percorso = paths.COACH / FILE
    if not percorso.exists():
        return []

    trovate: list[Correction] = []
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        if not riga.strip().startswith("|"):
            continue
        celle = _cells(riga)
        if len(celle) < 5:
            continue
        identificativo = _clean(celle[0])
        if not identificativo.isdigit():
            continue      # intestazione, separatore, o riga di esempio

        stato = _clean(celle[1])
        if stato not in KNOWN:
            raise UnknownDecision(
                f"In coach/{FILE} l'attività {identificativo} ha stato "
                f"«{stato}», che questo progetto non sa applicare. "
                f"Quelli previsti sono: {', '.join(sorted(KNOWN))}. "
                "Il file non viene interpretato a metà: una decisione non "
                "capita lascerebbe dentro i conti un'attività che credi di "
                "aver tolto.")

        trovate.append(Correction(
            activity_id=int(identificativo),
            status=stato,
            scope=_clean(celle[3]) if len(celle) > 3 else "",
            reason=_clean(celle[4]) if len(celle) > 4 else "",
            confirmed_on=_iso(celle[5]) if len(celle) > 5 else None,
            corrected_distance_m=parse_corrected_distance(celle[6])
            if len(celle) > 6 else None))
    return trovate


def _iso(text: str) -> date | None:
    trovato = re.search(r"\d{4}-\d{2}-\d{2}", text or "")
    return date.fromisoformat(trovato.group()) if trovato else None


def apply(connection: duckdb.DuckDBPyConnection) -> dict:
    """Porta le decisioni dell'atleta dentro ``activity_quality``.

    Idempotente e completa: la tabella viene rifatta dal file, così togliere una
    riga dal markdown toglie davvero la correzione. Le decisioni su attività non
    ancora importate restano scritte lo stesso — se il sync le porta domani, la
    correzione è già in attesa invece di arrivare una notte dopo, quando quei
    numeri sono già passati dentro una media.
    """
    decisioni = declared()
    adesso = datetime.now()

    connection.execute("DELETE FROM activity_quality WHERE decided_by = 'athlete'")
    for una in decisioni:
        connection.execute(
            "INSERT OR REPLACE INTO activity_quality (activity_id, status, "
            " scope, reason, confirmed_on, decided_by, applied_at, "
            " corrected_distance_m) "
            "VALUES (?, ?, ?, ?, ?, 'athlete', ?, ?)",
            [una.activity_id, una.status, una.scope, una.reason,
             una.confirmed_on, adesso, una.corrected_distance_m])

    escluse = sum(1 for una in decisioni if una.excludes)
    return {"decisioni": len(decisioni), "escluse": escluse,
            "distanze_corrette": sum(1 for una in decisioni
                                     if una.corrected_distance_m is not None)}


def about(connection: duckdb.DuckDBPyConnection,
          activity_id: int) -> Correction | None:
    """La decisione su una singola attività, se esiste.

    Serve alle pagine: un'attività esclusa non deve **sparire**, deve poter
    essere aperta e dire perché non conta. Una correzione che assomiglia a un
    buco nei dati verrà scambiata per un difetto e prima o poi rimossa.
    """
    riga = connection.execute(
        "SELECT activity_id, status, scope, reason, confirmed_on, "
        " corrected_distance_m "
        "FROM activity_quality WHERE activity_id = ?", [activity_id]).fetchone()
    return Correction(*riga) if riga else None


# ── Segnalazione automatica: classifica, non decide ──────────────────────
#
# I limiti sono fisici, non statistici. Una soglia statistica su un archivio
# personale segnala l'atleta quando migliora; una soglia fisica segnala soltanto
# ciò che un essere umano non fa.
#
# Nessuno di questi numeri esclude niente. Producono `review`, che significa
# «non regge una conclusione forte finché non l'hai guardata»: la differenza fra
# aiutare l'atleta a trovare un dato sbagliato e decidere al posto suo.

# Il record mondiale sui 50 m stile è 20,91 s, cioè 41,8 s/100 m, tenuti per
# venti secondi. Sotto i 40 s/100 m su una distanza vera non c'è nuoto.
MIN_HUMAN_PACE_S_PER_100M = 40.0

# Distanza minima perché il passo significhi qualcosa: sotto, un errore di
# qualche secondo sposta il rapporto senza che niente sia anomalo.
MIN_DISTANCE_FOR_PACE_M = 200

AUTOMATIC_CHECKS = (
    ("passo non umano",
     f"duration_s / distance_m * 100 < {MIN_HUMAN_PACE_S_PER_100M} "
     f"AND distance_m > {MIN_DISTANCE_FOR_PACE_M} AND duration_s > 0",
     "il passo risultante è più veloce del record mondiale sui 50 m"),
)

# ── Il controllo che manca, e perché non c'è ─────────────────────────────
#
# Il segno che ha smascherato place20 è «movimento senza bracciate». Due
# tentativi di rilevarlo dai soli campi di riepilogo sono stati misurati
# sull'archivio vero e scartati entrambi, invece di essere spediti.
#
# **Metri per bracciata.** Sembrava che oltre 3,5 m per bracciata non ci fosse
# nuoto. Misurato: la mediana di questo atleta è 2,87 e il novantesimo
# percentile 3,25, quindi la soglia segnalava 46 sedute su 1.286 — il 3,6%, per
# lo più sedute in vasca con cadenza normale, cioè probabilmente vasche a gambe.
# La soglia era tarata su un'assunzione sbagliata: `total_strokes` conta cicli
# di bracciata, non bracciate singole, e con l'unità sbagliata il ragionamento
# fisico dava il numero sbagliato.
#
# **Bracciate contro cadenza per durata.** Doveva essere immune all'unità,
# perché i due campi la condividono. Non lo è: `duration_s` include i riposi,
# quindi cadenza × durata sovrastima sistematicamente, e le peggiori segnalate
# erano sedute da 125-250 m con l'orologio lasciato acceso — un fatto normale,
# non un dato sbagliato.
#
# Il rilevatore giusto guarda i **lap**, non il riepilogo: place20 si riconosce
# perché ha lap lunghi in movimento con cadenza zero alternati a pochi tratti
# con cadenza da nuoto, e quello si vede solo in `activity_laps`. Resta da fare,
# ed è dichiarato OPEN nell'audit invece che risolto a metà: un rilevatore che
# segnala 46 sedute buone insegna a ignorare le segnalazioni, ed è peggio di
# non averlo.


# ── Distanza percorsa senza bracciate, riconosciuta dai lap ──────────────
#
# È il controllo che l'audit aveva lasciato OPEN, e ci sono voluti tre tentativi.
# I primi due guardavano il riepilogo e sono stati scartati dopo averli misurati:
# i metri per bracciata sbagliavano l'unità, e le bracciate contro cadenza ×
# durata erano confuse dai riposi dentro `duration_s`.
#
# La firma di place20 si vede solo lap per lap: cinque lap con cadenza fra 21 e
# 28 — l'orologio **stava misurando** — e ventitré che coprono 800-1500 m
# ciascuno con cadenza 0, 1, 2.
#
# ## Il terzo tentativo, e perché è stato scartato anche lui
#
# «Quota di distanza in lap senza cadenza» segnalava al 98-100% le quattro
# attività peggiori, e fra queste c'era **place07 2019, 5.800 m a 1:26,0** —
# uno dei migliori risultati veri dell'atleta, citato in `coach/gare.md`.
# In acque libere molti orologi non registrano affatto la cadenza: zero su
# tutta l'attività significa «non misurata», non «non nuotata».
#
# ## Il discriminante che funziona
#
# L'**alternanza**. L'orologio ha dimostrato di saper misurare in quella stessa
# attività, e ciononostante gran parte della distanza è passata senza bracciate.
# Restringendo alle attività con almeno un lap a cadenza piena, place20 diventa
# il massimo assoluto — 0,79 — e place07 esce da sola.

# Sotto questa cadenza un lap non contiene nuoto. Non è una soglia statistica:
# la mediana di questo atleta è 25 bracciate al minuto.
SILENT_LAP_CADENCE = 5.0

# Un lap più corto di così può essere una vasca a gambe, che ha cadenza zero ed
# è allenamento vero. La firma che si cerca è fatta di tratti lunghi.
SILENT_LAP_MIN_METRES = 300.0

# Sopra questa cadenza il lap prova che l'orologio stava misurando.
MEASURING_LAP_CADENCE = 15.0

# Quota di distanza «muta» oltre la quale l'attività va guardata. Misurata su
# 1.187 attività in cui l'orologio misurava: due la superano — place20 a 0,79 e
# il 16/07/2019, che è 2.500 m con 148 bracciate in totale, cioè un'altra
# anomalia vera. È una scelta, e va guardata dall'auditor.
SILENT_DISTANCE_SHARE = 0.35


def _silent_distance(connection: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Le attività in cui l'orologio misurava e la distanza è passata muta."""
    from .database import table_exists

    if not table_exists(connection, "activity_laps"):
        return []
    return connection.execute(f"""
        WITH per_attivita AS (
            SELECT activity_id,
                   sum(distance_m)                                   AS totale,
                   sum(distance_m) FILTER (
                       WHERE coalesce(avg_cadence_spm, 0) <= {SILENT_LAP_CADENCE}
                         AND distance_m >= {SILENT_LAP_MIN_METRES})  AS muta,
                   count(*) FILTER (
                       WHERE coalesce(avg_cadence_spm, 0)
                             >= {MEASURING_LAP_CADENCE})             AS lap_misurati
            FROM activity_laps
            WHERE NOT coalesce(is_rest, FALSE)
            GROUP BY activity_id
        )
        SELECT p.activity_id, a.activity_date, p.muta / p.totale
        FROM per_attivita p
        JOIN activities a USING (activity_id)
        WHERE p.totale > 0 AND p.muta IS NOT NULL
          AND p.lap_misurati >= 1
          AND p.muta / p.totale > {SILENT_DISTANCE_SHARE}
        ORDER BY a.activity_date
    """).fetchall()


def flag_automatically(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    """Segna come ``review`` le attività che superano un limite fisico.

    La decisione dell'atleta vince sempre: se una riga porta già la sua firma,
    questa funzione non la tocca. È il senso dell'overlay — la macchina propone
    dove guardare, la persona decide cosa è successo.
    """
    adesso = datetime.now()
    connection.execute(
        "DELETE FROM activity_quality WHERE decided_by = 'automatic'")

    segnalate: list[dict] = []
    for nome, condizione, perche in AUTOMATIC_CHECKS:
        righe = connection.execute(f"""
            SELECT activity_id, activity_date FROM activities a
            WHERE is_swim AND ({condizione})
              AND NOT EXISTS (SELECT 1 FROM activity_quality q
                              WHERE q.activity_id = a.activity_id)
            ORDER BY activity_date
        """).fetchall()
        for activity_id, giorno in righe:
            connection.execute(
                "INSERT OR REPLACE INTO activity_quality (activity_id, status, "
                " scope, reason, confirmed_on, decided_by, applied_at) "
                "VALUES (?, ?, ?, ?, NULL, 'automatic', ?)",
                [activity_id, REVIEW, "conclusioni forti",
                 f"{nome}: {perche}. Da guardare e decidere.", adesso])
            segnalate.append({"activity_id": activity_id, "day": giorno,
                              "check": nome})

    # Il controllo sui lap sta a parte perché non è una condizione su una riga
    # di `activities`: ha bisogno di aggregare i lap e di sapere se l'orologio
    # stava misurando. Incastrarlo nella tabella sopra avrebbe reso quella
    # tabella una cosa che non è.
    gia_deciso = {riga[0] for riga in connection.execute(
        "SELECT activity_id FROM activity_quality "
        "WHERE decided_by = 'athlete'").fetchall()}
    for activity_id, giorno, quota in _silent_distance(connection):
        if activity_id in gia_deciso:
            continue
        connection.execute(
            "INSERT OR REPLACE INTO activity_quality (activity_id, status, "
            " scope, reason, confirmed_on, decided_by, applied_at) "
            "VALUES (?, ?, ?, ?, NULL, 'automatic', ?)",
            [activity_id, REVIEW, "conclusioni forti",
             f"distanza senza bracciate: il {quota:.0%} dei metri è passato in "
             "lap lunghi con cadenza quasi nulla, mentre in altri lap della "
             "stessa attività l'orologio misurava una cadenza da nuoto. "
             "Da guardare e decidere.", adesso])
        segnalate.append({"activity_id": activity_id, "day": giorno,
                          "check": "distanza senza bracciate"})
    return segnalate
