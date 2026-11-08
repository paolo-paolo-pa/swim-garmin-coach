"""Lettura e scrittura dei markdown dell'atleta in ``coach/``.

I fatti misurati stanno nel database; le intenzioni dell'atleta — gare,
obiettivi, sensazioni, decisioni — stanno in markdown (Regola Aurea n.3).
Questo modulo è l'unico che li legge e li scrive.

Le scritture toccano **soltanto** ``coach/``: mai ``garmin-export/``, mai
``data/``, mai il resto del progetto.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import paths

# Le scritture di questo modulo leggono un file, lo cambiano e lo riscrivono.
# Due richieste che arrivano insieme leggerebbero la stessa versione e la
# seconda cancellerebbe la riga della prima. Il lucchetto le mette in fila.
#
# Il limite, dichiarato: protegge da questo processo, non da Notepad aperto
# sullo stesso file. Nessun lucchetto qui potrebbe.
_WRITING = threading.Lock()

# Il segnaposto che l'atleta lascia nei file quando un dato non c'è ancora.
PLACEHOLDER = "DA COMPILARE"

# Le righe di esempio nei modelli non sono dati veri.
EXAMPLE_MARKER = "(esempio)"

# Un testo scritto da un umano può essere lungo quanto vuole; quello che il
# coach rilegge va limitato per non divorare il contesto.
MAX_SECTION_CHARS = 4000
STRUCTURED_KINDS = {"workouts", "css-tests", "wellness", "training-settings", "training-blocks", "plan-links", "plan-revisions", "session-annotations"}


def structured_entries(kind: str) -> list[dict]:
    """Piani e test CSS dichiarati: markdown leggibile con blocco JSON."""
    import json
    if kind not in STRUCTURED_KINDS:
        raise ValueError("Tipo non supportato")
    folder = paths.COACH / kind
    entries = []
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8").split("```json\n", 1)[1].split("\n```", 1)[0]))
        except (ValueError, IndexError):
            continue
    if kind == "workouts":
        for block in structured_entries("training-blocks"):
            entries.extend(block.get("sessions", []))
    return entries


def add_structured_entry(kind: str, entry: dict) -> dict:
    """Unica scrittura autorizzata per le nuove intenzioni, dopo conferma UI."""
    import json
    import uuid
    if kind not in STRUCTURED_KINDS:
        raise ValueError("Tipo non supportato")
    with _WRITING:
        folder = paths.COACH / kind
        folder.mkdir(parents=True, exist_ok=True)
        # Il clock Windows può dare lo stesso timestamp a due salvataggi.
        # L'ordine delle revisioni non deve dipendere dall'UUID casuale.
        revision=max((int(r.get('saved_revision',0)) for r in structured_entries(kind)),default=0)+1
        entry = dict(entry, id=uuid.uuid4().hex, saved_at=datetime.now().isoformat(),saved_revision=revision)
        if kind == "training-blocks":
            entry["sessions"] = [dict(s,id=uuid.uuid4().hex,saved_at=entry["saved_at"],block_id=entry["id"]) for s in entry["sessions"]]
        _write_atomically(folder / (entry["id"] + ".md"),
                          "# " + str(entry.get("title", kind)).replace("\n", " ") +
                          "\n\nDichiarato e confermato dall’atleta.\n\n```json\n" +
                          json.dumps(entry, ensure_ascii=False, indent=2) + "\n```\n")
        return entry


def current_structured_entries(kind: str, key: str) -> list[dict]:
    """Ultima revisione per identità logica; gli originali restano leggibili."""
    latest = {}
    for entry in sorted(structured_entries(kind), key=lambda e:(e.get('saved_revision',0),e.get("saved_at", ""),e["id"])):
        latest[entry.get(key,entry["id"])] = entry
    return list(latest.values())


@dataclass(frozen=True)
class Race:
    race_id: str
    race_date: date
    name: str
    distance: str
    environment: str
    pool: str
    priority: str
    goal: str
    notes: str

    @property
    def days_away(self) -> int:
        return (self.race_date - date.today()).days


def _read(name: str) -> str:
    path = paths.COACH / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_atomically(path, text: str) -> None:
    """Scrive il file intero o non lo tocca: non esiste un mezzo file.

    ``write_text`` tronca prima di scrivere. Se il computer si spegne in quel
    mezzo secondo, il file dei riferimenti dell'atleta resta vuoto o mozzato —
    ed è uno dei pochi file di questo progetto che non si può ricostruire da
    nessuna sorgente.

    Il file nuovo nasce accanto a quello vero, sullo stesso disco perché
    ``os.replace`` sia una sostituzione e non una copia, e prende il suo posto
    in un colpo solo.
    """
    provvisorio = path.with_name(path.name + ".nuovo")
    try:
        provvisorio.write_text(text, encoding="utf-8")
        os.replace(provvisorio, path)
    except BaseException:
        provvisorio.unlink(missing_ok=True)
        raise


def _table_rows(text: str) -> list[list[str]]:
    """Le righe dati di una tabella markdown, senza intestazioni né separatori."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":", ""} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _iso_date(text: str) -> date | None:
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


