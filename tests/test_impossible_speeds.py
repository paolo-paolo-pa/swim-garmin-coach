"""Una velocita' massima di 100 m/s non e' una velocita'.

## Cosa c'e' nell'archivio

`max_speed_ms` arriva a **100,33 m/s** sul 6 km di place03 del 26/08/2023, e a
45,36 sul 30/07/2023. Sono 361 e 163 km/h. Il record mondiale sui 50 stile
corrisponde a 2,39 m/s di media, e il p90 di questo atleta e' 2,14.

Quaranta attivita' su 1.293 portano un valore sopra i 3 m/s: sono picchi del
GPS, non nuotate.

## Cosa sparisce e cosa resta

Sparisce il campo, non la seduta: place03 2023 e' 6.000 m a 1:26,7, una
prestazione vera e citata fra i riferimenti dell'atleta. Il picco non la tocca.

E resta il file di origine. Il valore che non si riscrive mai sta in
`garmin-export/`, dove il fatto che Garmin lo abbia registrato e' conservato per
sempre. La colonna del database e' derivata, e una colonna che si chiama
"velocita' massima" non deve contenere un artefatto del GPS: e' la stessa scelta
che il progetto fa gia' con gli zeri di Garmin.

## Perche' anche un criterio

Il rimedio vale dal prossimo import. Le quarantuno attivita' gia' in archivio
restano finche' non si rilancia `all`, e un criterio che le conta e' il modo di
non dimenticarsene.
"""

import duckdb
import pytest

from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status
from garmin_coach.verification import MAX_HUMAN_SWIM_SPEED_MS, run_checks

from datetime import date, datetime


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _nuotata(con, activity_id, velocita_massima):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, environment, distance_m, duration_s, max_speed_ms, "
        " source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'open_water_swimming', TRUE, 'open_water', 6000, "
        " 5200, ?, 'sha', ?)",
        [activity_id, datetime(2023, 8, 26, 8), date(2023, 8, 26),
         velocita_massima, datetime(2026, 1, 1)])


def _criterio(connection):
    daily_status.build(connection)
    return next(c for c in run_checks(connection) if c.identifier == "C12")


class TestUnaVelocitaImpossibileEContata:
    def test_a_gps_spike_is_reported(self, connection):
        _nuotata(connection, 1, 100.33)

        criterio = _criterio(connection)
        assert not criterio.passed
        assert criterio.actual == 1

    def test_a_real_swim_speed_is_not(self, connection):
        """Il divieto e' mirato: 2,1 m/s e' veloce e possibile."""
        _nuotata(connection, 1, 2.1)

        assert _criterio(connection).passed

    def test_the_threshold_is_above_the_world_record(self):
        """Il record mondiale sui 50 stile e' 20,91 s, cioe' 2,39 m/s di media,
        e la velocita' di picco dentro quella vasca e' piu' alta. La soglia sta
        sopra, perche' deve segnalare gli artefatti e non i nuotatori."""
        assert MAX_HUMAN_SWIM_SPEED_MS > 2.39

    def test_the_activity_itself_is_not_excluded(self, connection):
        """place03 2023 e' 6.000 m a 1:26,7, una prestazione vera. Il difetto sta
        nel campo, non nella seduta."""
        _nuotata(connection, 1, 100.33)
        daily_status.build(connection)

        assert connection.execute(
            "SELECT count(*) FROM canonical_activities WHERE activity_id = 1"
        ).fetchone()[0] == 1

    def test_the_criterion_reads_what_is_in_the_database_today(self, connection):
        """Il criterio guarda `activities`, non il file di origine.

        Il valore che non si tocca mai sta in `garmin-export/`, ed e' li' che
        resta il fatto che Garmin lo ha registrato. La colonna del database e'
        derivata, e una colonna che si chiama "velocita' massima" non deve
        contenere un artefatto del GPS.
        """
        _nuotata(connection, 1, 100.33)

        assert _criterio(connection).actual == 1


class TestNonNeEntranoDiNuove:
    """Il rimedio: il valore impossibile non entra al prossimo import.

    E' la stessa scelta che il progetto fa gia' altrove - gli zeri di Garmin non
    diventano zeri, e il sync si ferma davanti a un valore che nessuna scala
    nota spiega. Un artefatto scritto in una colonna che si chiama "velocita'
    massima" e' un dato falso travestito da misura.
    """

    def test_an_impossible_peak_does_not_enter_the_database(self):
        from garmin_coach.ingest.summaries import _human_speed

        assert _human_speed(100.33, is_swim=True) is None

    def test_a_possible_one_does(self):
        from garmin_coach.ingest.summaries import _human_speed

        assert _human_speed(2.1, is_swim=True) == pytest.approx(2.1)

    def test_the_limit_applies_only_to_swimming(self):
        """In bicicletta 10 m/s sono trentasei all'ora, cioe' niente di strano.

        Il limite e' quello del nuoto, e applicarlo a tutto trasformerebbe una
        correzione in un danno.
        """
        from garmin_coach.ingest.summaries import _human_speed

        assert _human_speed(10.0, is_swim=False) == pytest.approx(10.0)
