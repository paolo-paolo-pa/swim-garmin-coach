"""``details`` non è mai arrivato in fondo, e nessun test se n'era accorto.

Il comando legge dal report chiavi che il report non ha: ``fit_files_indexed``,
``sessions_matched``, ``pool_swims``, ``sets``, ``unmatched``. I nomi veri sono
altri — ``fit_files_scanned``, ``verdicts``, ``swims``, ``laps``. Il risultato è
un ``KeyError`` dopo che tutto il lavoro è stato fatto: l'import scrive, e poi il
comando muore stampando una traccia Python all'atleta.

I 402 test non lo vedevano perché provavano ``swim_details.load`` e la riga di
comando separatamente, e fra le due c'è esattamente il punto in cui si rompe.
Un dizionario è un contratto che nessuno firma: qui diventa un tipo.
"""

import duckdb
import pytest

from garmin_coach import cli, database, paths
from garmin_coach.ingest import swim_details


@pytest.fixture
def progetto_finto(tmp_path, monkeypatch):
    """Un progetto completo in una cartella temporanea: database, export, lock.

    Il vincolo dell'incarico è assoluto — ``details`` non si esegue contro il
    database vero. Qui non c'è niente di vero: export vuoto, database vuoto,
    lock in ``tmp``.
    """
    export = tmp_path / "garmin-export"
    (export / "GUID" / "DI_CONNECT" / "DI-Connect-Fitness").mkdir(parents=True)
    dati = tmp_path / "data"
    dati.mkdir()

    monkeypatch.setattr(paths, "EXPORT", export)
    monkeypatch.setattr(paths, "DATA", dati)
    monkeypatch.setattr(paths, "DATABASE", dati / "coach.duckdb")
    monkeypatch.setattr(paths, "STAGING", dati / "staging")
    monkeypatch.setattr("garmin_coach.rebuild.LOCK", dati / "scrittura.lock")

    with database.connect() as connection:
        connection.execute("SELECT 1")
    return tmp_path


class TestIlComandoArrivaInFondo:
    def test_details_does_not_die_reading_its_own_report(self, progetto_finto,
                                                         capsys):
        """L'unico test che conta: il comando finisce e restituisce un esito.

        Nessuna nuotata, nessun FIT: è il caso più semplice possibile, e già
        così il comando non arriva alla fine.
        """
        assert cli._details() == 0
        uscita = capsys.readouterr().out
        assert "file FIT" in uscita

    def test_the_report_is_a_type_and_not_a_dictionary(self, progetto_finto):
        """Un dizionario lascia scoprire il nome sbagliato a runtime.

        Con un tipo, la chiave che non esiste è un errore di attributo che si
        vede leggendo il codice, e i nomi stanno scritti in un posto solo.
        """
        with database.connect() as connection:
            report = swim_details.load(connection)
        assert not isinstance(report, dict), (
            "il report è ancora un dizionario: ogni chiamante può inventarsi "
            "una chiave e scoprirlo solo quando il comando gira davvero")


class TestQuelloCheIlComandoLegge:
    """Ogni nome usato dalla riga di comando deve esistere nel report.

    È il test che avrebbe fermato il difetto in partenza, e resta utile: la
    prossima volta che qualcuno aggiunge una riga stampata, questa classe dice
    subito se il campo c'è.
    """

    NOMI_LETTI_DAL_COMANDO = [
        "fit_files_scanned", "swims", "laps", "lengths", "verdicts",
    ]

    @pytest.mark.parametrize("nome", NOMI_LETTI_DAL_COMANDO)
    def test_the_field_exists(self, progetto_finto, nome):
        with database.connect() as connection:
            report = swim_details.load(connection)
        assert hasattr(report, nome) or (
            isinstance(report, dict) and nome in report), (
            f"il report non ha «{nome}»")


