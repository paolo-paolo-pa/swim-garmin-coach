"""I file originali delle sedute che l'export non contiene.

## Il buco, misurato

L'export storico si ferma al **4 luglio 2026**. Da allora il sync porta i
riepiloghi — distanza, durata, SWOLF medio — e basta: i file FIT arrivavano
soltanto dagli ZIP dell'export, che sono fermi.

Conseguenza al 24/08/2026: **36 nuotate su 36 successive a quella data non
avevano un solo lap.** Ottantatré chilometri, cioè l'intera preparazione
corrente verso place22, invisibili a qualunque analisi che guardi *dentro* una
seduta — serie, ripetute, vasca per vasca, traccia. E il numero cresceva di una
nuotata al giorno.

Nessuna delle analisi costruite nelle ultime settimane funzionava sulle sedute
di adesso. Funzionavano tutte solo sul passato.

## Cosa fa, e cosa non fa

Chiede a Garmin il file originale delle attività che non ce l'hanno, e lo salva
in `data/raw/activity-files/` accanto agli snapshot JSON, con la stessa regola:
**append-only**, mai sovrascritto. Da lì `details` e `track` lo leggono come
leggono gli ZIP.

Non interpreta niente. Il file viene salvato **prima** che qualcuno lo apra, per
la stessa ragione per cui esistono gli snapshot: se domani si scopre che un
campo era stato letto male, il rimedio non deve essere richiedere tutto a
Garmin.

## Perché scarica solo quello che manca

Il conto delle richieste non è teorico: questo account è già stato bloccato una
volta con un 429. Si scaricano soltanto le attività senza dettaglio, una volta
sola, e chi ha già il file non viene richiesto mai più.

## Il formato

Garmin restituisce il file originale dentro uno ZIP. Dentro c'è il `.fit`, che è
lo stesso formato dei file negli archivi dell'export — quindi a valle non cambia
niente: lo stesso lettore, le stesse regole di riconciliazione.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import duckdb

from . import source_catalog

# Quante attività al massimo per esecuzione. Non è una soglia tecnica: è il
# rispetto di un servizio di terzi che ci fa un favore. Con il sync ogni poche
# ore, venti sedute per volta recuperano l'arretrato in un paio di giorni senza
# che nessuno se ne accorga.
DEFAULT_LIMIT = 20

ZIP_MAGIC = b"PK"

# I FIT veri cominciano con un header la cui firma è ``.FIT`` al byte 8.
# Serve a non salvare come ``.fit`` qualcosa che non lo è: la prima versione di
# questo modulo si è fidata del formato predefinito della libreria — che è
# **TCX**, cioè XML — e ha scritto venti file XML con estensione ``.fit``.
# Nessuno se ne sarebbe accorto finché `details` non avesse smesso in silenzio
# di trovare lap.
FIT_SIGNATURE = b".FIT"


def looks_like_fit(content: bytes) -> bool:
    """Se questi byte sono davvero un file FIT.

    Un controllo di dodici byte che vale più di qualunque fiducia nel valore
    predefinito di una libreria di terzi.
    """
    return len(content) >= 12 and content[8:12] == FIT_SIGNATURE


@dataclass(frozen=True)
class DownloadReport:
    missing: int
    downloaded: int
    failed: int
    skipped_existing: int

    @property
    def still_missing(self) -> int:
        return self.missing - self.downloaded


def _fit_from(payload: bytes) -> bytes | None:
    """Il FIT vero, tirato fuori dallo ZIP con cui Garmin lo consegna.

    Se un giorno Garmin smettesse di incartarlo, i byte arriverebbero già buoni
    e questa funzione li lascerebbe passare: riconoscere lo ZIP dai suoi primi
    due byte costa niente ed evita di dover indovinare dalla versione della
    libreria.
    """
    if not payload:
        return None
    if not payload.startswith(ZIP_MAGIC):
        return payload
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        dentro = [n for n in bundle.namelist() if n.lower().endswith(".fit")]
        return bundle.read(dentro[0]) if dentro else None


def without_detail(connection: duckdb.DuckDBPyConnection) -> list[int]:
    """Le nuotate che non hanno lap e per cui non abbiamo già il file.

    Guarda `activity_laps` e non i verdetti di riconciliazione: il verdetto dice
    se l'aggancio è riuscito, questa domanda è più semplice e più vera — quella
    seduta ha un dettaglio, sì o no.
    """
    righe = connection.execute("""
        SELECT a.activity_id
        FROM activities a
        WHERE a.is_swim
          AND NOT EXISTS (SELECT 1 FROM activity_laps l
                          WHERE l.activity_id = a.activity_id)
        ORDER BY a.activity_date DESC
    """).fetchall()

    gia_scaricate = {percorso.stem.split("-")[0]
                     for percorso in source_catalog.RAW_FIT.glob("*.fit")} \
        if source_catalog.RAW_FIT.exists() else set()
    return [int(riga[0]) for riga in righe
            if str(riga[0]) not in gia_scaricate]


def pull(connection: duckdb.DuckDBPyConnection, client,
         limit: int = DEFAULT_LIMIT) -> DownloadReport:
    """Scarica i file mancanti e li registra fra le sorgenti."""
    mancanti = without_detail(connection)
    da_fare = mancanti[:limit]

    # Il formato va chiesto: il valore predefinito della libreria è TCX, cioè
    # XML. Chiederlo esplicitamente è anche una difesa contro il giorno in cui
    # quel valore predefinito cambierà di nuovo.
    from garminconnect import Garmin

    originale = Garmin.ActivityDownloadFormat.ORIGINAL

    descritte: list[source_catalog.SourceObject] = []
    falliti = 0
    for activity_id in da_fare:
        try:
            payload = client.download_activity(str(activity_id),
                                               dl_fmt=originale)
            contenuto = _fit_from(payload)
        except Exception:  # noqa: BLE001
            # Un'attività che non si scarica è una in meno, non un sync
            # fallito: al passaggio successivo ci si riprova.
            falliti += 1
            continue
        if not contenuto or not looks_like_fit(contenuto):
            falliti += 1
            continue
        descritte.append(source_catalog.capture_file(contenuto, activity_id))

    if descritte:
        source_catalog.register(connection, descritte)

    return DownloadReport(
        missing=len(mancanti),
        downloaded=len(descritte),
        failed=falliti,
        skipped_existing=0)
