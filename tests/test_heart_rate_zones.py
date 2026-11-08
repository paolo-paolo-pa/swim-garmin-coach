"""Le zone cardiache: perché non sono affidabili, detto con le prove.

## La differenza che questi test proteggono

«Non calcolabile» e «calcolata e sbagliata» non sono la stessa cosa. La prima
manda ad aspettare, la seconda manda a smettere di usarla. Le zone di questo
atleta sono della seconda specie, e la prova più forte non è fisiologica: è che
l'orologio ne tiene **due definizioni diverse** e non concordano fra loro.

## Cosa difendono

1. Due definizioni che collocano lo stesso battito in zone diverse vengono
   riconosciute come discordi, e il verdetto lo dice con un esempio.
2. Un massimo stimato resta dichiarato tale.
3. Il massimo osservato e quello plausibile restano due numeri diversi: il
   primo contiene gli artefatti della lettura al polso in acqua.
4. **Il verdetto non produce zone corrette.** Correggerle richiederebbe un
   massimo misurato, e questo modulo non lo inventa.
5. Quello che resta utilizzabile viene detto, perché «non affidabili» senza
   un'alternativa è un vicolo cieco.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import heart_rate_zones as hz
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _zone(con, sport, method, massimo, riposo, confini):
    con.execute("""
        INSERT INTO hr_zones (sport, method, max_hr_used, resting_hr_used,
            zone1_floor, zone2_floor, zone3_floor, zone4_floor, zone5_floor,
            source_object_id, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'sha', ?)
    """, [sport, method, massimo, riposo, *confini, datetime(2026, 1, 1)])


def _nuotata(con, activity_id, giorno, max_hr, durata=3600.0):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, max_hr_bpm, avg_hr_bpm,
            source_object_id, imported_at)
        VALUES (?, ?, ?, 'lap_swimming', true, ?, 3000, ?, 140, 'sha', ?)
    """, [activity_id, giorno, datetime(giorno.year, giorno.month, giorno.day, 7),
          durata, max_hr, datetime(2026, 1, 1)])


class TestTwoScalesThatDisagree:
    def test_two_definitions_placing_a_beat_differently_are_in_conflict(
            self, connection):
        _zone(connection, "DEFAULT", "HR_RESERVE", 198, 54,
              (148, 169, 175, 184, 191))
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        elenco = hz.definitions(connection)

        assert hz.disagree(elenco)
        assert hz.zone_of(elenco[0], 136) == 0
        assert hz.zone_of(elenco[1], 136) == 2, (
            "lo stesso battito in due zone diverse: la scala dà due risposte")

    def test_the_verdict_names_the_conflict_first(self, connection):
        _zone(connection, "DEFAULT", "HR_RESERVE", 198, 54,
              (148, 169, 175, 184, 191))
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        quadro = hz.assess(connection)

        assert not quadro.usable
        assert "non concordano" in quadro.reasons[0], (
            "è la prova più forte e non richiede fisiologia: va per prima")

    def test_a_single_definition_is_not_a_conflict(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        assert not hz.disagree(hz.definitions(connection))
        assert not any("non concordano" in una
                       for una in hz.assess(connection).reasons)


class TestTheMaximum:
    def test_an_estimated_maximum_is_declared_as_such(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        motivi = " ".join(hz.assess(connection).reasons)

        assert "220 − età" in motivi and "±12 bpm" in motivi

    def test_the_observed_and_the_plausible_maximum_stay_apart(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))
        for indice, battiti in enumerate([214, 187, 180, 176, 170, 168, 165]):
            _nuotata(connection, indice, date(2026, 1, 1 + indice), battiti)

        assoluto, plausibile, quante = hz.observed_max(connection)

        assert assoluto == 214
        assert plausibile < assoluto, (
            "il massimo assoluto contiene gli artefatti della lettura al polso "
            "in acqua; il 95° percentile no")
        assert quante == 7

    def test_an_implausible_maximum_is_called_an_artefact(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))
        for indice, battiti in enumerate([214, 180, 176, 170]):
            _nuotata(connection, indice, date(2026, 1, 1 + indice), battiti)

        motivi = " ".join(hz.assess(connection).reasons)

        assert "artefatto" in motivi


class TestWhatItRefusesAndWhatItOffers:
    def test_it_never_produces_corrected_zones(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        quadro = hz.assess(connection)

        assert quadro.usable is False, (
            "correggere le zone richiederebbe un massimo misurato: questo "
            "modulo non lo inventa")

    def test_it_says_what_still_works(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        quadro = hz.assess(connection)

        assert quadro.what_still_works, (
            "«non affidabili» senza un'alternativa è un vicolo cieco")
        assert any("parità di passo" in una for una in quadro.what_still_works)

    def test_without_zones_on_the_watch_it_says_only_that(self, connection):
        quadro = hz.assess(connection)

        assert quadro.reasons == [
            "Le zone impostate sull'orologio non sono in archivio."]

    def test_the_page_says_which_test_would_fix_it(self, connection):
        _zone(connection, "SWIMMING", "HR_MAX", 198, 54,
              (99, 119, 139, 158, 178))

        assert "test massimale" in hz.as_page_dict(connection)["what_would_fix_it"]