WATCHES_FILE = "orologi.md"
UNKNOWN_WATCH = "Orologio non indicato"


def watches() -> list[tuple[date, date | None, str]]:
    """I modelli di orologio usati, da ``coach/orologi.md``: (dal, al, modello).

    Basta il modello (Forerunner 920, Fenix 6X, Fenix 7, Fenix 8...), non l'esemplare:
    l'atleta ne ha cambiati molti perché si rompevano, e per l'analisi conta che cosa
    quel modello poteva registrare. Nelle schermate l'identificativo Garmin del singolo
    orologio non compare mai.
    """
    result = []
    for cells in _table_rows(_read(WATCHES_FILE)):
        if len(cells) < 3:
            continue
        start, end, model = _iso_date(cells[0]), _iso_date(cells[1]), cells[2].strip()
        if start is None or not model or model.lower().startswith(("da compilare", "esempio")):
            continue
        result.append((start, end, model))
    return sorted(result, key=lambda row: row[0])


def watch_models_by_id() -> dict[int, str]:
    """Corrispondenza identificativo Garmin → modello, dalla tabella «identificativo | modello».

    Serve quando due modelli si usano negli stessi mesi (un vecchio orologio tenuto di
    riserva): la data da sola non li distingue, l'identificativo sì. Resta nel file
    dell'atleta e non viene mai mostrato.
    """
    result = {}
    for cells in _table_rows(_read(WATCHES_FILE)):
        if len(cells) == 2 and cells[0].isdigit() and cells[1].strip():
            result[int(cells[0])] = cells[1].strip()
    return result


def watch_label(day: date | None, rows: list | None = None) -> str:
    """Il modello in uso in un giorno, oppure «Orologio non indicato»."""
    if day is not None:
        for start, end, model in reversed(watches() if rows is None else rows):
            if start <= day and (end is None or day <= end):
                return model
    return UNKNOWN_WATCH


class WatchLabeler:
    """Etichetta ogni seduta con il modello di orologio, senza mostrare identificativi.

    Dove il modello non è indicato, esemplari diversi restano gruppi distinti
    («Orologio non indicato A», «B»...): il SWOLF di due orologi sconosciuti non si
    mescola. La lettera nasce dall'ordine di comparsa e non rivela l'identificativo.
    """

    def __init__(self) -> None:
        self._rows = watches()
        self._by_id = watch_models_by_id()
        self._unknown: dict[object, int] = {}

    def label(self, day: date | None, device_id=None) -> str:
        if device_id is not None and int(device_id) in self._by_id:
            return self._by_id[int(device_id)]
        model = watch_label(day, self._rows)
        if model != UNKNOWN_WATCH or device_id is None:
            return model
        index = self._unknown.setdefault(device_id, len(self._unknown))
        return f"{UNKNOWN_WATCH} {chr(65 + index % 26)}"


def races() -> list[Race]:
    """Le gare dichiarate in ``coach/gare.md``, in ordine di data.

    Una riga vale solo se ha una data valida e non è l'esempio del modello.
    """
    result: list[Race] = []
    for cells in _table_rows(_read("gare.md")):
        if any(EXAMPLE_MARKER in cell for cell in cells):
            continue
        race_date = _iso_date(cells[0])
        if race_date is None or len(cells) < 6:
            continue
        padded = cells + [""] * (8 - len(cells))
        result.append(Race(
            race_id=f"{race_date.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', padded[1].lower()).strip('-') or 'gara'}",
            race_date=race_date,
            name=padded[1],
            distance=padded[2],
            environment=padded[3],
            pool=padded[4],
            # Una gara senza priorità dichiarata vale C, come scritto in gare.md
            priority=(padded[5] or "C").upper()[:1],
            goal=padded[6],
            notes=padded[7],
        ))
    return sorted(result, key=lambda race: race.race_date)


def upcoming_races(horizon_days: int = 365, today: date | None = None) -> list[Race]:
    today = today or date.today()
    return [race for race in races()
            if 0 <= (race.race_date - today).days <= horizon_days]


