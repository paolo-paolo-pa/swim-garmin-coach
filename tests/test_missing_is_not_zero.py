"""Un dato che non c'è non è uno zero. È la Regola Aurea n.5, e si violava.

## Cosa è stato misurato sull'archivio vero

**1.828 giorni pubblicano un ACWR.** Di questi, il minimo di giorni con attività
vera nella finestra a 28 è **1**, la media 12,7, e **98 giorni pubblicano un
ACWR con meno di cinque giorni di allenamento nelle quattro settimane**.

La soglia che doveva impedirlo — `MIN_DAYS_FOR_ACWR = 21` — non protegge da
niente: conta `day_load`, che dentro l'epoca del carico è già stato portato a
zero da un `coalesce`. Quindi conta i giorni **del calendario**, non i giorni
con un dato. Su una finestra interamente dentro l'epoca vale sempre 28.

**Tre giorni dichiarano zero metri nuotati pur avendo una nuotata.** Otto
attività di nuoto hanno `distance_m` a NULL: il `coalesce` le trasforma in
zero, e il giorno dice «hai nuotato zero metri» quando la verità è «non lo so».

## Perché conta più di quanto sembri

Uno zero finto non rompe niente di visibile: entra nelle medie, abbassa la
mediana, sposta la fascia personale, e ogni conclusione costruita sopra sembra
solida. È il modo in cui un archivio onesto produce risposte disoneste.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _nuotata(con, activity_id, giorno, distanza, carico=50.0, ora=7):
    """``ora`` distanzia le nuotate dello stesso giorno.

    Serve da quando le registrazioni contigue si contano come una seduta sola:
    due nuotate allo stesso istante **sono** la stessa seduta, e un test che le
    mettesse insieme misurerebbe il raggruppamento invece della copertura.
    """
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, environment, distance_m, duration_s, "
        " garmin_training_load, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', ?, 3600, ?, 'sha', ?)",
        [activity_id, datetime.combine(giorno, datetime.min.time()).replace(hour=ora),
         giorno, distanza, carico, datetime(2026, 1, 1)])


class TestUnaDistanzaSconosciutaNonEZero:
    def test_a_swim_without_a_distance_does_not_become_zero_metres(
            self, connection):
        """«Hai nuotato zero metri» e «non so quanto hai nuotato» sono due
        risposte diverse, e solo una delle due è vera."""
        _nuotata(connection, 1, date(2026, 8, 10), None)
        daily_status.build(connection)

        valore = connection.execute(
            "SELECT swim_distance_m FROM daily_status WHERE status_date = ?",
            [date(2026, 8, 10)]).fetchone()[0]
        assert valore is None, (
            f"il giorno dichiara {valore} m nuotati e la distanza non si sa")

    def test_a_day_without_any_swim_is_a_real_zero(self, connection):
        """Il divieto è mirato: un giorno di riposo ha nuotato zero metri
        davvero, e trasformarlo in «non lo so» sarebbe l'errore opposto."""
        _nuotata(connection, 1, date(2026, 8, 10), 3000)
        _nuotata(connection, 2, date(2026, 8, 12), 3000)
        daily_status.build(connection)

        valore = connection.execute(
            "SELECT swim_distance_m FROM daily_status WHERE status_date = ?",
            [date(2026, 8, 11)]).fetchone()[0]
        assert valore == 0

    def test_a_partially_known_day_is_not_silently_completed(self, connection):
        """Due nuotate, una senza distanza: il totale del giorno non è la somma
        di quella che si conosce, perché mancherebbe un pezzo senza dirlo."""
        _nuotata(connection, 1, date(2026, 8, 10), 3000, ora=7)
        _nuotata(connection, 2, date(2026, 8, 10), None, ora=19)
        daily_status.build(connection)

        riga = connection.execute(
            "SELECT swim_distance_m, swim_distance_known_n, swim_sessions_count "
            "FROM daily_status WHERE status_date = ?",
            [date(2026, 8, 10)]).fetchone()
        assert riga[1] == 1 and riga[2] == 2, (
            "il giorno non dichiara che una delle due distanze manca")


class TestLAcwrNonSiPubblicaSuQuattroSedute:
    OSSERVAZIONE = date(2026, 8, 20)

    def _un_mese_con(self, connection, giorni_allenati: int):
        """Sedute distribuite **dentro** la finestra a 28 giorni che finisce il
        giorno dell'osservazione. Metterle fuori misurerebbe il fixture."""
        for i in range(giorni_allenati):
            _nuotata(connection, 100 + i,
                     self.OSSERVAZIONE - _giorni(27 - i * 2), 3000)
        # Un'attività anche il giorno stesso: la finestra include oggi.
        _nuotata(connection, 999, self.OSSERVAZIONE, 3000)
        daily_status.build(connection)

    def test_four_training_days_in_four_weeks_do_not_produce_an_acwr(
            self, connection):
        """Il denominatore cronico di quattro sedute in quattro settimane non
        descrive un carico cronico: descrive quattro sedute."""
        self._un_mese_con(connection, 3)

        acwr = connection.execute(
            "SELECT acwr FROM daily_status WHERE status_date = ?",
            [self.OSSERVAZIONE]).fetchone()[0]
        assert acwr is None, (
            f"pubblicato un ACWR di {acwr} su tre giorni di allenamento in "
            "quattro settimane")

    def test_a_real_training_month_still_produces_one(self, connection):
        """Il divieto è mirato: con un carico vero l'ACWR deve continuare a
        esserci, altrimenti la correzione ha spento la metrica."""
        self._un_mese_con(connection, 12)

        acwr = connection.execute(
            "SELECT acwr FROM daily_status WHERE status_date = ?",
            [self.OSSERVAZIONE]).fetchone()[0]
        assert acwr is not None, "l'ACWR è sparito anche dove era legittimo"

    def test_the_window_declares_how_many_days_it_actually_saw(self, connection):
        """`n` e `expected_n` distinti: senza, «21 su 28» e «21 su 21» sono lo
        stesso numero e non sono la stessa cosa."""
        self._un_mese_con(connection, 6)

        riga = connection.execute(
            "SELECT load_training_days_28, load_days_28 FROM daily_status "
            "WHERE status_date = ?", [self.OSSERVAZIONE]).fetchone()
        assert riga[0] is not None and riga[1] is not None
        assert riga[0] < riga[1], (
            "i giorni con allenamento e i giorni osservati coincidono: uno dei "
            "due non sta misurando quello che dice")


def _giorni(n: int):
    from datetime import timedelta
    return timedelta(days=n)
