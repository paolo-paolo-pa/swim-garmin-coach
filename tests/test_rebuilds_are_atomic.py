"""Rifare il database non deve poter lasciare mezzo database.

Tre operazioni riscrivono in blocco, e tutte e tre lo fanno sul file vivo:

- ``rebuild`` cancella ``data/coach.duckdb`` e lo ricostruisce al suo posto. Se
  la ricostruzione si ferma a metà — un FIT illeggibile, il computer che si
  spegne, un ``Ctrl+C`` — quello che resta non è il database di prima e non è
  quello nuovo. C'è una copia di sicurezza, ma rimetterla a posto è un gesto
  manuale che va saputo fare nel momento peggiore.

- ``details`` cancella ``activity_laps``, ``pool_lengths`` e
  ``activity_source_matches`` e le riempie di nuovo. Con ``limit`` cancella
  **tutto** e reinserisce soltanto il sottoinsieme richiesto: una modalità
  diagnostica che svuota l'archivio del dettaglio.

- ``reset`` cancella il file e il suo WAL, uno dopo l'altro, senza lucchetto.

Nessuna di queste è distruttiva sui dati originali — l'export non si tocca e il
database è generato. Ma «ricostruibile» vale finché la ricostruzione riesce, e
il momento in cui non riesce è esattamente il momento in cui serve.

Tutte le prove qui girano su directory temporanee: il vincolo dell'incarico è
assoluto e il database vero non viene sfiorato.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import database, paths


@pytest.fixture
def progetto(tmp_path, monkeypatch):
    """Un progetto in miniatura: dati in tmp, export finto, lucchetto in tmp."""
    export = tmp_path / "garmin-export"
    (export / "GUID" / "DI_CONNECT" / "DI-Connect-Fitness").mkdir(parents=True)
    dati = tmp_path / "data"
    dati.mkdir()

    monkeypatch.setattr(paths, "EXPORT", export)
    monkeypatch.setattr(paths, "DATA", dati)
    monkeypatch.setattr(paths, "DATABASE", dati / "coach.duckdb")
    monkeypatch.setattr(paths, "STAGING", dati / "staging")
    monkeypatch.setattr("garmin_coach.rebuild.LOCK", dati / "scrittura.lock")
    monkeypatch.setattr("garmin_coach.ingest.source_catalog.RAW", dati / "raw")
    return dati


def _database_con_dati(quante: int = 3) -> None:
    with database.connect() as con:
        con.execute("""
            INSERT INTO activities (activity_id, start_time_utc, activity_date,
                                    sport, is_swim, distance_m, duration_s,
                                    source_object_id, imported_at)
            SELECT i, (DATE '2026-08-01' + INTERVAL (i) DAY)::TIMESTAMP,
                   (DATE '2026-08-01' + INTERVAL (i) DAY)::DATE,
                   'lap_swimming', TRUE, 3000, 3600,
                   repeat('a', 64), TIMESTAMP '2026-01-01'
            FROM range(1, ?) t(i)
        """, [quante + 1])


def _quante_attivita() -> int:
    with database.connect(read_only=True) as con:
        return con.execute("SELECT count(*) FROM activities").fetchone()[0]


class TestUnaRicostruzioneFallitaNonLasciaMacerie:
    def test_the_live_database_survives_a_rebuild_that_breaks_halfway(
            self, progetto, monkeypatch):
        """Il caso peggiore, e non è raro: si rompe **dopo** aver cancellato.

        Un archivio di nove anni sparisce e al suo posto resta un file a metà.
        La copia di sicurezza c'è, ma rimetterla è un gesto manuale da fare nel
        momento in cui si è appena persa la fiducia nello strumento.
        """
        from garmin_coach import rebuild as rebuilder
        from garmin_coach.ingest import summaries

        _database_con_dati(3)
        assert _quante_attivita() == 3

        def esplode(connection):
            raise RuntimeError("un file dell'export è illeggibile")

        monkeypatch.setattr(summaries, "load", esplode)

        with pytest.raises(RuntimeError):
            rebuilder.rebuild()

        assert paths.DATABASE.exists(), "il database vivo è sparito"
        assert _quante_attivita() == 3, (
            "la ricostruzione fallita ha lasciato un database diverso da quello "
            "di partenza")

    def test_a_failed_rebuild_leaves_no_leftovers_behind(self, progetto,
                                                         monkeypatch):
        """Nessun file candidato dimenticato: il tentativo non lascia tracce."""
        from garmin_coach import rebuild as rebuilder
        from garmin_coach.ingest import summaries

        _database_con_dati(2)
        prima = sorted(p.name for p in progetto.iterdir())

        monkeypatch.setattr(summaries, "load",
                            lambda c: (_ for _ in ()).throw(RuntimeError("no")))
        with pytest.raises(RuntimeError):
            rebuilder.rebuild()

        assert sorted(p.name for p in progetto.iterdir()) == prima

    def test_a_rebuild_never_writes_into_the_live_file(self, progetto,
                                                       monkeypatch):
        """La prova che la ricostruzione avviene altrove.

        Se costruisse in loco, il file vivo cambierebbe **durante** il lavoro:
        e in quel momento l'app che lo legge in sola lettura vedrebbe un
        database a metà.
        """
        from garmin_coach import rebuild as rebuilder

        _database_con_dati(2)
        visti: list = []

        vero = database.connect

        def spiando(read_only=False, path=None):
            visti.append(str(path or paths.DATABASE))
            return vero(read_only=read_only, path=path)

        monkeypatch.setattr(database, "connect", spiando)
        rebuilder.rebuild(with_details=False)

        scritture_sul_vivo = [p for p in visti if p == str(paths.DATABASE)]
        assert not scritture_sul_vivo, (
            f"la ricostruzione ha aperto il file vivo: {scritture_sul_vivo}")

    def test_a_rebuild_that_succeeds_actually_replaces_it(self, progetto):
        from garmin_coach import rebuild as rebuilder

        _database_con_dati(5)
        report = rebuilder.rebuild(with_details=False)

        # L'export finto è vuoto: la ricostruzione produce un database vuoto, e
        # deve essere **quello** a prendere il posto del vecchio.
        assert report["activities"] == 0
        assert _quante_attivita() == 0


class TestIlDettaglioFitNonSiCancellaAMeta:
    def test_a_failing_detail_import_does_not_empty_the_tables(self, progetto,
                                                               monkeypatch):
        from garmin_coach.ingest import swim_details

        _database_con_dati(2)
        with database.connect() as con:
            con.execute(
                "INSERT INTO activity_laps (activity_id, lap_index, "
                " start_time_utc, duration_s, distance_m, source_object_id, "
                " imported_at) VALUES (1, 1, ?, 60, 100, 'fit://vecchio', ?)",
                [datetime(2026, 8, 2, 9), datetime(2026, 8, 2, 10)])

        monkeypatch.setattr(swim_details, "_bulk_insert",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("il CSV di appoggio non si scrive")))

        with database.connect() as con:
            with pytest.raises(RuntimeError):
                swim_details.load(con)

        with database.connect(read_only=True) as con:
            rimasti = con.execute(
                "SELECT count(*) FROM activity_laps").fetchone()[0]
        assert rimasti == 1, (
            "l'import fallito ha svuotato activity_laps: le tabelle erano già "
            "state cancellate quando si è rotto")

    def test_a_limited_import_does_not_delete_what_it_will_not_reinsert(
            self, progetto):
        """``limit`` è una modalità diagnostica, non una cancellazione.

        Cancellava tutte e tre le tabelle e reinseriva solo il sottoinsieme
        chiesto: un `--limit 5` per guardare cosa succede svuotava l'archivio
        del dettaglio di nove anni.
        """
        from garmin_coach.ingest import swim_details

        _database_con_dati(3)
        with database.connect() as con:
            for activity_id in (1, 2, 3):
                con.execute(
                    "INSERT INTO activity_laps (activity_id, lap_index, "
                    " start_time_utc, duration_s, distance_m, "
                    " source_object_id, imported_at) "
                    "VALUES (?, 1, ?, 60, 100, 'fit://vecchio', ?)",
                    [activity_id, datetime(2026, 8, 2, 9),
                     datetime(2026, 8, 2, 10)])

            swim_details.load(con, limit=1)

            rimasti = con.execute(
                "SELECT count(DISTINCT activity_id) FROM activity_laps"
            ).fetchone()[0]
        assert rimasti >= 2, (
            "un import con limit ha cancellato il dettaglio delle sedute che "
            "non aveva nemmeno guardato")

    def test_a_failed_run_is_recorded_as_failed(self, progetto, monkeypatch):
        """Un ``ingest_run`` che resta `running` per sempre è una bugia sul
        proprio stato: alla prossima occhiata sembra un import ancora in corso."""
        from garmin_coach.ingest import swim_details

        _database_con_dati(1)
        monkeypatch.setattr(swim_details, "_bulk_insert",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("rotto")))

        with database.connect() as con:
            with pytest.raises(RuntimeError):
                swim_details.load(con)
            sospese = con.execute(
                "SELECT count(*) FROM ingest_runs WHERE finished_at IS NULL"
            ).fetchone()[0]
        assert sospese == 0, (
            f"{sospese} esecuzioni risultano ancora in corso e non lo sono")


class TestResetNonLasciaMezzoFile:
    def test_reset_removes_the_write_ahead_log_first(self, progetto):
        """Se sparisce il database ma resta il WAL, la riapertura successiva
        prova a rigiocare un giornale che non ha più il proprio libro."""
        _database_con_dati(1)
        wal = paths.DATABASE.with_name(paths.DATABASE.name + ".wal")
        wal.write_bytes(b"giornale")

        database.reset()

        assert not wal.exists(), "il WAL è rimasto senza il suo database"
        assert not paths.DATABASE.exists()

    def test_reset_refuses_while_another_write_is_in_progress(self, progetto):
        """Cancellare il database mentre un sync ci sta scrivendo dentro."""
        from garmin_coach import rebuild as rebuilder

        _database_con_dati(1)
        with rebuilder.single_writer("un sync finto"):
            with pytest.raises(rebuilder.DatabaseBusy):
                database.reset()

        assert paths.DATABASE.exists(), "il database è stato cancellato lo stesso"
