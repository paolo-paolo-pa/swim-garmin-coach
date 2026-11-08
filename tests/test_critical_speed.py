"""La velocità critica: il passo di soglia, dalle due prove che l'atleta ha già fatto.

## Perché questi test esistono

Per nove mesi il progetto ha dichiarato la velocità critica «non calcolabile».
Era vero quando `coach/riferimenti.md` era l'unica sorgente di tempi ed era
vuoto. Ha smesso di essere vero il giorno in cui è entrato lo storico della
federazione, e nessuno se n'è accorto per nove giorni perché il codice guardava
il file dell'atleta invece dell'archivio.

Il primo test di questo file è quello che avrebbe fatto suonare l'allarme.

## Cosa difendono

1. **Due prove che esistono producono un numero.** Il blocco non sopravvive ai
   dati.
2. **Due prove lontane non lo producono.** La velocità critica descrive uno
   stato, e un 400 di quest'anno con un 200 di otto anni fa misura la distanza
   fra due epoche.
3. **Il mare non entra.** Una pendenza costruita su due distanze dichiarate
   dagli organizzatori misura la loro fantasia.
4. **Le gare in mezzo si contano.** Il 24/05/2026 fra il 200 e il 400 c'è stato
   un 100: il valore che ne esce è prudente e il codice lo dice da sé.
5. **Una coppia impossibile non produce un numero prudente: non ne produce.**
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import critical_speed as cs
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _gara(con, race_id, giorno, distanza, tempo, vasca=25, stile="stile",
          ambiente="piscina", origine="certified_pool"):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, relay_legs, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source)
        VALUES (?, ?, 'Meet', 'stile libero', ?, ?, false, NULL, ?, ?, 'valid',
                'A', 'sha', ?, ?, ?)
    """, [race_id, giorno, distanza, stile, vasca, tempo,
          datetime(2026, 1, 1), ambiente, origine])


class TestTheBlockFallsWhenTheDataArrives:
    def test_a_four_hundred_and_a_two_hundred_produce_a_pace(self, connection):
        # I due tempi veri del 24/05/2026, in vasca da 25.
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76)

        coppia = cs.current(connection)

        assert coppia is not None, (
            "le due prove che il protocollo chiede esistono: dichiarare la "
            "velocità critica «non calcolabile» sarebbe un blocco scaduto")
        # CSS = 200 / (275,34 − 128,76) = 1,3644 m/s → 73,29 s/100 m
        assert coppia.speed_ms == pytest.approx(1.3644, abs=0.0001)
        assert coppia.pace_100_s == pytest.approx(73.29, abs=0.01)

    def test_the_pace_is_half_the_difference(self, connection):
        # Con 200 metri di differenza fra le due prove la formula generale si
        # semplifica. Il test lo verifica per non fidarsi della semplificazione.
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76)

        coppia = cs.current(connection)

        assert coppia.pace_100_s == pytest.approx((275.34 - 128.76) / 2, abs=0.001)

    def test_no_races_means_a_reason_and_not_a_number(self, connection):
        assert cs.current(connection) is None
        assert "nessun 400" in cs.why_unavailable(connection)


class TestWhatIsNotAllowedToPair:
    def test_two_distant_efforts_do_not_pair(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2019, 1, 27), 200, 125.26)

        assert cs.current(connection) is None, (
            "un 400 del 2026 e un 200 del 2019 non descrivono la stessa "
            "persona nello stesso stato")
        assert "nessuna coppia" in cs.why_unavailable(connection)

    def test_two_pools_do_not_pair(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34, vasca=25)
        _gara(connection, "200", date(2026, 5, 25), 200, 128.76, vasca=50)

        assert cs.current(connection) is None, (
            "su un 400 le virate in più valgono secondi: la pendenza fra due "
            "vasche diverse non è una pendenza")

    def test_the_sea_does_not_enter(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76,
              ambiente="acque libere", origine="event_field", stile=None)

        assert cs.current(connection) is None

    def test_another_stroke_does_not_enter(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 159.36, stile="misti")

        assert cs.current(connection) is None

    def test_an_impossible_pair_produces_nothing(self, connection):
        # Un 400 più veloce del 200: la pendenza sarebbe negativa. Non esiste
        # una velocità critica prudente da estrarne.
        _gara(connection, "400", date(2026, 5, 24), 400, 120.0)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76)

        assert cs.current(connection) is None


class TestWhatTheNumberCarriesWithIt:
    def test_the_nearest_effort_wins_not_the_fastest(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200-vicino", date(2026, 5, 24), 200, 128.76)
        _gara(connection, "200-veloce", date(2026, 5, 10), 200, 125.00)

        coppia = cs.current(connection)

        assert coppia.short_time_s == pytest.approx(128.76), (
            "prendere il miglior 200 disponibile insieme a un 400 recente "
            "misurerebbe due momenti diversi")

    def test_races_in_between_are_counted(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76)
        _gara(connection, "100", date(2026, 5, 24), 100, 58.96)

        coppia = cs.current(connection)

        assert coppia.races_between == 1, (
            "il 400 è stato nuotato su gambe già usate: il valore è prudente "
            "e questo conteggio è il modo in cui il codice se ne accorge")

    def test_a_clean_pair_declares_nothing_in_between(self, connection):
        _gara(connection, "400", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200", date(2026, 5, 24), 200, 128.76)

        assert cs.current(connection).races_between == 0

    def test_every_usable_pair_is_listed_newest_first(self, connection):
        _gara(connection, "400a", date(2026, 5, 24), 400, 275.34)
        _gara(connection, "200a", date(2026, 5, 24), 200, 128.76)
        _gara(connection, "400b", date(2016, 11, 13), 400, 284.30)
        _gara(connection, "200b", date(2016, 11, 27), 200, 129.50)

        coppie = cs.pairs(connection)

        assert [una.day for una in coppie] == [date(2026, 5, 24),
                                               date(2016, 11, 27)]