def _missing_fields(text: str) -> list[str]:
    """Le voci ancora da compilare, con un'etichetta leggibile.

    In una tabella l'etichetta è la prima cella; altrove è il titolo della
    sezione in cui il segnaposto compare. Le righe di commento — quelle che
    iniziano con ``>`` — spiegano il file e non sono campi da compilare.
    """
    found: list[str] = []
    heading = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            continue
        if PLACEHOLDER not in stripped or stripped.startswith(">"):
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            label = cells[0] if cells else heading
        else:
            label = heading
        label = label.strip(" -|*`")
        if label and label not in found:
            found.append(label[:80])
    return found


def profile() -> dict:
    """Il contesto dell'atleta: cosa c'è e, soprattutto, cosa manca.

    Segnalare i campi vuoti è parte della risposta: un coach che non sa la vasca
    abituale deve dirlo, non dare per scontato 25 m.
    """
    athlete = _read("atleta.md")
    goals = _read("obiettivi.md")
    race_list = races()
    return {
        "athlete_profile": athlete[:MAX_SECTION_CHARS],
        "goals": goals[:MAX_SECTION_CHARS],
        "races_declared": len(race_list),
        "next_races": [
            {"race_id": race.race_id, "date": race.race_date.isoformat(),
             "name": race.name, "distance": race.distance,
             "priority": race.priority, "days_away": race.days_away}
            for race in upcoming_races()[:5]
        ],
        "missing_from_profile": _missing_fields(athlete),
        "missing_from_goals": _missing_fields(goals),
        "note": (
            "I campi elencati come mancanti non sono stati dichiarati dall'atleta. "
            "Il coach deve chiederli invece di assumerli."
        ),
    }


def append_to_diary(entry: str, when: date | None = None) -> str:
    """Aggiunge una voce al diario della settimana. È l'unica scrittura del
    progetto, e tocca soltanto ``coach/diario/``."""
    when = when or date.today()
    year, week, _ = when.isocalendar()
    folder = paths.COACH / "diario"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{year}-W{week:02d}.md"

    with _WRITING:
        if path.exists():
            testa = path.read_text(encoding="utf-8")
        else:
            monday = date.fromisocalendar(year, week, 1)
            sunday = date.fromisocalendar(year, week, 7)
            testa = (
                f"# Settimana {year}-W{week:02d} — {monday} → {sunday}\n\n"
                "Diario di allenamento: sensazioni, RPE, decisioni prese e perché.\n"
                "Scritto dall'atleta e dal coach. I fatti misurati stanno nel "
                "database.\n")

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        _write_atomically(path, f"{testa}\n## {stamp}\n\n{entry.strip()}\n")
    # Relativo a `coach/`, non alla radice del progetto: questa funzione scrive
    # dentro COACH e non ha motivo di sapere dove COACH si trova. Chiedere il
    # percorso rispetto a ROOT la rompeva ogni volta che COACH veniva spostata,
    # per esempio in una prova.
    return path.relative_to(paths.COACH.parent).as_posix()


# ── Riferimenti prestativi confermati (fase 4.4) ─────────────────────────

# Il coach non promuove mai un tempo a «riferimento» da solo. La differenza fra
# un numero nei dati e un riferimento è una persona che dice «quel giorno stavo
# andando a tutta», e quella persona non è il codice.
REFERENCES_FILE = "riferimenti.md"

# Le distanze che il coach sa leggere. Non è una limitazione tecnica: sono le
# distanze su cui esiste una curva prestativa sensata per un mezzofondista.
KNOWN_DISTANCES = (50, 100, 200, 400, 800, 1500)

KNOWN_STROKES = ("stile", "dorso", "rana", "delfino", "misti")

KNOWN_POOLS = ("25", "50", "acque libere")

KNOWN_KINDS = ("gara", "test", "time trial", "allenamento a tutta")

# Passi oltre i quali il numero non descrive un essere umano che nuota. Servono
# a rifiutare un errore di battitura invece di correggerlo in silenzio.
MIN_PLAUSIBLE_PACE_S = 30
MAX_PLAUSIBLE_PACE_S = 300


@dataclass(frozen=True)
class Reference:
    """Una prova confermata dall'atleta."""

    day: date
    distance_m: int
    stroke: str
    pool: str
    seconds: float
    kind: str
    context: str
    activity_id: int | None
    notes: str

    @property
    def pace_per_100m_s(self) -> float:
        return self.seconds / self.distance_m * 100

    @property
    def reference_id(self) -> str:
        return f"{self.day.isoformat()}-{self.distance_m}-{self.stroke}-{self.pool}"


