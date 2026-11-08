"""Connessione e schema del database.

Un solo database, DuckDB, in ``data/coach.duckdb``. È interamente generato:
si può cancellare e ricostruire in qualunque momento da ``garmin-export/``.

Provenienza: ogni tabella importata porta ``source_object_id`` e ``imported_at``
(decisione n.6 del piano). Nessun sottosistema di governance.

``source_object_id`` è un **riferimento alla sorgente**, non un hash, e le forme
lecite sono due e restano riconoscibili: lo SHA-256 del file dell'export, oppure
un URI ``garmin-connect://…`` per le risposte del sync. Si chiamava
``source_sha`` e conteneva entrambe le cose: il nome prometteva la prima e il
criterio C9 ora controlla che non ne compaia una terza.

Unità di misura, uniformi su tutto il database:

| Grandezza      | Unità        |
|----------------|--------------|
| distanza       | metri        |
| durata         | secondi      |
| frequenza card.| bpm          |
| velocità       | m/s          |
| peso           | kg           |
| HRV            | millisecondi |
| temperatura    | °C           |
"""

from __future__ import annotations

import duckdb

from . import paths, schema_migrations

# Lo schema non vive più qui: sta nei file di ``migrations/`` e viene applicato
# da ``schema_migrations``. Il motivo è in quel modulo — ``CREATE TABLE IF NOT
# EXISTS`` non aggiorna un database già esistente, e questo progetto ne ha uno.
#
# ``SCHEMA`` resta come scorciatoia per costruire un database di prova in
# memoria: è la stessa sequenza di istruzioni, applicata in una volta sola.
SCHEMA = schema_migrations.combined_sql()


def connect(read_only: bool = False, path=None) -> duckdb.DuckDBPyConnection:
    """Apre il database. Lo crea se non esiste.

    ``path`` serve a lavorare su un database che non è ancora quello vero: la
    ricostruzione costruisce un candidato accanto e lo mette al posto del vivo
    solo quando è finito. Senza questo parametro l'unico modo di ricostruire
    era cancellare prima e sperare poi.
    """
    paths.ensure_data_dirs()
    connection = duckdb.connect(str(path or paths.DATABASE), read_only=read_only)
    if not read_only:
        schema_migrations.apply(connection)
    return connection


def table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    """Se una tabella esiste davvero in questo database.

    Le capacità del coach crescono per fasi, quindi il codice interroga tabelle
    che in un database più vecchio possono non esserci ancora. Chiederlo prima è
    la differenza fra rispondere «questo non lo so ancora fare» e rompersi.

    Sta qui perché era scritto tre volte — in ``mcp/queries.py``, in
    ``mcp/capabilities.py`` e in ``verification.py`` — e tre copie della stessa
    riga sono tre occasioni di correggerne solo due.
    """
    return connection.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?", [table]).fetchone()[0] > 0


def reset() -> None:
    """Cancella il database. È interamente ricostruibile: nessun dato originale
    vive qui dentro.

    Due dettagli che non erano dettagli.

    **Il giornale prima del libro.** Il WAL si cancella per primo: se sparisse
    il database e restasse il WAL, la riapertura successiva proverebbe a
    rigiocare un giornale che non ha più il proprio libro.

    **Il lucchetto.** Cancellare il file mentre il sync automatico ci sta
    scrivendo dentro non è un'operazione innocua per il fatto che il contenuto
    è rigenerabile: è un'operazione che interrompe l'altra a metà.
    """
    from . import rebuild

    with rebuild.single_writer("cancellazione del database"):
        for suffix in (".wal", ""):
            target = paths.DATABASE.with_name(paths.DATABASE.name + suffix)
            target.unlink(missing_ok=True)
