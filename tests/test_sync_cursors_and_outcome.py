"""Da dove riparte il sync, e cosa dichiara di aver fatto.

Tre difetti, tutti nello stesso punto: il sync sa meno di quello che dice.

**Un cursore solo per due famiglie di dati.** ``_last_known_day`` prende il
massimo fra l'ultima attività e l'ultimo giorno di salute. Una nuotata di ieri
sposta il cursore in avanti anche se la salute è ferma a tre mesi fa: il buco
non viene mai colmato, e nessuno lo dice. Le due famiglie hanno vite separate —
un orologio scarico non registra il sonno ma l'attività la carica il telefono —
quindi vogliono due cursori.

**Un giorno scritto a metà.** ``daily_health``, ``sleep`` e ``health_status`` si
scrivono con tre ``execute`` separati e DuckDB conferma ognuno per conto suo. Se
l'endpoint del sonno fallisce, il giorno resta con la salute scritta e il sonno
mancante — e alla successiva esecuzione quel giorno è "già fatto", perché il
cursore lo ha superato.

**Un errore chiamato «saltato».** Qualunque eccezione di un endpoint finisce in
``skipped``, e ``succeeded`` guarda solo ``errors``. Un sync in cui ogni singolo
giorno è fallito restituisce «riuscito», scrive nel log che è andato bene, e
lascia l'atleta a guardare dati vecchi convinto che siano freschi.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.ingest import sync

OGGI = date(2026, 8, 20)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


class ClientFinto:
    """Un client che sa fallire in un punto solo, per volta."""

    def __init__(self, *, summary=None, sleep=None, hrv=None,
                 rompi=(), giorni_visti=None):
        self._summary = summary if summary is not None else {"restingHeartRate": 52}
        self._sleep = sleep if sleep is not None else {"sleepTimeSeconds": 27000}
        self._hrv = hrv if hrv is not None else {"lastNightAvg": 62}
        self._rompi = set(rompi)
        self.giorni_visti = giorni_visti if giorni_visti is not None else []

    def get_activities_by_date(self, start, end):
        return []

    def get_user_summary(self, day):
        self.giorni_visti.append(day)
        if "summary" in self._rompi:
            raise ConnectionError("Garmin non risponde")
        return self._summary

    def get_sleep_data(self, day):
        if "sleep" in self._rompi:
            raise ConnectionError("endpoint del sonno non raggiungibile")
        return {"dailySleepDTO": self._sleep}

    def get_hrv_data(self, day):
        if "hrv" in self._rompi:
            raise ConnectionError("endpoint HRV non raggiungibile")
        return {"hrvSummary": self._hrv}


def _attivita(con, giorno: date, activity_id: int = 1) -> None:
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, distance_m, duration_s, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 3000, 3600, 'abc', ?)",
        [activity_id, datetime(giorno.year, giorno.month, giorno.day, 8), giorno,
         datetime(2026, 1, 1)])


def _salute(con, giorno: date) -> None:
    con.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, "
        " source_object_id, imported_at) VALUES (?, 52, 'abc', ?)",
        [giorno, datetime(2026, 1, 1)])


class TestDueFamiglieDueCursori:
    def test_a_hole_in_health_is_refilled_even_if_activities_are_fresh(
            self, connection):
        """La nuotata di ieri non è una prova che il sonno di maggio ci sia.

        Le attività arrivano fino a ieri, la salute si ferma a tre mesi fa. Il
        sync deve tornare a prendere i giorni di salute mancanti: se parte da
        ieri per entrambe, quel buco non si chiude più da solo.
        """
        _attivita(connection, OGGI - timedelta(days=1))
        _salute(connection, OGGI - timedelta(days=40))

        client = ClientFinto()
        sync.pull(connection, until=OGGI, client=client)

        primo_giorno_chiesto = min(client.giorni_visti)
        assert primo_giorno_chiesto <= (OGGI - timedelta(days=40)).isoformat(), (
            "il sync è ripartito dall'ultima attività invece che dall'ultimo "
            f"giorno di salute: ha chiesto solo dal {primo_giorno_chiesto}")

    def test_the_health_hole_is_actually_closed(self, connection):
        _attivita(connection, OGGI - timedelta(days=1))
        _salute(connection, OGGI - timedelta(days=40))

        sync.pull(connection, until=OGGI, client=ClientFinto())

        mancanti = connection.execute("""
            SELECT count(*) FROM (
                SELECT unnest(generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY))::DATE AS g
            ) s
            WHERE NOT EXISTS (SELECT 1 FROM daily_health WHERE health_date = s.g)
        """, [OGGI - timedelta(days=40), OGGI]).fetchone()[0]
        assert mancanti == 0, f"restano {mancanti} giorni di salute senza dati"


class TestUnGiornoNonSiScriveAMeta:
    def test_health_is_not_committed_when_sleep_fails(self, connection):
        """Se il sonno del giorno non arriva, il giorno non è fatto.

        Scrivere ``daily_health`` e non ``sleep`` produce un giorno che al
        prossimo passaggio risulta già coperto — e non lo è.
        """
        _attivita(connection, OGGI)
        _salute(connection, OGGI)

        sync.pull(connection, until=OGGI + timedelta(days=1),
                  client=ClientFinto(rompi={"sleep"}))

        a_meta = connection.execute("""
            SELECT count(*) FROM daily_health h
            WHERE h.source_object_id LIKE 'garmin-connect://%'
              AND NOT EXISTS (SELECT 1 FROM sleep s WHERE s.sleep_date = h.health_date)
        """).fetchone()[0]
        assert a_meta == 0, (
            f"{a_meta} giorni hanno la salute scritta e il sonno no: il giorno "
            "è stato confermato a metà")


class TestUnSyncFallitoLoDice:
    def test_a_sync_where_every_day_failed_does_not_report_success(
            self, connection):
        """È il difetto che rende inutili tutti gli altri controlli.

        Se un sync completamente fallito dice «riuscito», l'atleta guarda dati
        vecchi credendoli di oggi — ed è esattamente la situazione che questo
        progetto esiste per impedire.
        """
        _attivita(connection, OGGI - timedelta(days=5))

        report = sync.pull(connection, until=OGGI,
                           client=ClientFinto(rompi={"summary"}))

        assert not report.succeeded, (
            "nessun giorno è stato scaricato e il sync si dichiara riuscito")

    def test_a_partly_failed_sync_is_neither_success_nor_failure(
            self, connection):
        """Metà dei giorni presi e metà no non è «riuscito», e non è «fallito».

        Servono tre esiti, non due: chi legge il log deve poter distinguere
        «tutto a posto» da «ci sono buchi noti» senza contare le righe.
        """
        _attivita(connection, OGGI - timedelta(days=5))

        class MetaRotto(ClientFinto):
            def get_user_summary(self, day):
                self.giorni_visti.append(day)
                if day.endswith(("1", "3", "5", "7", "9")):
                    raise ConnectionError("Garmin non risponde")
                return self._summary

        report = sync.pull(connection, until=OGGI, client=MetaRotto())

        assert hasattr(report, "outcome"), (
            "il report non ha un esito: solo `succeeded`, che è vero o falso e "
            "non sa dire «in parte»")
        assert report.outcome == "partial", (
            f"esito dichiarato: {getattr(report, 'outcome', None)!r}")

    def test_the_failure_is_visible_in_the_printed_summary(self, connection):
        _attivita(connection, OGGI - timedelta(days=5))

        report = sync.pull(connection, until=OGGI,
                           client=ClientFinto(rompi={"summary"}))

        testo = report.summary().lower()
        assert "fallit" in testo or "non riuscit" in testo, (
            f"il riepilogo non dice che è andata male: «{report.summary()}»")