class InvalidReference(ValueError):
    """Il riferimento non è scrivibile così com'è."""


def parse_swim_time(text: str) -> float:
    """``1:02,4``, ``4:35.10``, ``58,9`` → secondi.

    Il nuoto scrive i tempi in minuti, secondi e centesimi, e in Italia con la
    virgola. Accettare un solo formato costringerebbe l'atleta a convertire, che
    è esattamente il tipo di attrito per cui un modulo non viene mai usato.
    """
    ripulito = (text or "").strip().replace(",", ".")
    if not ripulito:
        raise InvalidReference("Il tempo è vuoto.")
    pezzi = ripulito.split(":")
    if len(pezzi) > 2:
        raise InvalidReference(f"Non capisco il tempo «{text}»: si scrive mm:ss,cc")
    try:
        if len(pezzi) == 2:
            minuti, secondi = int(pezzi[0]), float(pezzi[1])
        else:
            minuti, secondi = 0, float(pezzi[0])
    except ValueError:
        raise InvalidReference(f"Non capisco il tempo «{text}»: si scrive mm:ss,cc")
    if len(pezzi) == 2 and secondi >= 60:
        raise InvalidReference(f"«{text}»: i secondi devono stare sotto 60.")
    if minuti < 0 or secondi < 0:
        raise InvalidReference("Un tempo non può essere negativo.")
    return minuti * 60 + secondi


def format_swim_time(seconds: float) -> str:
    """Secondi → ``mm:ss,cc``, come si scrive in vasca.

    L'arrotondamento ai centesimi si fa **prima** di dividere per sessanta, e
    non lasciandolo fare alla formattazione. Fatto dopo, 119,999 s diventava
    ``1:60,00``: un minuto e sessanta secondi, che non esiste. Peggio, il
    progetto scriveva così una riga che ``parse_swim_time`` poi rifiutava,
    perché quella giustamente pretende i secondi sotto 60 — un tempo salvato
    nei riferimenti e non più rileggibile.

    Non è un caso di laboratorio: il passo per 100 m mostrato nell'anteprima è
    una divisione (``secondi / distanza × 100``) e cade su valori qualunque.
    """
    centesimi = round(seconds * 100)
    minuti, resto = divmod(centesimi, 6000)
    if minuti:
        return f"{minuti}:{resto // 100:02d},{resto % 100:02d}"
    return f"{resto // 100:d},{resto % 100:02d}"


def _one_line(text: str) -> str:
    """Testo scritto da un umano, ridotto a una cella di tabella.

    Le barre verticali spezzerebbero la tabella markdown; gli a capo pure.
    """
    return re.sub(r"\s+", " ", (text or "")).replace("|", "/").strip()[:200]


def validate_reference(*, day: str, distance_m: str, stroke: str, pool: str,
                       time: str, kind: str = "gara", context: str = "",
                       activity_id: str = "", notes: str = "") -> Reference:
    """Controlla e costruisce un riferimento. **Non scrive niente.**

    Separata dalla scrittura di proposito: l'anteprima che l'atleta conferma
    deve mostrare *esattamente* ciò che verrà scritto, e per farlo deve passare
    dagli stessi controlli.
    """
    quando = _iso_date(day or "")
    if quando is None:
        raise InvalidReference("La data manca o non è nel formato AAAA-MM-GG.")
    if quando > date.today():
        raise InvalidReference("La data è nel futuro.")

    try:
        distanza = int(str(distance_m).strip())
    except (TypeError, ValueError):
        raise InvalidReference("La distanza deve essere un numero di metri.")
    if distanza not in KNOWN_DISTANCES:
        raise InvalidReference(
            "Distanza non prevista. Quelle ammesse: "
            + ", ".join(str(d) for d in KNOWN_DISTANCES))

    stile = (stroke or "").strip().lower()
    if stile not in KNOWN_STROKES:
        raise InvalidReference("Stile non previsto: " + ", ".join(KNOWN_STROKES))

    vasca = (pool or "").strip().lower()
    if vasca not in KNOWN_POOLS:
        raise InvalidReference("Vasca non prevista: " + ", ".join(KNOWN_POOLS))

    tipo = (kind or "gara").strip().lower()
    if tipo not in KNOWN_KINDS:
        raise InvalidReference("Tipo non previsto: " + ", ".join(KNOWN_KINDS))

    secondi = parse_swim_time(time)
    passo = secondi / distanza * 100
    if not MIN_PLAUSIBLE_PACE_S <= passo <= MAX_PLAUSIBLE_PACE_S:
        raise InvalidReference(
            f"Il tempo dà un passo di {passo:.0f} s/100 m, fuori da quello che "
            "un essere umano nuota. Controlla il tempo o la distanza.")

    identificativo = None
    if str(activity_id).strip():
        try:
            identificativo = int(str(activity_id).strip())
        except ValueError:
            raise InvalidReference(
                "L'identificativo della seduta deve essere un numero.")

    return Reference(day=quando, distance_m=distanza, stroke=stile, pool=vasca,
                     seconds=secondi, kind=tipo, context=_one_line(context),
                     activity_id=identificativo, notes=_one_line(notes))


