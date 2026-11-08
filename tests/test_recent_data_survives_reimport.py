"""Ciò che l'export non contiene non deve sparire quando l'export si rilegge.

L'export scaricato a mano si ferma a una data. Le settimane successive esistono
soltanto perché il sync le ha scritte; i lap e le vasche soltanto perché
``details`` ha letto i FIT. Nessuna delle due cose sta in
``summarizedActivities.json``.

``ingest`` — il primo terzo di ``all`` — esegue ``DELETE FROM activities`` e
riempie la tabella con il solo export. L'audit indipendente lo ha riprodotto sul
database vero: 1.508 attività diventate 1.471, 1.340 nuotate diventate 1.306,
l'ultimo giorno con dati arretrato a luglio. E ``verify`` continuava a dire
21/21, perché nessun criterio guarda **indietro**.

Un archivio che si accorcia da solo è il guasto peggiore che questo progetto
possa avere: non rompe niente di visibile, e cancella l'unica cosa che non si
può riscaricare.
"""

import json
from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import paths
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import summaries
from garmin_coach.ingest.source_file import SourceFile

# Il giorno in cui si ferma l'export finto, e i giorni che esistono solo grazie
# al sync. La distanza fra i due è il punto della questione.
ULTIMO_GIORNO_EXPORT = date(2026, 7, 4)
GIORNO_SOLO_DAL_SYNC = date(2026, 8, 19)


def _attivita_export(activity_id: int, quando: date) -> dict:
    """Una riga come la scrive Garmin nell'export: centimetri e millisecondi."""
    inizio = datetime(quando.year, quando.month, quando.day, 8, 0)
    return {
        "activityId": activity_id,
        "beginTimestamp": int(inizio.timestamp() * 1000),
        "startTimeLocal": int(inizio.timestamp() * 1000),
        "activityType": "lap_swimming",
        "name": "Piscina",
        "distance": 300_000,          # 3.000 m in centimetri
        "duration": 3_600_000,        # 3.600 s in millisecondi
        "poolLength": 2500,           # 25 m in centimetri
        "calories": 2_095,            # kilojoule
        "hrTimeInZone_2": 900,
        "lapCount": 24,
        "activeLengths": 120,
        "timeZoneId": 100,
        "deviceId": 3_112_233_445,
    }


@pytest.fixture
def export_finto(tmp_path, monkeypatch):
    """Un export che si ferma al 4 luglio, come quello vero."""
    percorso = tmp_path / "summarizedActivities.json"
    percorso.write_text(json.dumps([{"summarizedActivitiesExport": [
        _attivita_export(1001, ULTIMO_GIORNO_EXPORT),
        _attivita_export(1002, date(2026, 6, 30)),
    ]}]), encoding="utf-8")

    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(summaries, "source_files", lambda: [SourceFile(percorso)])
    return percorso


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _scrivi_attivita_del_sync(con: duckdb.DuckDBPyConnection) -> None:
    """Una nuotata che esiste solo perché il sync l'ha scaricata da Garmin."""
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        " activity_date, sport, is_swim, environment, distance_m, duration_s, "
        " pool_length_m, device_id, source_object_id, imported_at) "
        "VALUES (2001, ?, ?, ?, 'lap_swimming', TRUE, 'pool', 4000, 4200, 25, "
        " 3112233445, 'garmin-connect://activity/2001', ?)",
        [datetime(2026, 8, 19, 19), datetime(2026, 8, 19, 19),
         GIORNO_SOLO_DAL_SYNC, datetime(2026, 8, 19, 20)])


