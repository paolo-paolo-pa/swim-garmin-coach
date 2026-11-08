"""Le gare in acque libere, cronometrate da terzi e misurate da nessuno.

## La domanda a cui risponde

*«In mare, cosa ho fatto davvero — e quando?»*

L'obiettivo dichiarato dell'atleta è una 10 km in acque libere. Fino a qui
l'archivio sapeva quanto aveva nuotato in mare in allenamento e non sapeva
nulla delle sue gare in mare: la prima 10 km l'ha nuotata nel 2019 e il progetto
non lo sapeva. Sono 26 risultati dal 2016 al 2026, dal profilo Icron.

## Il tempo è misurato, la distanza no

È la differenza che governa tutto questo file. In vasca la piastra cronometra e
i 400 m sono 400 m certificati: entrambi i numeri sono misure. In mare il
cronometro resta una misura e **la distanza diventa una dichiarazione** — il
percorso è quello che boe, corrente e traiettoria hanno reso quel giorno.

L'atleta lo ha detto per primo, e l'archivio lo conferma: il 04/07/2026 Icron
chiama «MIGLIO» una gara che la traccia Garmin misura 1.234 m, meno sia di
1.609 sia di 1.852. Il passo per 100 m che si ricava da una gara in mare non è
un passo: è un tempo diviso per un numero che nessuno ha misurato.

Perciò ogni riga porta con sé `distance_source`, e chi legge sa sempre se sta
guardando una misura o una dichiarazione.

## Le tre cose che questo importatore non fa

**Non inventa la distanza mancante.** Cinque risultati riportano solo la
categoria (`MASTER`, `AGONISTI`, `AGONISTA`) e due il solo `MIGLIO`, che Icron
non quantifica. Quelle gare entrano con il loro tempo e `distance_m` a NULL.
Scegliere fra il miglio terrestre e quello marino significherebbe inventare
243 metri, e la Regola Aurea n.5 dice che un valore mancante resta mancante.

**Non attribuisce uno stile.** In acque libere si nuota a stile libero per
convenzione, non per regolamento, e Icron non lo scrive. `stroke` resta NULL:
è anche ciò che tiene queste gare fuori dai record di vasca, che filtrano su
uno stile noto.

**Non fonde due classifiche in due gare.** Il 12/09/2020 Icron espone lo stesso
risultato due volte — stesso giorno, stessa manifestazione, stesso tempo — una
volta in `AGONISTI_REGIONE` e una in `AGONISTI`: è una nuotata sola, classificata
in due graduatorie. Contarla due volte gonfierebbe ogni conteggio di gare per
sempre, e la chiave di raggruppamento è giorno + manifestazione + tempo proprio
per questo.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from .. import paths
from . import source_catalog

PARSER = "icron"
PARSER_VERSION = "1"
KIND = "icron"

FOLDER = "icron"
RACES_SUFFIX = "_icron_gare.csv"

ENVIRONMENT = "acque libere"

VALID = "valid"
INVALID = "invalid"

# Da dove viene la distanza. L'ordine è anche l'ordine di preferenza: il campo
# della prova batte il nome della gara, perché è il posto in cui
# l'organizzazione scrive la distanza quando la vuole dichiarare.
FROM_EVENT_FIELD = "event_field"
FROM_MEET_NAME = "meet_name"
UNKNOWN_DISTANCE = "unknown"

# Il miglio marino è 1.852 m per definizione, e le gare italiane che si
# chiamano così lo usano. Il miglio senza aggettivo no: può essere quello
# terrestre (1.609 m) o quello marino, Icron non lo dice, e la differenza è
# quasi un quarto di chilometro. Resta senza distanza.
NAUTICAL_MILE_M = 1852


@dataclass(frozen=True)
class Distance:
    """Quanto era lunga la gara, e chi lo dice."""

    metres: int | None
    source: str


def parse_day(text: str) -> date | None:
    trovato = re.fullmatch(r"\s*(\d{2})/(\d{2})/(\d{4})\s*", text or "")
    if not trovato:
        return None
    giorno, mese, anno = (int(g) for g in trovato.groups())
    return date(anno, mese, giorno)


def parse_time(text: str) -> float | None:
    """«00:25:35,005» e «00.38.39» → secondi. Due formati, una sola sorgente.

    Icron mostra i tempi come li ha ricevuti dai cronometristi, e i
    cronometristi non usano tutti la stessa convenzione: nello stesso file
    convivono i due punti e il punto come separatore, e i millesimi compaiono
    solo quando il cronometraggio li ha prodotti.

    Il formato è sempre ore-minuti-secondi, anche per una gara di ventidue
    minuti: `00.22.51` è 22'51" e non 22 ore. Una stringa che non ha quella
    forma non viene indovinata.
    """
    pulito = (text or "").strip()
    trovato = re.fullmatch(
        r"(\d{1,2})[:.](\d{2})[:.](\d{2})(?:[,.](\d{1,3}))?", pulito)
    if not trovato:
        return None
    ore, minuti, secondi, frazione = trovato.groups()
    valore = int(ore) * 3600 + int(minuti) * 60 + int(secondi)
    if frazione:
        valore += int(frazione) / (10 ** len(frazione))
    return valore


def parse_place(text: str) -> int | None:
    """«9°» → 9. Il grado non è un carattere, è il modo in cui si scrive.

    Il piazzamento non è una prestazione — dipende da chi si è presentato — ma
    in mare è l'unico fatto confrontabile fra due gare, perché il tempo non lo
    è: due percorsi «da 3 km» con corrente diversa danno tempi che non si
    possono mettere uno accanto all'altro.
    """
    trovato = re.search(r"(\d+)", text or "")
    return int(trovato.group(1)) if trovato else None


def _normalise(text: str) -> str:
    """Prepara l'etichetta al riconoscimento della distanza.

    Icron usa il trattino basso per due cose diverse: separare parole
    (`5000_AGONISTI`) e scrivere una virgola decimale (`1_5KM`, che è 1,5 km e
    non 15 né 1). Si distinguono da cosa hanno intorno: fra due cifre è una
    virgola, altrove è uno spazio.
    """
    con_virgola = re.sub(r"(?<=\d)_(?=\d)", ".", (text or "").upper())
    return con_virgola.replace("_", " ")


def parse_distance(event: str, meet: str) -> Distance:
    """Quanti metri erano, e da dove lo so.

    Si guarda prima il campo della prova, poi il nome della gara. Quando
    nessuno dei due contiene una distanza il risultato è `unknown`, e non un
    numero plausibile: `MASTER` e `AGONISTI` sono categorie, e chiamarle
    distanze produrrebbe passi inventati su gare che sono davvero successe.
    """
    metri = _metres_in(_normalise(event))
    if metri is not None:
        return Distance(metri, FROM_EVENT_FIELD)

    testo = _normalise(meet)
    if "MIGLIO MARINO" in testo:
        return Distance(NAUTICAL_MILE_M, FROM_MEET_NAME)

    # Nel nome della gara si accettano soltanto i chilometri scritti per esteso
    # — «3KM FIN», «DTW place09 3K». Un numero qualunque no: «3* event01»,
    # «1° TROFEO CITTA' DI place10» e «event03 OPEN WATER place32 2»
    # contengono cifre che non sono distanze, e leggerle come tali darebbe una
    # gara di tre metri.
    chilometri = re.search(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*K(?:M)?\b", testo)
    if chilometri:
        return Distance(round(float(chilometri.group(1).replace(",", ".")) * 1000),
                        FROM_MEET_NAME)

    return Distance(None, UNKNOWN_DISTANCE)


def _metres_in(testo: str) -> int | None:
    chilometri = re.search(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*K(?:M)?\b", testo)
    if chilometri:
        return round(float(chilometri.group(1).replace(",", ".")) * 1000)

    metri = re.search(r"(?<![\d.,])(\d+)\s*M(?:T)?\b", testo)
    if metri:
        return int(metri.group(1))

    # Il numero nudo vale **soltanto se apre l'etichetta**: «5000 AGONISTI»,
    # «1800 A», «1500». Quando la cifra viene dopo non è una distanza — in
    # «AGONISTI 2001» è l'anno della categoria, e leggerla come metri darebbe
    # una gara di 2.001 m mai nuotata.
    #
    # Le regole con l'unità esplicita (K, M, MT) restano libere di trovare il
    # numero ovunque nell'etichetta, perché lì è l'unità a dire che si tratta
    # di una lunghezza.
    nudo = re.match(r"(\d{3,5})\b", testo.strip())
    return int(nudo.group(1)) if nudo else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def race_id(day: date, meet: str, event: str) -> str:
    """L'identificatore di una gara in mare.

    Prefissato con la sorgente perché adesso le sorgenti di gare sono due, e due
    identificatori costruiti con regole diverse possono collidere senza che
    nessuno se ne accorga finché un record non diventa sbagliato.
    """
    return f"icron-{day.isoformat()}-{_slug(meet)}-{_slug(event)}"


def _folder() -> Path:
    return paths.COACH / FOLDER


def _files() -> list[Path]:
    cartella = _folder()
    if not cartella.exists():
        return []
    return sorted(uno for uno in cartella.rglob(f"*{RACES_SUFFIX}")
                  if uno.is_file())


def _locator(path: Path) -> str:
    try:
        return path.relative_to(paths.ROOT).as_posix()
    except ValueError:
        return f"{FOLDER}/{path.name}"


def _rows(path: Path) -> list[dict]:
    """Il CSV di Icron usa il punto e virgola, perché i tempi usano la virgola."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _owned(connection: duckdb.DuckDBPyConnection) -> list[str]:
    return [riga[0] for riga in connection.execute(
        "SELECT source_object_id FROM source_objects "
        "WHERE kind = ? AND parser = ?", [KIND, PARSER]).fetchall()]