REFERENCE_HEADER = ("| Data | Distanza | Stile | Vasca | Tempo | Tipo | "
                    "Contesto | Seduta Garmin | Note |")


def references() -> list[Reference]:
    """I riferimenti confermati, dal più recente.

    Una riga scritta a mano che non torna viene **saltata**, non fa fallire la
    lettura di tutte le altre: un file compilato a mano è quasi sempre un po'
    sbagliato, e rifiutarlo per intero significherebbe non usarlo mai.
    """
    trovati: list[Reference] = []
    for cells in _table_rows(_read(REFERENCES_FILE)):
        if any(EXAMPLE_MARKER in cell for cell in cells) or len(cells) < 5:
            continue
        quando = _iso_date(cells[0])
        if quando is None:
            continue
        try:
            trovati.append(validate_reference(
                day=quando.isoformat(), distance_m=cells[1], stroke=cells[2],
                pool=cells[3], time=cells[4],
                kind=cells[5] if len(cells) > 5 else "gara",
                context=cells[6] if len(cells) > 6 else "",
                activity_id=cells[7] if len(cells) > 7 else "",
                notes=cells[8] if len(cells) > 8 else ""))
        except InvalidReference:
            continue
    return sorted(trovati, key=lambda r: r.day, reverse=True)


PROGRAM_FILE = "programma-settimanale.md"

# Le intenzioni che l'allenatore scrive e che il coach sa leggere. Sono poche di
# proposito: un elenco lungo invita a scegliere l'etichetta più vicina invece
# di quella giusta, e un'etichetta sbagliata è peggio di nessuna etichetta.
PROGRAM_PURPOSES = (
    "aerobico", "soglia", "vo2max", "velocità", "tecnica", "recupero",
    "specifico gara", "misto", "non dichiarato",
)


@dataclass(frozen=True)
class PlannedSession:
    """Una seduta come l'allenatore l'ha prevista, non come è andata."""

    day: date
    distance_m: int | None
    purpose: str
    detail: str
    notes: str

    @property
    def display(self) -> str:
        quanto = f"{self.distance_m} m" if self.distance_m else "senza volume dichiarato"
        return f"{quanto}, {self.purpose}"


def planned_sessions(weeks: int = 8, today: date | None = None
                     ) -> list[PlannedSession]:
    """Il programma dell'allenatore, letto da ``coach/programma-settimanale.md``.

    È la metà del ciclo che all'archivio è sempre mancata. L'orologio registra
    ciò che è stato **eseguito**; nessun dato contiene ciò che era **previsto**,
    perché il previsto vive su un foglio, in una chat, o nella testa di chi
    allena. Finché non lo scrive l'atleta, «hai fatto quello che dovevi?» non
    ha risposta — e non per un limite tecnico.

    Una riga che non torna viene saltata, non fa fallire le altre: un file
    compilato a mano è quasi sempre un po' sbagliato, e rifiutarlo per intero
    significherebbe non usarlo mai.
    """
    oggi = today or date.today()
    inizio = oggi - timedelta(weeks=weeks)
    trovate: list[PlannedSession] = []
    for cells in _table_rows(_read(PROGRAM_FILE)):
        if any(EXAMPLE_MARKER in cell for cell in cells) or len(cells) < 2:
            continue
        quando = _iso_date(cells[0])
        if quando is None or not (inizio <= quando <= oggi + timedelta(days=30)):
            continue
        padded = cells + [""] * (5 - len(cells))
        trovate.append(PlannedSession(
            day=quando,
            distance_m=_planned_metres(padded[1]),
            purpose=_planned_purpose(padded[2]),
            detail=padded[1].strip(),
            notes=padded[4] or padded[3]))
    return sorted(trovate, key=lambda una: una.day)