class TestQuelloCheIlSyncHaPortato:
    def test_a_sync_activity_is_not_deleted_by_reimporting_the_export(
            self, connection, export_finto):
        """La riproduzione dell'audit, ridotta a tre righe.

        L'attività 2001 non è nell'export e non ci sarà mai: l'export è un file
        fermo. Se `ingest` la cancella, l'unico modo per riaverla è un sync che
        potrebbe non riuscire — e nel frattempo il coach risponde su un archivio
        più corto di quello che l'atleta ha davvero nuotato.
        """
        _scrivi_attivita_del_sync(connection)

        summaries.load(connection)

        superstite = connection.execute(
            "SELECT count(*) FROM activities WHERE activity_id = 2001"
        ).fetchone()[0]
        assert superstite == 1, (
            "l'attività arrivata dal sync è stata cancellata dal reimport "
            "dell'export: l'archivio si è accorciato da solo")

    def test_the_most_recent_day_never_goes_backwards(self, connection,
                                                      export_finto):
        """È l'invariante che nessuno dei 21 criteri di `verify` controlla.

        Un archivio può crescere, può restare fermo, e può correggere una riga.
        Non può tornare indietro nel tempo: se lo fa, qualcosa ha cancellato
        dati che non sapeva di avere.
        """
        _scrivi_attivita_del_sync(connection)
        prima = connection.execute(
            "SELECT max(activity_date) FROM activities").fetchone()[0]

        summaries.load(connection)

        dopo = connection.execute(
            "SELECT max(activity_date) FROM activities").fetchone()[0]
        assert dopo >= prima, (
            f"l'ultimo giorno con dati è arretrato da {prima} a {dopo}")

    def test_the_swim_count_never_goes_backwards(self, connection, export_finto):
        # Come nella realtà: l'export è già stato importato una volta, e il
        # sync ha aggiunto i giorni successivi. È il secondo import che perde.
        summaries.load(connection)
        _scrivi_attivita_del_sync(connection)
        prima = connection.execute(
            "SELECT count(*) FROM activities WHERE is_swim").fetchone()[0]

        summaries.load(connection)

        dopo = connection.execute(
            "SELECT count(*) FROM activities WHERE is_swim").fetchone()[0]
        assert dopo >= prima, f"le nuotate sono passate da {prima} a {dopo}"


class TestQuelloCheIFitHannoPortato:
    def test_laps_are_never_left_pointing_at_nothing(self, connection,
                                                     export_finto):
        """Cancellare `activities` senza toccare `activity_laps` lascia lap
        orfani: righe che descrivono una seduta che il database non ha più.

        Sono peggio di righe mancanti, perché ogni conteggio le trova e nessuna
        join le mostra.
        """
        _scrivi_attivita_del_sync(connection)
        connection.execute(
            "INSERT INTO activity_laps (activity_id, lap_index, start_time_utc, "
            " duration_s, distance_m, source_object_id, imported_at) "
            "VALUES (2001, 1, ?, 60, 100, 'fit://prova', ?)",
            [datetime(2026, 8, 19, 19), datetime(2026, 8, 19, 20)])

        summaries.load(connection)

        orfani = connection.execute("""
            SELECT count(*) FROM activity_laps l
            WHERE NOT EXISTS (SELECT 1 FROM activities a
                              WHERE a.activity_id = l.activity_id)
        """).fetchone()[0]
        assert orfani == 0, (
            f"{orfani} lap descrivono sedute che non esistono più")


class TestLaSaluteHaLoStessoProblema:
    """``health.load`` cancella le proprie tabelle con la stessa mossa.

    Il rilievo parlava di attività e nuotate perché sono i numeri che si vedono
    nel report. La salute sparisce identica, e in silenzio più profondo: nessuno
    conta i giorni di sonno a mente.
    """

    @pytest.fixture
    def export_salute(self, tmp_path, monkeypatch):
        from garmin_coach.ingest import health

        monkeypatch.setattr(paths, "ROOT", tmp_path)
        # Nessun file di salute nell'export: basta a mostrare la cancellazione,
        # ed è anche il caso vero delle categorie che l'export non contiene.
        monkeypatch.setattr(health, "discover", lambda *a, **k: [])
        return health

    def test_a_health_day_from_the_sync_survives_the_reimport(
            self, connection, export_salute):
        connection.execute(
            "INSERT INTO daily_health (health_date, resting_hr_bpm, "
            " source_object_id, imported_at) "
            "VALUES (?, 52, 'garmin-connect://user_summary/2026-08-19', ?)",
            [GIORNO_SOLO_DAL_SYNC, datetime(2026, 8, 19, 20)])

        export_salute.load(connection)

        rimasti = connection.execute(
            "SELECT count(*) FROM daily_health WHERE health_date = ?",
            [GIORNO_SOLO_DAL_SYNC]).fetchone()[0]
        assert rimasti == 1, (
            "il giorno di salute arrivato dal sync è stato cancellato dal "
            "reimport dell'export")

    def test_a_sleep_night_from_the_sync_survives_too(self, connection,
                                                      export_salute):
        connection.execute(
            "INSERT INTO sleep (sleep_date, total_sleep_s, source_object_id, "
            " imported_at) VALUES (?, 27000, "
            " 'garmin-connect://sleep/2026-08-19', ?)",
            [GIORNO_SOLO_DAL_SYNC, datetime(2026, 8, 19, 20)])

        export_salute.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM sleep WHERE sleep_date = ?",
            [GIORNO_SOLO_DAL_SYNC]).fetchone()[0] == 1