def _delete_owned(connection: duckdb.DuckDBPyConnection,
                  posseduti: list[str]) -> None:
    """Cancella solo le righe di questa sorgente, mai quelle dell'altra.

    Le gare in archivio arrivano da due posti — la federazione per la vasca,
    Icron per il mare — e un importatore che cancellasse «tutte le gare» prima
    di riscrivere le proprie farebbe sparire quelle dell'altro a ogni `ingest`.
    È lo stesso difetto che in questo progetto ha già fatto arretrare il
    database una volta.
    """
    if not posseduti:
        return
    segnaposto = ", ".join("?" for _ in posseduti)
    connection.execute(
        f"DELETE FROM race_splits WHERE source_object_id IN ({segnaposto})",
        posseduti)
    connection.execute(
        f"DELETE FROM races WHERE source_object_id IN ({segnaposto})",
        posseduti)


def load(connection: duckdb.DuckDBPyConnection) -> dict:
    """Importa le gare in acque libere. Idempotente: rifarlo non cambia niente."""
    file_gare = _files()
    if not file_gare:
        posseduti = _owned(connection)
        if posseduti:
            connection.execute("BEGIN TRANSACTION")
            try:
                _delete_owned(connection, posseduti)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return {"races": 0, "files": 0, "skipped": [], "duplicates": 0,
                "without_distance": 0}

    adesso = datetime.now()
    sorgenti, gare, scartate = [], {}, []
    doppioni = 0

    for percorso in file_gare:
        sorgente = source_catalog.describe(
            percorso.read_bytes(), KIND, _locator(percorso),
            PARSER, PARSER_VERSION)
        sorgenti.append(sorgente)

        for riga in _rows(percorso):
            giorno = parse_day(riga.get("data", ""))
            manifestazione = (riga.get("gara") or "").strip()
            prova = (riga.get("prova") or "").strip()
            if giorno is None or not manifestazione:
                scartate.append(
                    f"{riga.get('data', '?')} {manifestazione or 'senza nome'}: "
                    "manca la data o il nome della gara")
                continue

            grezzo = (riga.get("tempo_originale") or "").strip()
            tempo = parse_time(grezzo)
            if tempo is None:
                scartate.append(f"{giorno} {manifestazione}: tempo «{grezzo}» "
                                "in un formato che non riconosco")

            distanza = parse_distance(prova, manifestazione)

            # Stessa nuotata, due graduatorie: la chiave le fonde invece di
            # contarle due volte.
            #
            # La distanza fa parte della chiave, e non è un dettaglio: nello
            # stesso giorno e nella stessa manifestazione ci sono davvero due
            # gare diverse — il 18/05/2019 un 2.700 e un 5.000 — e se per caso
            # chiudessero con lo stesso tempo una delle due sparirebbe senza
            # che nessuno se ne accorga. Il 12/09/2020, che è il caso da
            # fondere davvero, ha entrambe le distanze assenti e continua a
            # fondersi.
            chiave = (giorno, manifestazione.upper(), tempo, distanza.metres)
            if chiave in gare:
                doppioni += 1
                continue

            gare[chiave] = (
                race_id(giorno, manifestazione, prova),
                giorno, manifestazione, prova or "senza prova dichiarata",
                distanza.metres,
                None,                       # stroke: Icron non lo dichiara
                False, None,                # non esistono staffette qui
                None,                       # pool_length_m: non c'è vasca
                tempo,
                VALID if tempo is not None else INVALID,
                None,                       # timing: Icron non espone A o M
                None,                       # federation: varia per gara
                (riga.get("categoria") or "").strip() or None,
                None, None,                 # meet_id, event_id: non esposti
                sorgente.source_object_id, adesso,
                ENVIRONMENT, distanza.source,
                (riga.get("localita") or "").strip() or None,
                parse_place(riga.get("posizione_generale", "")),
                parse_place(riga.get("posizione_categoria", "")))

    posseduti = set(_owned(connection)) | {
        sorgente.source_object_id for sorgente in sorgenti}

    connection.execute("BEGIN TRANSACTION")
    try:
        source_catalog.register(connection, sorgenti)
        _delete_owned(connection, list(posseduti))
        if gare:
            connection.executemany(
                "INSERT OR REPLACE INTO races (race_id, race_date, meet, "
                " event_label, distance_m, stroke, is_relay, relay_legs, "
                " pool_length_m, time_s, status, timing, federation, category, "
                " meet_id, event_id, source_object_id, imported_at, "
                " environment, distance_source, venue, overall_place, "
                " category_place) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                " ?, ?, ?, ?, ?)",
                list(gare.values()))
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    return {
        "races": len(gare),
        "files": len(file_gare),
        "skipped": scartate,
        "duplicates": doppioni,
        "without_distance": sum(1 for una in gare.values() if una[4] is None),
    }
