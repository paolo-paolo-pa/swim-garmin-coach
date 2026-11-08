"""I dati che non reggono, e la decisione che aspettano.

## La domanda a cui risponde

*«Quali numeri, fra i miei, non descrivono quello che ho fatto — e cosa devo
decidere perché il coach smetta di dire "confidenza bassa"?»*

## Perché serviva una superficie e non bastava una segnalazione

`corrections.flag_automatically` marca `review` da ieri, e funziona: tre
attività su 1.345. Ma la segnalazione compariva **solo** durante un import, in
tre righe di terminale, e diceva l'identificativo e nient'altro. Per decidere,
l'atleta doveva aprire un file markdown, capire una tabella a sei colonne e
ricopiare a mano undici cifre — e soprattutto doveva sapere *perché* quel
numero è impossibile, che è l'unica cosa che il terminale non gli diceva.

Il risultato misurato: tre attività ferme in `review`, la homepage che dichiara
«confidenza bassa» da un giorno, e nessun posto in cui rispondere.

## Che cosa questo modulo aggiunge, e cosa no

**Non aggiunge un rilevatore.** I flag restano quelli di `corrections.py`, con
le loro soglie fisiche. Qui non si segnala niente di nuovo: si spiega ciò che è
già segnalato.

Quello che aggiunge è il **confronto con l'atleta stesso**. «18,2 s/100 m» non
dice niente a nessuno; «18,2 contro un tuo intervallo fra 69 e 190 su
101 nuotate in acque libere» è una prova. Il confronto usa la popolazione
dell'atleta nello stesso ambiente, esclusi i dubbi stessi — altrimenti il caso
anomalo allargherebbe la fascia che serve a smascherarlo.

**Non propone una risposta.** Non dice «probabilmente erano 70 m»: quella
sarebbe la seconda invenzione che il progetto ha già deciso di non fare per
place20. Mostra i numeri vicini e lascia la frase all'atleta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb

from ..database import table_exists

# Sotto questa distanza il passo non è una prova di niente: pochi secondi di
# errore lo spostano di minuti. È la stessa soglia con cui `corrections.py`
# decide se guardare il passo, e sta scritta una volta sola.
MIN_DISTANCE_FOR_COMPARISON_M = 200


@dataclass(frozen=True)
class Comparison:
    """Un numero di questa attività, messo accanto a quelli dell'atleta."""

    what: str
    here: str
    typical: str
    range: str
    population: str


@dataclass(frozen=True)
class Doubt:
    """Un'attività su cui l'atleta deve dire una parola."""

    activity_id: int
    day: date
    title: str
    environment: str
    status: str
    decided_by: str
    flag: str
    recorded: list[tuple[str, str]] = field(default_factory=list)
    against: list[Comparison] = field(default_factory=list)
    same_day: list[str] = field(default_factory=list)
    weight: str = ""
    question: str = ""

    @property
    def decided(self) -> bool:
        return self.decided_by == "athlete"


def _pace(distance: float | None, duration: float | None) -> float | None:
    if not distance or not duration or distance <= 0:
        return None
    return duration / distance * 100


def _show_pace(seconds: float | None) -> str:
    if seconds is None:
        return "non calcolabile"
    minuti, resto = divmod(seconds, 60)
    return f"{int(minuti)}:{resto:04.1f}/100 m"


def _show_metres(value: float | None) -> str:
    return "non disponibile" if value is None else f"{value:,.0f} m".replace(",", ".")


def _show_minutes(seconds: float | None) -> str:
    return "non disponibile" if seconds is None else f"{seconds / 60:.1f} min"


def _population(connection: duckdb.DuckDBPyConnection, environment: str,
                excluded: set[int]) -> dict:
    """Passo e metri per ciclo dell'atleta nello stesso ambiente.

    Le attività in dubbio escono dalla popolazione. Se restassero dentro,
    l'intervallo si allargherebbe fino a contenerle e il confronto direbbe che
    va tutto bene — che è precisamente il modo in cui un valore assurdo
    sopravvive a un controllo statistico.
    """
    fuori = ", ".join(str(int(uno)) for uno in excluded) or "0"
    riga = connection.execute(f"""
        SELECT count(*),
               median(100.0 * duration_s / distance_m),
               quantile_cont(100.0 * duration_s / distance_m, 0.02),
               quantile_cont(100.0 * duration_s / distance_m, 0.98),
               median(distance_m / nullif(total_strokes, 0)),
               min(distance_m / nullif(total_strokes, 0)),
               max(distance_m / nullif(total_strokes, 0))
        FROM activities
        WHERE is_swim AND environment = ?
          AND distance_m > {MIN_DISTANCE_FOR_COMPARISON_M} AND duration_s > 0
          AND activity_id NOT IN ({fuori})
    """, [environment]).fetchone()
    return {"n": riga[0], "pace_median": riga[1], "pace_low": riga[2],
            "pace_high": riga[3], "per_stroke_median": riga[4],
            "per_stroke_low": riga[5], "per_stroke_high": riga[6]}