class TestUnCriterioNonDeveFallirePerIlTempoChePassa:
    """C8c falliva il giorno stesso in cui l'atleta nuotava.

    Trovato eseguendo `verify` sull'archivio vero dopo aver corretto `details`:
    il sync delle [orario] aveva scritto la nuotata di oggi, nessun FIT poteva
    ancora descriverla, e il criterio la contava come seduta senza verdetto.

    L'unico rimedio sarebbe stato eseguire `details` — cioe' il comando che si
    rompeva con un KeyError. La strada per tornare verdi non esisteva, e un
    criterio che non si puo' soddisfare insegna a ignorare tutti gli altri.
    """

    @pytest.fixture
    def connessione(self):
        import duckdb
        from garmin_coach.database import SCHEMA

        con = duckdb.connect(":memory:")
        con.execute(SCHEMA)
        yield con
        con.close()

    def _c8c(self, connection):
        from garmin_coach.metrics import daily_status
        from garmin_coach.verification import run_checks

        daily_status.build(connection)
        return next(c for c in run_checks(connection) if c.identifier == "C8c")

    def _nuotata(self, con, activity_id, quando, importata):
        from datetime import datetime

        con.execute(
            "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
            " sport, is_swim, distance_m, duration_s, source_object_id, "
            " imported_at) VALUES (?, ?, ?, 'lap_swimming', TRUE, 3000, 3600, "
            " 'garmin-connect://activity/1', ?)",
            [activity_id, datetime.combine(quando, datetime.min.time()), quando,
             importata])

    @pytest.fixture
    def details_gia_passato(self, connessione):
        """Una seduta vecchia, col suo lap e il suo verdetto, e una corsa di
        `details` alle 10:00 del 20 agosto.

        Il lap serve: i criteri C8 si attivano solo su un database in cui la
        Fase 5 e' stata eseguita, e senza sarebbero controlli su tabelle vuote.
        """
        from datetime import date, datetime

        self._nuotata(connessione, 100, date(2026, 8, 1), datetime(2026, 8, 1, 9))
        connessione.execute(
            "INSERT INTO activity_laps (activity_id, lap_index, start_time_utc, "
            " duration_s, distance_m, is_rest, source_object_id, imported_at) "
            "VALUES (100, 1, ?, 3600, 3000, FALSE, 'fit://prova', ?)",
            [datetime(2026, 8, 1, 9), datetime(2026, 8, 20, 10)])
        connessione.execute(
            "INSERT INTO activity_source_matches (activity_id, source_object_id, "
            " verdict, method, decided_at) "
            "VALUES (100, 'fit://prova', 'matched', 'timestamp', ?)",
            [datetime(2026, 8, 20, 10)])
        connessione.execute(
            "INSERT INTO ingest_runs (run_id, command, started_at, outcome) "
            "VALUES ('r1', 'details', ?, 'ok')", [datetime(2026, 8, 20, 10)])
        return connessione

    def test_a_swim_arrived_after_the_last_details_run_is_not_a_failure(
            self, details_gia_passato):
        """La nuotata di stasera. Il sync l'ha scritta alle [orario], `details`
        e' passato stamattina, e nessun FIT potra' mai descriverla finche' non
        si rilancia."""
        from datetime import date, datetime

        self._nuotata(details_gia_passato, 1, date(2026, 8, 21),
                      datetime(2026, 8, 21, 20, 30))

        assert self._c8c(details_gia_passato).passed, (
            "la nuotata di oggi non ha un verdetto perche' details non e' "
            "ancora passato: non e' un difetto dei dati")

    def test_a_swim_details_did_see_and_did_not_judge_is_still_a_failure(
            self, details_gia_passato):
        from datetime import date, datetime

        self._nuotata(details_gia_passato, 1, date(2026, 8, 18),
                      datetime(2026, 8, 18, 9))

        assert not self._c8c(details_gia_passato).passed, (
            "details era passato dopo questa seduta e non le ha dato nessun "
            "verdetto: quello resta un buco vero")
