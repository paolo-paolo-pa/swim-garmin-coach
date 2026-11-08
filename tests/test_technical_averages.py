"""Una media di medie giornaliere non è la media, e non lo dice.

## I due difetti, misurati sull'archivio vero

**Media di medie.** ``daily_status`` calcola ``avg(avg_swolf)`` per giorno e poi
la media di quei valori sui 28 giorni. Un giorno da 800 m pesa quanto uno da
5 km. Sui 25 giorni dell'archivio con più di una seduta in vasca da 25 m, lo
scarto medio fra la media semplice e quella pesata sui metri è **0,69 SWOLF**,
con un massimo di **2,35**.

**Dispositivi mescolati, ed è il problema più grande.** Su questo archivio ci
sono fino a **quattro dispositivi nello stesso anno** (2024), e il loro SWOLF
medio a parità di vasca va da **28,9 a 30,7**: uno scarto di **1,8**, più del
doppio dell'errore di media-di-medie. È dell'ordine di grandezza di un vero
cambiamento tecnico, e cade a metà stagione — l'orologio del 2017-2024 lascia
il posto a un altro il 7 giugno 2024, e a un terzo il 19 agosto.

CLAUDE.md lo dice da sempre: *«ogni confronto nel tempo di SWOLF, DPS o FC deve
controllare device_id, anche dentro la stessa stagione»*. La regola c'era e
nessuna riga la applicava.

## Cosa questo modulo non può risolvere

Lo **stile**. ``avg_swolf`` è un valore per attività e lo stile sta nei lap: a
livello di riepilogo una seduta mista e una seduta tutta a stile libero hanno la
stessa forma. Non si corregge qui, si dichiara — e la dichiarazione va dove
qualcuno la leggerà, cioè nella scheda della metrica.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

GIORNO = date(2026, 8, 10)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _seduta(con, activity_id, giorno, distanza, swolf, ora=7, device=1):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, environment, distance_m, duration_s, pool_length_m, "
        " avg_swolf, device_id, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', ?, 3600, 25, ?, ?, "
        " 'sha', ?)",
        [activity_id, datetime.combine(giorno, datetime.min.time()).replace(hour=ora),
         giorno, distanza, swolf, device, datetime(2026, 1, 1)])


class TestLaMediaSiPesaSuiMetri:
    def test_a_short_session_does_not_weigh_as_much_as_a_long_one(
            self, connection):
        """500 m a SWOLF 40 e 4.500 m a SWOLF 30.

        La media semplice dice 35, che non descrive nessuna delle due e
        soprattutto non descrive la giornata: il 90% dei metri è stato nuotato
        a 30.
        """
        _seduta(connection, 1, GIORNO, 500, 40, ora=7)
        _seduta(connection, 2, GIORNO, 4500, 30, ora=19)
        daily_status.build(connection)

        valore = connection.execute(
            "SELECT swolf_28d_pool25 FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0]
        assert valore == pytest.approx(31.0, abs=0.1), (
            f"la media a 28 giorni vale {valore}: è la media delle due sedute, "
            "non la media dei metri nuotati")

    def test_the_window_weighs_the_days_by_their_metres_too(self, connection):
        """Lo stesso errore si ripete al livello sopra: una settimana da 2 km e
        una da 20 pesano uguale nella finestra a 28 giorni."""
        _seduta(connection, 1, date(2026, 7, 20), 1000, 40)
        _seduta(connection, 2, GIORNO, 9000, 30)
        daily_status.build(connection)

        valore = connection.execute(
            "SELECT swolf_28d_pool25 FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0]
        assert valore == pytest.approx(31.0, abs=0.1), (
            f"la finestra vale {valore}: media dei giorni invece che dei metri")

    def test_a_session_without_swolf_does_not_drag_the_average_down(
            self, connection):
        """I metri senza SWOLF non entrano nel denominatore.

        Se entrassero, una seduta in cui l'orologio non ha misurato lo SWOLF
        abbasserebbe la media come se fosse stata nuotata a zero.
        """
        _seduta(connection, 1, GIORNO, 1000, 30, ora=7)
        _seduta(connection, 2, GIORNO, 9000, None, ora=19)
        daily_status.build(connection)

        valore = connection.execute(
            "SELECT swolf_28d_pool25 FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0]
        assert valore == pytest.approx(30.0, abs=0.1)


class TestUnaMediaAttraversoDueOrologiLoDice:
    def test_the_window_declares_how_many_devices_it_mixed(self, connection):
        """CLAUDE.md lo chiede da sempre, e nessuna riga lo applicava.

        Su questo archivio due orologi diversi danno 28,9 e 30,7 di SWOLF medio
        a parità di vasca: 1,8 di scarto, che è dell'ordine di grandezza di un
        vero cambiamento tecnico.
        """
        _seduta(connection, 1, date(2026, 8, 1), 3000, 30, device=111)
        _seduta(connection, 2, GIORNO, 3000, 32, device=222)
        daily_status.build(connection)

        quanti = connection.execute(
            "SELECT technique_devices_28d FROM daily_status "
            "WHERE status_date = ?", [GIORNO]).fetchone()[0]
        assert quanti == 2, (
            f"la finestra dichiara {quanti} dispositivi: la media attraversa "
            "due orologi e non lo dice")

    def test_a_single_device_window_says_one(self, connection):
        _seduta(connection, 1, date(2026, 8, 1), 3000, 30, device=111)
        _seduta(connection, 2, GIORNO, 3000, 32, device=111)
        daily_status.build(connection)

        assert connection.execute(
            "SELECT technique_devices_28d FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0] == 1

    def test_a_day_with_no_technique_data_declares_zero_devices(self, connection):
        """Zero e non NULL: nessun dispositivo ha contribuito, ed è un fatto."""
        _seduta(connection, 1, GIORNO, 3000, None, device=111)
        daily_status.build(connection)

        assert connection.execute(
            "SELECT technique_devices_28d FROM daily_status WHERE status_date = ?",
            [GIORNO]).fetchone()[0] == 0


class TestIlLimiteSulloStileEDichiarato:
    def test_the_catalog_says_swolf_does_not_separate_strokes(self):
        """Quello che non si può correggere si dichiara dove verrà letto.

        ``avg_swolf`` è un valore per attività e lo stile sta nei lap: a livello
        di riepilogo una seduta mista e una tutta a stile libero hanno la stessa
        forma. Tacerlo renderebbe confrontabili due numeri che non lo sono.
        """
        from garmin_coach.metrics.catalog import BY_COLUMN

        for colonna in ("swolf_28d_pool25", "swolf_28d_pool50"):
            avvertenza = BY_COLUMN[colonna].caveat.lower()
            assert "stile" in avvertenza, (
                f"«{colonna}» non dichiara di mescolare gli stili")

    def test_the_catalog_says_it_may_cross_devices(self):
        from garmin_coach.metrics.catalog import BY_COLUMN

        for colonna in ("swolf_28d_pool25", "dps_28d_pool25"):
            avvertenza = BY_COLUMN[colonna].caveat.lower()
            assert "dispositiv" in avvertenza or "orolog" in avvertenza, (
                f"«{colonna}» non dichiara che può attraversare due orologi")