def _comparisons(seduta: dict, popolazione: dict, ambiente: str) -> list[Comparison]:
    dove = "acque libere" if ambiente == "open_water" else "vasca"
    quanti = f"{popolazione['n']:,} tue nuotate in {dove}".replace(",", ".")
    confronti: list[Comparison] = []

    passo = _pace(seduta["distance_m"], seduta["duration_s"])
    if passo is not None and popolazione["pace_median"]:
        confronti.append(Comparison(
            what="passo medio",
            here=_show_pace(passo),
            typical=_show_pace(popolazione["pace_median"]),
            range=f"da {_show_pace(popolazione['pace_low'])} "
                  f"a {_show_pace(popolazione['pace_high'])}",
            population=quanti))

    bracciate = seduta.get("total_strokes")
    if bracciate and seduta["distance_m"] and popolazione["per_stroke_median"]:
        confronti.append(Comparison(
            what="metri per ciclo di bracciata",
            here=f"{seduta['distance_m'] / bracciate:.2f} m",
            typical=f"{popolazione['per_stroke_median']:.2f} m",
            range=f"da {popolazione['per_stroke_low']:.2f} "
                  f"a {popolazione['per_stroke_high']:.2f} m",
            population=quanti))
    return confronti


def _same_day(connection: duckdb.DuckDBPyConnection, seduta: dict) -> list[str]:
    """Che altro c'era quel giorno.

    Serve a rispondere alla domanda che viene per prima a chi guarda una data
    di cinque anni fa: «cosa stavo facendo?». Una nuotata vera lì accanto dice
    più di qualsiasi soglia.
    """
    righe = connection.execute("""
        SELECT distance_m, duration_s, name
        FROM activities
        WHERE activity_date = ? AND activity_id <> ? AND is_swim
        ORDER BY start_time_local
    """, [seduta["activity_date"], seduta["activity_id"]]).fetchall()
    return [f"{_show_metres(d)} in {_show_minutes(t)} "
            f"({_show_pace(_pace(d, t))}) — {n}" for d, t, n in righe]


def _weight(connection: duckdb.DuckDBPyConnection, seduta: dict) -> str:
    """Quanto pesa questa attività sull'anno in cui sta.

    È l'informazione che rende la decisione proporzionata: togliere 700 m da un
    anno da 200 km non è la stessa cosa che togliere 25 km, e l'atleta ha il
    diritto di saperlo prima di decidere invece di scoprirlo dopo.
    """
    anno = seduta["activity_date"].year
    totale = connection.execute("""
        SELECT sum(distance_m) FROM activities
        WHERE is_swim AND year(activity_date) = ?
    """, [anno]).fetchone()[0]
    if not totale or not seduta["distance_m"]:
        return f"Peso sul {anno} non calcolabile."
    quota = seduta["distance_m"] / totale
    return (f"Vale {_show_metres(seduta['distance_m'])} sui "
            f"{totale / 1000:,.1f} km nuotati nel {anno}".replace(",", ".")
            + f", cioè il {quota:.1%}.")


_QUESTIONS = {
    "passo non umano":
        "Questa distanza in questo tempo non è nuotabile: uno dei due numeri è "
        "sbagliato, e l'orologio non dice quale. Ti ricordi cos'era?",
    "distanza senza bracciate":
        "L'orologio in questa attività sapeva contare le bracciate — l'ha fatto "
        "in alcuni tratti — e per gran parte della distanza non ne ha contate. "
        "Era nuoto, o eri in movimento senza nuotare?",
}

_DEFAULT_QUESTION = ("Questo numero descrive quello che hai fatto quel giorno?")