class TestIlCriterioCheMancava:
    """``verify`` non era cieco alla perdita: diventava verde a causa sua.

    C1-C5 contano le righe fino al 4 luglio 2026, il giorno in cui l'export si
    ferma. Cancellare tutto ciò che viene dopo riporta l'archivio **esattamente**
    al valore atteso. Serviva un pavimento, e il pavimento esiste già su disco:
    le catture del sync in ``data/raw/garmin-connect/``.
    """

    @pytest.fixture
    def catture(self, tmp_path, monkeypatch):
        cartella = tmp_path / "raw" / "garmin-connect" / "2026-08-19"
        cartella.mkdir(parents=True)
        (cartella / "get_user_summary.json").write_text(
            json.dumps({"calendarDate": "2026-08-19", "restingHeartRate": 52}),
            encoding="utf-8")
        monkeypatch.setattr("garmin_coach.ingest.source_catalog.RAW",
                            cartella.parent)
        return cartella.parent

    def _criterio(self, connection):
        """Solo C10: gli altri venti criteri parlano dell'archivio vero e su un
        database di prova direbbero soltanto che è di prova."""
        from garmin_coach.metrics import daily_status
        from garmin_coach.verification import run_checks

        daily_status.build(connection)
        return next(c for c in run_checks(connection) if c.identifier == "C10")

    def test_a_captured_day_that_vanished_is_reported(self, connection, catture):
        assert not self._criterio(connection).passed, (
            "il giorno è stato catturato dal sync e non è nel database, e "
            "verify non se ne accorge")

    def test_a_captured_day_that_is_there_passes(self, connection, catture):
        connection.execute(
            "INSERT INTO daily_health (health_date, resting_hr_bpm, "
            " source_object_id, imported_at) VALUES (?, 52, "
            " 'garmin-connect://user_summary/2026-08-19', ?)",
            [GIORNO_SOLO_DAL_SYNC, datetime(2026, 8, 19, 20)])

        assert self._criterio(connection).passed

    def test_a_day_garmin_had_nothing_for_is_not_a_loss(self, connection,
                                                        catture):
        """Un giorno senza orologio al polso esiste e non ha niente da mostrare.

        Pretendere una riga per ogni cattura trasformerebbe una giornata di
        riposo in un guasto, e il criterio verrebbe spento dopo due settimane.
        """
        (catture / "2026-08-19" / "get_user_summary.json").write_text(
            "null", encoding="utf-8")

        assert self._criterio(connection).passed


class TestIlComandoAllUsaTutteLeSorgenti:
    """``all`` importava solo l'export, e ``rebuild`` anche le catture.

    Due comandi che dicono di ricostruire la stessa cosa e ne ricostruiscono
    due diverse. Quello più innocuo dei due — ``all`` non cancella niente, e per
    questo lo si lancia senza pensarci — era quello che perdeva i dati.
    """

    @pytest.fixture
    def progetto(self, tmp_path, monkeypatch, export_finto):
        from garmin_coach import database, paths as percorsi
        from garmin_coach.ingest import health

        # L'export vero resta fuori da questa prova: e' di sola lettura e non
        # c'entra, ma leggerlo qui renderebbe il test lento e dipendente dai
        # dati dell'atleta.
        monkeypatch.setattr(health, "discover", lambda *a, **k: [])

        dati = tmp_path / "data"
        dati.mkdir()
        cattura = dati / "raw" / "garmin-connect" / "2026-08-19"
        cattura.mkdir(parents=True)
        (cattura / "get_user_summary.json").write_text(
            json.dumps({"calendarDate": "2026-08-19", "restingHeartRate": 52}),
            encoding="utf-8")

        monkeypatch.setattr(percorsi, "DATA", dati)
        monkeypatch.setattr(percorsi, "DATABASE", dati / "coach.duckdb")
        monkeypatch.setattr(percorsi, "STAGING", dati / "staging")
        monkeypatch.setattr("garmin_coach.rebuild.LOCK", dati / "scrittura.lock")
        monkeypatch.setattr("garmin_coach.ingest.source_catalog.RAW",
                            cattura.parent)
        with database.connect() as con:
            con.execute("SELECT 1")
        return dati

    def test_all_replays_the_captures_the_export_does_not_contain(self, progetto):
        from garmin_coach import cli, database

        # Il codice di uscita qui non dice niente: `verify` confronta i conteggi
        # con quelli dell'archivio vero e su un export finto di due attivita'
        # fallisce per forza. Cio che si prova e' cosa e' finito nel database.
        cli._all()

        with database.connect(read_only=True) as con:
            giorni = con.execute(
                "SELECT count(*) FROM daily_health WHERE health_date = ?",
                [GIORNO_SOLO_DAL_SYNC]).fetchone()[0]
        assert giorni == 1, (
            "all ha importato solo l'export: il giorno catturato dal sync non "
            "e' rientrato, e il database e' piu' corto di quello che l'atleta ha")
