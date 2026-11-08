"""Una fetta verticale della catena, da controllare a occhio (D8).

## A che serve

Le altre fasi dimostrano che i pezzi funzionano. Questa dimostra che
funzionano **insieme**, su casi reali e diversi fra loro:

```text
FIT → sorgente → verdetto di aggancio → lap e vasche → qualità → session()
```

Il cancello di D8 non è un test verde: è un umano che guarda un campione e
dice se le risposte hanno senso. Per questo l'uscita è un testo da leggere,
non un `assert`.

## Perché stratificato

Un campione preso a caso sarebbe fatto quasi solo di stile libero in vasca da
25 con il Fenix 8, perché è quello che l'atleta fa di più. Le cose si rompono
ai bordi: il mare, la vasca da 50, i dispositivi vecchi, gli esercizi tecnici,
i dati mancanti. Il campione va a cercarli uno per uno, e **dice quando uno
strato non esiste** invece di tacere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

# Ogni strato è una cosa che potrebbe rompersi in modo diverso dalle altre.
# La condizione è SQL su `activities` più, dove serve, sui lap.
STRATA: list[tuple[str, str, str]] = [
    ("vasca 25 m",
     "a.environment = 'pool' AND a.pool_length_m = 25",
     "il caso normale: se si rompe qui si rompe tutto"),
    ("vasca 50 m",
     "a.environment = 'pool' AND a.pool_length_m = 50",
     "stessa vasca ma passo e SWOLF non confrontabili con la 25"),
    ("acque libere",
     "a.environment = 'open_water'",
     "niente vasche: il concetto non si applica, non manca"),
    ("con esercizi tecnici",
     "EXISTS (SELECT 1 FROM activity_laps l "
     "WHERE l.activity_id = a.activity_id AND l.stroke = 'drill')",
     "i drill non vanno sommati allo stile che imitano"),
    ("con stili misti",
     "EXISTS (SELECT 1 FROM activity_laps l "
     "WHERE l.activity_id = a.activity_id AND l.stroke = 'mixed')",
     "un lap misto non ha un passo confrontabile con uno a stile"),
    ("con recuperi registrati",
     "EXISTS (SELECT 1 FROM activity_laps l "
     "WHERE l.activity_id = a.activity_id AND l.is_rest)",
     "il recupero è una riga, non una ripetuta mancata"),
    ("senza frequenza cardiaca",
     "a.is_swim AND a.avg_hr_bpm IS NULL AND a.activity_date < DATE '2021-01-01'",
     "prima del 2021 l'intensità non esiste: è un limite atteso, non un difetto"),
    ("dispositivo più vecchio",
     "a.device_id = (SELECT device_id FROM canonical_activities WHERE is_swim "
     "AND device_id IS NOT NULL ORDER BY start_time_utc LIMIT 1)",
     "SWOLF e distanza per bracciata non si confrontano fra dispositivi"),
    ("dispositivo attuale",
     "a.device_id = (SELECT device_id FROM canonical_activities WHERE is_swim "
     "AND device_id IS NOT NULL ORDER BY start_time_utc DESC LIMIT 1)",
     "il termine di paragone di oggi"),
    ("aggancio ambiguo",
     "EXISTS (SELECT 1 FROM activity_source_matches m "
     "WHERE m.activity_id = a.activity_id AND m.verdict = 'ambiguous')",
     "deve restare senza dettaglio, e dire perché"),
    ("senza file FIT",
     "EXISTS (SELECT 1 FROM activity_source_matches m "
     "WHERE m.activity_id = a.activity_id AND m.verdict = 'unmatched')",
     "arrivata col sync dopo l'export: i totali ci sono, il dettaglio no"),
]


@dataclass
class SliceCase:
    stratum: str
    why: str
    activity_id: int | None = None
    day: object = None
    findings: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.activity_id is None


def _pick(connection: duckdb.DuckDBPyConnection, condition: str) -> tuple | None:
    """La seduta più recente che soddisfa lo strato.

    La più recente e non una a caso: se qualcosa si è rotto di recente, è lì
    che si vede per primo.
    """
    return connection.execute(f"""
        SELECT a.activity_id, a.activity_date FROM canonical_activities a
        WHERE a.is_swim AND ({condition})
        ORDER BY a.start_time_utc DESC LIMIT 1
    """).fetchone()


def _inspect(connection: duckdb.DuckDBPyConnection, case: SliceCase) -> None:
    """Attraversa la catena su una seduta e annota cosa si vede e cosa non torna."""
    from .mcp import queries

    answer = queries.session(connection, case.activity_id)
    detail = answer["session"]
    level = answer["detail_level"]

    # Una seduta senza distanza esiste davvero — il campione va a cercare
    # apposta i casi con dati mancanti, e questo rapporto non deve rompersi
    # proprio sul caso che è stato costruito per esaminare.
    distanza = (f"{detail['distance_m']:,.0f} m" if detail["distance_m"] is not None
                else "distanza mancante")
    durata = (f"{detail['duration_s'] / 60:.0f} min" if detail["duration_s"]
              else "durata mancante")
    case.findings.append(
        f"{distanza} in {durata} — {detail['environment'] or 'ambiente ignoto'}"
        + (f", vasca {detail['pool_length_m']:.0f} m" if detail.get("pool_length_m") else ""))
    case.findings.append(f"dettaglio: {level}")

    if level == "laps":
        laps = answer["laps"]
        swum = [lap for lap in laps if not lap["is_rest"]]
        rests = [lap for lap in laps if lap["is_rest"]]
        case.findings.append(f"{len(swum)} lap nuotati, {len(rests)} recuperi")
        if answer.get("by_stroke"):
            case.findings.append("stili: " + ", ".join(
                f"{s['stroke']} {s['distance_m'] or 0:,.0f} m"
                for s in answer["by_stroke"]))
        if answer.get("detail_incomplete"):
            case.findings.append("dichiarato incompleto: sì")

        # I controlli che devono valere sempre, qualunque sia lo strato.
        if detail["environment"] == "open_water":
            if any(lap.get("active_lengths") for lap in laps):
                case.problems.append("vasche in acque libere: non devono esistere")
            if not swum:
                case.problems.append("tutti i lap marcati come recupero in mare")
        if any(lap["is_rest"] and lap["stroke"] for lap in laps):
            case.problems.append("un recupero porta uno stile")
        if any((lap["distance_m"] or 0) < 0 for lap in laps):
            case.problems.append("distanza negativa")
    else:
        motivo = answer.get("detail_unavailable", "")
        case.findings.append("motivo: " + motivo.split(".")[0])
        if not motivo:
            case.problems.append("nessun dettaglio e nessuna spiegazione")

    # La provenienza deve arrivare fino in fondo: è tutto il senso di D2.
    if level == "laps":
        # Lo schema impedisce già una sorgente nulla. Quello che può ancora
        # succedere è peggio e non si vede: un riferimento a una sorgente che
        # non esiste nel catalogo, cioè una provenienza che sembra esserci.
        traced = connection.execute("""
            SELECT count(*) FILTER (
                       WHERE source_object_id IS NULL
                          OR NOT EXISTS (SELECT 1 FROM source_objects s
                                         WHERE s.source_object_id = l.source_object_id)),
                   count(*)
            FROM activity_laps l WHERE activity_id = ?""",
            [case.activity_id]).fetchone()
        if traced[0]:
            case.problems.append(
                f"{traced[0]} lap su {traced[1]} citano una sorgente che non esiste")
        else:
            case.findings.append(f"provenienza: tutti i {traced[1]} lap risalgono al file")


def run(connection: duckdb.DuckDBPyConnection) -> list[SliceCase]:
    cases = []
    for stratum, condition, why in STRATA:
        case = SliceCase(stratum, why)
        found = _pick(connection, condition)
        if found:
            case.activity_id, case.day = found
            _inspect(connection, case)
        cases.append(case)
    return cases


def render(cases: list[SliceCase]) -> str:
    lines = [
        "FETTA VERTICALE — un caso per ogni cosa che può rompersi",
        "",
        "  Da leggere, non da far girare: il cancello D8 è un umano che guarda",
        "  e dice se le risposte hanno senso.",
        "",
    ]
    problems = 0
    for case in cases:
        lines.append(f"  {case.stratum.upper()}")
        lines.append(f"    perché: {case.why}")
        if case.empty:
            lines += ["    NESSUN CASO in archivio — lo strato non è coperto", ""]
            continue
        lines.append(f"    seduta del {case.day} (id {case.activity_id})")
        for finding in case.findings:
            lines.append(f"      · {finding}")
        for problem in case.problems:
            problems += 1
            lines.append(f"      ✗ {problem}")
        lines.append("")

    coperti = sum(1 for case in cases if not case.empty)
    lines += [
        f"  {coperti} strati su {len(cases)} hanno un caso reale.",
        f"  {problems} problemi rilevati automaticamente."
        if problems else "  Nessun problema rilevato automaticamente.",
        "",
        "  Il controllo automatico non sostituisce la lettura: guarda se i",
        "  numeri somigliano a quello che ricordi di quelle sedute.",
    ]
    return "\n".join(lines)
