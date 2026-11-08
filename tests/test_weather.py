"""Le condizioni di una nuotata in mare, e cosa esce dal computer per averle.

## Cosa difendono

1. **Le direzioni si mediano come vettori, non come numeri.** Fra 350° e 10° la
   media aritmetica dà 180 — cioè esattamente la direzione opposta a quella
   vera. È l'errore che rovinerebbe in silenzio ogni confronto sul vento.
2. **Un buco non diventa uno zero.** Sui laghi il modello marino non risponde,
   e «non lo copre» non è «zero gradi».
3. **La finestra è quella della nuotata**, non la giornata: una gara alle otto
   e il pomeriggio dello stesso giorno possono avere venti opposti.
4. **Si chiede una volta sola.** Ogni riga costa una richiesta a un servizio di
   terzi che risponde gratis.
5. **La posizione che esce è arrotondata a ~11 km.** È il perimetro che
   l'atleta ha autorizzato, ed è anche la risoluzione a cui i modelli lavorano.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import race_history as rh
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import track, weather


class TestAveragingDirections:
    def test_two_directions_across_north_average_to_north(self):
        # 350 e 10 fanno 0, non 180. La media aritmetica darebbe la direzione
        # opposta, e nessuno se ne accorgerebbe guardando un numero solo.
        assert weather._circular_mean([350.0, 10.0]) == pytest.approx(0.0, abs=0.5)

    def test_a_plain_average_would_have_been_wrong(self):
        vettoriale = weather._circular_mean([350.0, 10.0])
        aritmetica = sum([350.0, 10.0]) / 2

        assert abs(vettoriale - aritmetica) > 90, (
            "e' il caso che giustifica la funzione: 180 gradi di errore")

    def test_directions_that_do_not_cross_north_still_work(self):
        assert weather._circular_mean([80.0, 100.0]) == pytest.approx(90.0, abs=0.5)

    def test_missing_directions_are_skipped_not_counted_as_zero(self):
        assert weather._circular_mean([None, 90.0, None]) == pytest.approx(90.0, abs=0.5)

    def test_nothing_at_all_gives_nothing(self):
        assert weather._circular_mean([None, None]) is None
        assert weather._circular_mean([]) is None


class TestAveragingValues:
    def test_a_hole_is_skipped_not_zeroed(self):
        assert weather._mean([20.0, None, 22.0]) == pytest.approx(21.0)

    def test_all_holes_give_nothing(self):
        # Sui laghi il modello marino non risponde: «non lo copre» non e'
        # «zero gradi».
        assert weather._mean([None, None]) is None


class TestTheWindow:
    def test_a_short_swim_covers_its_own_hour(self):
        inizio = datetime(2024, 5, 26, 8, 30)

        assert weather._hours_of(inizio, 1800) == (8, 8)

    def test_a_long_swim_covers_every_hour_it_crossed(self):
        # place19-place28: dieci ore. La media della giornata descriverebbe una
        # giornata che nessuno ha nuotato.
        inizio = datetime(2018, 6, 29, 7, 0)

        assert weather._hours_of(inizio, 10 * 3600) == (7, 17)

    def test_a_swim_never_runs_past_midnight_of_its_own_day(self):
        inizio = datetime(2024, 5, 26, 22, 0)

        da, a = weather._hours_of(inizio, 6 * 3600)

        assert a == 23, "l'archivio di quel giorno finisce alle 23"

    def test_the_window_picks_only_its_hours(self):
        hourly = {"temperature_2m": list(range(24))}

        assert weather._window(hourly, "temperature_2m", 8, 10) == [8, 9, 10]

    def test_a_field_the_model_does_not_have_gives_an_empty_window(self):
        assert weather._window({}, "wave_height", 8, 10) == []


class TestWhatLeavesTheComputer:
    def test_the_position_is_rounded_to_about_eleven_kilometres(self):
        # Un decimo di grado. Dice in quale tratto di costa si nuotava, non da
        # quale spiaggia si e' partiti.
        assert track.POSITION_DECIMALS == 1

    def test_the_track_keeps_only_the_rounded_start(self):
        gradi = 2 ** 31 / 180
        punti = [{"timestamp": datetime(2026, 6, 1, 8, 0, 0),
                  "distance": 0.0,
                  "position_lat": 44.0123456 * gradi,
                  "position_long": 12.7987654 * gradi}]

        _, misure = track._rows(1, punti, "sha", datetime(2026, 1, 1))

        assert misure["start_lat_rounded"] == pytest.approx(44.0)
        assert misure["start_lon_rounded"] == pytest.approx(12.8)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _nuotata_con_posizione(con, activity_id, giorno, metri=10000):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, pool_length_m,
            source_object_id, imported_at)
        VALUES (?, ?, ?, 'open_water_swimming', true, 9000, ?, NULL, 'sha', ?)
    """, [activity_id, giorno, datetime(giorno.year, giorno.month, giorno.day, 8),
          metri, datetime(2026, 1, 1)])
    con.execute("""
        INSERT INTO activity_track_quality (activity_id, points, gps_points,
            has_heart_rate, segments_ok, source_object_id, imported_at,
            start_lat_rounded, start_lon_rounded)
        VALUES (?, 200, 200, true, true, 'sha', ?, 44.0, 12.8)
    """, [activity_id, datetime(2026, 1, 1)])