def _planned_metres(testo: str) -> int | None:
    """«3000 m» → 3000, «3 km» → 3000. Quello che non si legge resta assente."""
    pulito = (testo or "").strip().lower().replace(",", ".")
    chilometri = re.search(r"(\d+(?:\.\d+)?)\s*km", pulito)
    if chilometri:
        return round(float(chilometri.group(1)) * 1000)
    metri = re.search(r"(\d{3,6})", pulito)
    return int(metri.group(1)) if metri else None


def _planned_purpose(testo: str) -> str:
    """L'intento dichiarato, se è uno di quelli che il coach sa leggere."""
    pulito = (testo or "").strip().lower()
    for ammesso in PROGRAM_PURPOSES:
        if ammesso in pulito:
            return ammesso
    return "non dichiarato"


def add_reference(reference: Reference) -> str:
    """Aggiunge un riferimento sotto l'intestazione dell'ultima tabella.

    Scrive **solo** dentro ``coach/riferimenti.md``, e solo se il file esiste
    già: creare al volo un file di memoria dell'atleta è il modo in cui si
    finisce con due file che dicono cose diverse.
    """
    path = paths.COACH / REFERENCES_FILE
    if not path.exists():
        raise InvalidReference(
            f"Manca coach/{REFERENCES_FILE}. Il modulo scrive dentro un file "
            "che esiste, non ne inventa uno.")

    riga = "| " + " | ".join([
        reference.day.isoformat(),
        str(reference.distance_m),
        reference.stroke,
        reference.pool,
        format_swim_time(reference.seconds),
        reference.kind,
        reference.context,
        str(reference.activity_id) if reference.activity_id else "",
        reference.notes,
    ]) + " |"

    with _WRITING:
        testo = path.read_text(encoding="utf-8")
        if REFERENCE_HEADER not in testo:
            raise InvalidReference(
                f"In coach/{REFERENCES_FILE} non trovo la tabella delle prove "
                "confermate: il file è stato modificato in un modo che non "
                "riconosco.")

        # L'ultima tabella è quella vera; la prima è l'esempio da cancellare.
        intestazione = testo.rindex(REFERENCE_HEADER)
        fine_separatore = testo.index("\n", testo.index("\n", intestazione) + 1)
        _write_atomically(path, testo[:fine_separatore + 1] + riga + "\n"
                          + testo[fine_separatore + 1:])
    return f"coach/{REFERENCES_FILE}"


# ── Nota su una seduta: RPE, finalità, sensazione (fase 4.3) ─────────────

# La scala della fatica percepita adottata dal progetto, ricavata dai dati e non
# scelta a tavolino: sui 499 valori storici di `workoutRpe` compaiono solo
# decine, cioè una CR10 moltiplicata per dieci.
RPE_MIN, RPE_MAX = 1, 10

# La finalità di una serie la sa l'allenatore, non l'orologio. Queste sono le
# risposte che l'atleta può dare senza scrivere un tema; «non so» è una risposta
# legittima e resta tale, non diventa una casella vuota.
KNOWN_PURPOSES = ("non dichiarata", "fondo", "soglia", "velocità", "tecnica",
                  "scarico", "recupero attivo", "gara o test")


@dataclass(frozen=True)
class SessionNote:
    """Quello che l'atleta sa e i dati non possono sapere."""

    activity_id: int
    day: date
    rpe: int | None
    purpose: str
    feeling: str

    @property
    def summary(self) -> str:
        pezzi = []
        if self.rpe is not None:
            pezzi.append(f"fatica percepita {self.rpe}/10")
        if self.purpose and self.purpose != "non dichiarata":
            pezzi.append(f"finalità: {self.purpose}")
        if self.feeling:
            pezzi.append(self.feeling)
        return " · ".join(pezzi) or "nessun dettaglio aggiunto"


def validate_session_note(*, activity_id: str, day: str, rpe: str = "",
                          purpose: str = "", feeling: str = "") -> SessionNote:
    """Controlla una nota di seduta. Non scrive niente."""
    try:
        identificativo = int(str(activity_id).strip())
    except (TypeError, ValueError):
        raise InvalidReference("Manca l'identificativo della seduta.")

    quando = _iso_date(day or "")
    if quando is None:
        raise InvalidReference("La data della seduta non è leggibile.")

    valore = None
    testo_rpe = str(rpe).strip()
    if testo_rpe:
        try:
            valore = int(testo_rpe)
        except ValueError:
            raise InvalidReference("La fatica percepita è un numero da 1 a 10.")
        if not RPE_MIN <= valore <= RPE_MAX:
            raise InvalidReference(
                f"La fatica percepita va da {RPE_MIN} a {RPE_MAX}.")

    finalita = (purpose or "non dichiarata").strip().lower()
    if finalita not in KNOWN_PURPOSES:
        raise InvalidReference("Finalità non prevista: " + ", ".join(KNOWN_PURPOSES))

    sensazione = _one_line(feeling)
    if valore is None and finalita == "non dichiarata" and not sensazione:
        raise InvalidReference(
            "Non hai scritto niente da aggiungere: compila almeno un campo.")

    return SessionNote(activity_id=identificativo, day=quando, rpe=valore,
                       purpose=finalita, feeling=sensazione)