def pending(connection: duckdb.DuckDBPyConnection) -> list[Doubt]:
    """Le attività in dubbio, dalla più recente, con le prove per decidere.

    Restituisce anche quelle già decise dall'atleta come ``keep``: una decisione
    presa deve restare visibile, altrimenti l'unico modo di sapere che è stata
    presa è non vedere più niente — e non vedere niente è anche ciò che succede
    quando un controllo si rompe.
    """
    if not table_exists(connection, "activity_quality"):
        return []

    righe = connection.execute("""
        SELECT q.activity_id, q.status, q.reason, q.decided_by,
               a.activity_date, a.name, a.environment, a.distance_m,
               a.duration_s, a.total_strokes, a.avg_swim_cadence_spm,
               a.lap_count, a.device_id
        FROM activity_quality q
        JOIN activities a USING (activity_id)
        WHERE q.status IN ('review', 'keep')
        ORDER BY a.activity_date DESC
    """).fetchall()
    if not righe:
        return []

    in_dubbio = {riga[0] for riga in righe}
    popolazioni: dict[str, dict] = {}
    trovati: list[Doubt] = []

    for (activity_id, stato, motivo, deciso_da, giorno, nome, ambiente,
         distanza, durata, bracciate, cadenza, lap, orologio) in righe:
        seduta = {"activity_id": activity_id, "activity_date": giorno,
                  "distance_m": distanza, "duration_s": durata,
                  "total_strokes": bracciate}
        if ambiente not in popolazioni:
            popolazioni[ambiente] = _population(connection, ambiente, in_dubbio)

        registrato = [
            ("distanza registrata", _show_metres(distanza)),
            ("durata registrata", _show_minutes(durata)),
            ("passo che ne risulta", _show_pace(_pace(distanza, durata))),
            ("cicli di bracciata contati",
             f"{bracciate:,.0f}".replace(",", ".") if bracciate else "nessuno"),
            ("cadenza media",
             f"{cadenza:.0f} cicli/min" if cadenza else "non registrata"),
            ("lap nel file", f"{lap:,.0f}".replace(",", ".") if lap else "nessuno"),
            ("orologio", str(orologio) if orologio else "non registrato"),
        ]

        segnale = next((chiave for chiave in _QUESTIONS if chiave in (motivo or "")),
                       None)
        trovati.append(Doubt(
            activity_id=activity_id,
            day=giorno,
            title=nome or "senza nome",
            environment=ambiente,
            status=stato,
            decided_by=deciso_da,
            flag=motivo or "",
            recorded=registrato,
            against=_comparisons(seduta, popolazioni[ambiente], ambiente),
            same_day=_same_day(connection, seduta),
            weight=_weight(connection, seduta),
            question=_QUESTIONS.get(segnale, _DEFAULT_QUESTION)))
    return trovati


def disagreements(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    """Le sedute in cui il riepilogo Garmin e il file dell'orologio litigano.

    Sono un dubbio diverso e non vanno mescolate: qui nessuno dei due numeri è
    impossibile, sono solo due, e il progetto non sa quale sia giusto. La
    decisione dell'atleta non è «era vero?» ma «quale dei due era vero?», e
    finché non arriva la pagina della seduta lo dichiara invece di scegliere.
    """
    if not table_exists(connection, "activity_source_matches"):
        return []
    righe = connection.execute("""
        SELECT m.activity_id, a.activity_date, a.name, a.distance_m,
               m.distance_gap_m, m.reason, q.status, q.reason
        FROM activity_source_matches m
        JOIN activities a USING (activity_id)
        LEFT JOIN activity_quality q USING (activity_id)
        WHERE m.verdict = 'discordant'
        ORDER BY a.activity_date DESC
    """).fetchall()
    return [{"activity_id": activity_id, "day": giorno, "title": nome,
             "summary": _show_metres(distanza),
             "file": _show_metres((distanza or 0) + (scarto or 0)),
             "reason": motivo,
             # Una volta che l'atleta ha risposto, la pagina smette di fare la
             # domanda. Continuare a chiederlo è il modo in cui un sistema
             # insegna che rispondergli non serve a niente — e la decisione
             # resta visibile, perché una decisione che sparisce non si può
             # rimettere in discussione.
             "decided": (stato or "") in ("correct", "keep"),
             "decision": perche or ""}
            for (activity_id, giorno, nome, distanza, scarto, motivo,
                 stato, perche) in righe]