class TestAskingOnlyOnce:
    def test_a_swim_with_a_position_is_a_candidate(self, connection):
        _nuotata_con_posizione(connection, 1, date(2024, 5, 26))

        assert [riga[0] for riga in weather.candidates(connection)] == [1]

    def test_a_swim_already_fetched_is_never_asked_again(self, connection):
        _nuotata_con_posizione(connection, 1, date(2024, 5, 26))
        connection.execute("""
            INSERT INTO race_conditions (activity_id, observed_date,
                hours_covered, model, source_object_id, imported_at)
            VALUES (1, DATE '2024-05-26', 3, 'open-meteo', 'sha', ?)
        """, [datetime(2026, 1, 1)])

        assert weather.candidates(connection) == [], (
            "ogni riga costa una richiesta a un servizio che risponde gratis")

    def test_a_short_swim_is_a_candidate_too(self, connection):
        # Deciso il 24/08/2026: «prendi tutti i dati meteo che hai a
        # disposizione». Un'uscita corta serve da confronto per le gare
        # lunghe, ed escluderla toglieva proprio i termini di paragone.
        _nuotata_con_posizione(connection, 1, date(2024, 5, 26), metri=1200)

        assert [riga[0] for riga in weather.candidates(connection)] == [1]

    def test_a_swim_without_a_position_cannot_be_asked_about(self, connection):
        _nuotata_con_posizione(connection, 1, date(2024, 5, 26))
        connection.execute(
            "UPDATE activity_track_quality SET start_lat_rounded = NULL")

        assert weather.candidates(connection) == []


class TestSayingIt:
    def test_degrees_become_a_direction_a_swimmer_remembers(self):
        assert rh.compass_of(0) == "nord"
        assert rh.compass_of(323) == "nord-ovest"
        assert rh.compass_of(170) == "sud"

    def test_no_direction_no_word(self):
        assert rh.compass_of(None) is None

    def test_a_lake_says_the_wind_and_stays_quiet_on_the_waves(self):
        # Il modello marino non copre i laghi. Si tace su acqua e onda invece
        # di scrivere «non disponibile» due volte.
        frase = rh.conditions_display({
            "air_c": 25.1, "water_c": None,
            "wind_kmh": 4.3, "wind_from_deg": 148.0, "wave_m": None})

        assert "aria 25 °C" in frase
        assert "vento" in frase and "sud-est" in frase
        assert "acqua" not in frase and "onda" not in frase

    def test_the_sea_says_everything(self):
        frase = rh.conditions_display({
            "air_c": 22.3, "water_c": 20.8,
            "wind_kmh": 11.8, "wind_from_deg": 339.0, "wave_m": 0.26})

        assert "acqua 21 °C" in frase
        assert "onda 0,26 m" in frase, "i decimali si scrivono con la virgola"

    def test_no_conditions_no_sentence(self):
        assert rh.conditions_display(None) == ""
        assert rh.conditions_display({}) == ""