def add_session_note(note: SessionNote) -> str:
    """Scrive la nota nel diario della settimana della seduta.

    Va nel diario e non nel database per la Regola Aurea n.3: il database
    contiene fatti misurati e si ricostruisce da zero, il markdown contiene ciò
    che l'atleta sente e decide. Una nota scritta nel database sparirebbe alla
    prima ricostruzione.
    """
    righe = [f"**Seduta {note.activity_id}** del {note.day.strftime('%d/%m/%Y')}"]
    if note.rpe is not None:
        righe.append(f"- fatica percepita: **{note.rpe}/10** (CR10)")
    if note.purpose != "non dichiarata":
        righe.append(f"- finalità: **{note.purpose}**")
    if note.feeling:
        righe.append(f"- sensazione: {note.feeling}")
    return append_to_diary("\n".join(righe), note.day)


def declared_purposes() -> dict[int, dict]:
    """Che cosa l'atleta ha dichiarato di aver fatto, seduta per seduta.

    La finalità di una serie non sta nel file FIT e non ci starà mai: la sa
    l'atleta e la sa il suo allenatore. Sta nel diario, dove l'ha scritta lui,
    e da lì viene letta — non copiata in una tabella che poi diverge.

    Quando una seduta non ha una nota, non compare. È la copertura, e va
    mostrata invece di riempita: «tre sedute su sette hanno una finalità
    dichiarata» dice all'atleta perché vale la pena scriverle.
    """
    cartella = paths.COACH / "diario"
    if not cartella.exists():
        return {}

    trovate: dict[int, dict] = {}
    for file in sorted(cartella.glob("*.md")):
        for blocco in file.read_text(encoding="utf-8").split("\n## "):
            seduta = re.search(r"\*\*Seduta (\d+)\*\*", blocco)
            if not seduta:
                continue
            finalita = re.search(r"finalità: \*\*([^*]+)\*\*", blocco)
            fatica = re.search(r"fatica percepita: \*\*(\d+)/10\*\*", blocco)
            # L'ultima nota vince: se l'atleta ha riscritto una seduta, la
            # seconda volta ci ha pensato di più.
            trovate[int(seduta.group(1))] = {
                "purpose": finalita.group(1).strip() if finalita else None,
                "rpe": int(fatica.group(1)) if fatica else None,
            }
    return trovate


def session_notes(activity_id: int) -> list[str]:
    """Le note gia scritte su una seduta, per non chiederle due volte."""
    cartella = paths.COACH / "diario"
    if not cartella.exists():
        return []
    marcatore = f"**Seduta {int(activity_id)}**"
    trovate = []
    for file in sorted(cartella.glob("*.md")):
        testo = file.read_text(encoding="utf-8")
        for blocco in testo.split("\n## "):
            if marcatore in blocco:
                trovate.append(blocco.strip()[:MAX_SECTION_CHARS])
    return trovate


# ── Decisione su un dato dubbio (rilievo A2, seconda metà) ───────────────
#
# `corrections.py` legge `coach/correzioni-dati.md`. Fino a qui nessuno lo
# scriveva: la segnalazione automatica marcava `review` e poi l'atleta doveva
# aprire un file markdown, capire il formato di una tabella a sei colonne e
# ricopiare a mano un identificativo di undici cifre. Tre sedute sono rimaste
# in attesa per un giorno intero per questo, e la homepage ha detto «confidenza
# bassa» senza che ci fosse un modo comodo di toglierle il dubbio.

CORRECTIONS_FILE = "correzioni-dati.md"

CORRECTIONS_HEADER = ("| Activity ID | Stato | Data attività | Ambito | "
                      "Decisione e motivo | Confermata il |")

