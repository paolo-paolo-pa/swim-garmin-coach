"""Cinque registrazioni in un giorno non sono cinque sedute.

## Cosa succede davvero

L'orologio si ferma e riparte: una chiamata, un cambio di vasca, un tasto
premuto per sbaglio. Il risultato è che una sola nuotata arriva nel database
come due o tre attività separate.

Misurato sull'archivio vero: fino a **sei** registrazioni di nuoto nello stesso
giorno — il 05/09/2017 sei per 825 m in totale, il 15/08/2026 cinque per
2.551 m. Su 86 intervalli fra registrazioni consecutive dello stesso giorno,
**undici sono sotto il minuto** e ventitré sotto i tre minuti.

Il 15/08/2026, guardato da vicino: 19:23 per 102 secondi, poi 19:28 per 606.
Fra la fine della prima e l'inizio della seconda passano due minuti. Non sono
due allenamenti.

## Perché conta

Ogni conteggio «sedute» le tratta come distinte. La frequenza settimanale — che
è uno dei pochi numeri su cui un coach decide davvero — risulta gonfiata, e
risulta gonfiata proprio nei giorni in cui l'orologio ha dato problemi, cioè in
modo non casuale.

## La soglia, e perché quella

Tre minuti. Non è statistica: è il tempo minimo per uscire dall'acqua, fare
un'altra cosa e rientrare. Sotto, è un orologio fermato e riacceso.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import volume
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

GIORNO = date(2026, 8, 15)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _registrazione(con, activity_id, inizio: datetime, durata: int,
                   distanza: float):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        " activity_date, sport, is_swim, environment, distance_m, duration_s, "
        " pool_length_m, device_id, source_object_id, imported_at) "
        "VALUES (?, ?, ?, ?, 'lap_swimming', TRUE, 'pool', ?, ?, 25, 1, 'sha', ?)",
        [activity_id, inizio, inizio, inizio.date(), distanza, durata,
         datetime(2026, 1, 1)])


class TestDueFrammentiSonoUnaSeduta:
    def test_two_recordings_two_minutes_apart_count_as_one(self, connection):
        """Il caso vero del 15/08/2026, ridotto all'osso."""
        _registrazione(connection, 1, datetime(2026, 8, 15, 19, 23, 53), 102, 66)
        _registrazione(connection, 2, datetime(2026, 8, 15, 19, 28, 34), 606, 476)

        misura = volume.of_period(connection, GIORNO, GIORNO)

        assert misura.sessions == 1, (
            f"contate {misura.sessions} sedute: sono due frammenti separati da "
            "due minuti")

    def test_the_metres_of_both_fragments_are_still_counted(self, connection):
        """Unire le sedute non deve perdere i metri: il volume è la somma."""
        _registrazione(connection, 1, datetime(2026, 8, 15, 19, 23, 53), 102, 66)
        _registrazione(connection, 2, datetime(2026, 8, 15, 19, 28, 34), 606, 476)

        misura = volume.of_period(connection, GIORNO, GIORNO)

        # Il servizio arrotonda i chilometri a due decimali, ed è una scelta
        # sua di vecchia data: 542 m diventano 0,54 km.
        assert misura.distance_km == pytest.approx(0.54, abs=0.005)

    def test_two_real_sessions_in_a_day_stay_two(self, connection):
        """Il divieto è mirato. Doppia seduta mattina e sera è una cosa vera e
        frequente, e unirla sarebbe l'errore opposto — più difficile da vedere,
        perché toglie invece di aggiungere."""
        _registrazione(connection, 1, datetime(2026, 8, 15, 7, 0), 3600, 3000)
        _registrazione(connection, 2, datetime(2026, 8, 15, 19, 0), 3600, 3000)

        assert volume.of_period(connection, GIORNO, GIORNO).sessions == 2

    def test_a_gap_just_over_the_threshold_keeps_them_apart(self, connection):
        """La soglia si prova ai suoi due lati, altrimenti non è una soglia."""
        _registrazione(connection, 1, datetime(2026, 8, 15, 7, 0), 600, 500)
        _registrazione(connection, 2,
                       datetime(2026, 8, 15, 7, 10) + timedelta(seconds=200),
                       600, 500)

        assert volume.of_period(connection, GIORNO, GIORNO).sessions == 2

    def test_three_fragments_in_a_row_are_one_session(self, connection):
        for i, minuto in enumerate((0, 4, 8)):
            _registrazione(connection, i + 1,
                           datetime(2026, 8, 15, 7, minuto), 120, 200)

        assert volume.of_period(connection, GIORNO, GIORNO).sessions == 1

    def test_recordings_on_different_days_are_never_merged(self, connection):
        """Una nuotata a mezzanotte e una alle 00:05 del giorno dopo sono
        contigue nel tempo. Restano due giorni, perché il giorno di calendario
        dell'atleta è l'unità con cui si allena."""
        _registrazione(connection, 1, datetime(2026, 8, 15, 23, 58), 60, 100)
        _registrazione(connection, 2, datetime(2026, 8, 16, 0, 1), 60, 100)

        assert volume.of_period(connection, GIORNO, GIORNO).sessions == 1
        assert volume.of_period(connection, date(2026, 8, 16),
                                date(2026, 8, 16)).sessions == 1


class TestIlGiornoNonContaCinqueSedute:
    def test_daily_status_counts_sessions_not_recordings(self, connection):
        """`swim_sessions_count` alimenta la frequenza settimanale, che è uno
        dei pochi numeri su cui un coach decide davvero."""
        for i, minuto in enumerate((0, 3, 6)):
            _registrazione(connection, i + 1,
                           datetime(2026, 8, 15, 7, minuto), 120, 200)
        daily_status.build(connection)

        quante = connection.execute(
            "SELECT swim_sessions_count FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0]
        assert quante == 1, f"il giorno dichiara {quante} sedute su tre frammenti"

    def test_the_distance_of_the_day_is_unchanged(self, connection):
        for i, minuto in enumerate((0, 3, 6)):
            _registrazione(connection, i + 1,
                           datetime(2026, 8, 15, 7, minuto), 120, 200)
        daily_status.build(connection)

        assert connection.execute(
            "SELECT swim_distance_m FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0] == 600