# L'ambito dipende dallo stato, e non è una domanda da fare all'atleta: è la
# conseguenza tecnica della sua decisione, e chiedergliela vorrebbe dire
# chiedergli di conoscere le nostre tabelle.
CORRECTION_SCOPES = {
    "exclude": "distanza, durata, passo, volume, carico, lap, record e confronti",
    "keep": "nessuno: l'anomalia è guardata e dichiarata vera",
    "review": "conclusioni forti",
}

# `correct` non si scrive da qui, ed è una scelta. Richiede i valori veri, e un
# modulo che chiede «quanto hai nuotato davvero?» a chi sta guardando un numero
# sbagliato invita a rispondere con una stima — che è esattamente la seconda
# invenzione che questo progetto ha deciso di non fare. Resta una modifica a
# mano, dove chi la scrive porta con sé il proprio motivo.
WRITABLE_DECISIONS = tuple(CORRECTION_SCOPES)

MIN_CORRECTION_REASON_CHARS = 10


@dataclass(frozen=True)
class Correction:
    """Ciò che l'atleta ha deciso su un'attività dubbia. Ancora non scritto."""

    activity_id: int
    status: str
    day: date
    reason: str

    @property
    def scope(self) -> str:
        return CORRECTION_SCOPES[self.status]

    @property
    def summary(self) -> str:
        parola = {"exclude": "esclusa da ogni metrica",
                  "keep": "tenuta, anomalia dichiarata vera",
                  "review": "lasciata in sospeso"}[self.status]
        return (f"Seduta {self.activity_id} del {self.day.strftime('%d/%m/%Y')}: "
                f"**{parola}**. Motivo: {self.reason}")


def validate_correction(*, activity_id: str, status: str, day: str,
                        reason: str = "") -> Correction:
    """Controlla la decisione. **Non scrive niente.**

    Il motivo è obbligatorio, e non per burocrazia: fra due anni l'unica cosa
    che permetterà di rimettere in discussione un'esclusione è sapere perché fu
    decisa. Una riga senza motivo è indistinguibile da un errore di battitura.
    """
    try:
        identificativo = int(str(activity_id).strip())
    except (TypeError, ValueError):
        raise InvalidReference("L'identificativo della seduta deve essere un numero.")

    stato = (status or "").strip().lower()
    if stato not in WRITABLE_DECISIONS:
        raise InvalidReference(
            "Decisione non prevista da qui. Quelle scrivibili sono: "
            + ", ".join(WRITABLE_DECISIONS)
            + ". Per «correct» servono i valori veri e si scrive a mano.")

    quando = _iso_date(day or "")
    if quando is None:
        raise InvalidReference("La data dell'attività manca o non è AAAA-MM-GG.")

    motivo = _one_line(reason)
    if len(motivo) < MIN_CORRECTION_REASON_CHARS:
        raise InvalidReference(
            "Scrivi perché lo stai decidendo, anche una riga. Fra un anno "
            "sarà l'unica cosa che permetterà di rimettere in discussione "
            "questa decisione.")

    return Correction(activity_id=identificativo, status=stato, day=quando,
                      reason=motivo)


def add_correction(correction: Correction) -> str:
    """Scrive la decisione in ``coach/correzioni-dati.md``.

    Se l'attività ha già una riga, la nuova va **sopra** e la vecchia resta:
    `corrections.declared()` legge dall'alto e l'ultima parola è la prima riga,
    ma la storia di come si è cambiato idea non si cancella. È la stessa scelta
    dei riferimenti, e per lo stesso motivo — un file che si può solo
    sovrascrivere è un file di cui non ci si fida.
    """
    path = paths.COACH / CORRECTIONS_FILE
    if not path.exists():
        raise InvalidReference(
            f"Manca coach/{CORRECTIONS_FILE}. Il modulo scrive dentro un file "
            "che esiste, non ne inventa uno.")

    riga = "| " + " | ".join([
        str(correction.activity_id),
        f"`{correction.status}`",
        correction.day.isoformat(),
        correction.scope,
        correction.reason,
        date.today().isoformat(),
    ]) + " |"

    with _WRITING:
        testo = path.read_text(encoding="utf-8")
        if CORRECTIONS_HEADER not in testo:
            raise InvalidReference(
                f"In coach/{CORRECTIONS_FILE} non trovo la tabella delle "
                "decisioni: il file è stato modificato in un modo che non "
                "riconosco.")
        intestazione = testo.rindex(CORRECTIONS_HEADER)
        fine_separatore = testo.index("\n", testo.index("\n", intestazione) + 1)
        _write_atomically(path, testo[:fine_separatore + 1] + riga + "\n"
                          + testo[fine_separatore + 1:])
    return f"coach/{CORRECTIONS_FILE}"
