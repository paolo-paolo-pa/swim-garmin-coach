"""«Come è andato il mio 100 stile negli anni?»

## Perché la progressione non è il record

Il record dice il giorno migliore di sempre: il 25"97 del 2018 non racconta
niente del 2026. La progressione mette in fila le stagioni e lascia vedere la
direzione — che su questo atleta è una direzione vera e scomoda, perché sui 50
e sui 100 stile è in calo mentre il fondo tiene.

## Cosa questi test difendono

1. **La stagione del nuoto comincia a settembre.** Il Christmas Swim di dicembre
   e il Regionale di febbraio sono lo stesso inverno di lavoro: spezzarli
   sull'anno solare separerebbe due gare della stessa preparazione.
2. **Dentro una stagione conta il migliore, non la media.** Una stagione con
   quattro gare e una con una sola non hanno medie confrontabili.
3. **Due punti in una stagione sola non sono una direzione.**
4. **Una stagione saltata si dichiara.** «Meglio dell'anno scorso» quando
   l'anno scorso non hai gareggiato è una frase falsa.
5. **La progressione dice quando finisce.** «Nel 2017/18 sei uguale al 2016/17»
   si legge come una notizia di adesso, e sono otto anni fa.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import race_history as rh
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _gara(con, race_id, giorno, distanza, tempo, stile="stile", vasca=25):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, relay_legs, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source)
        VALUES (?, ?, 'Meet', 'stile libero', ?, ?, false, NULL, ?, ?, 'valid',
                'A', 'sha', ?, 'piscina', 'certified_pool')
    """, [race_id, giorno, distanza, stile, vasca, tempo, datetime(2026, 1, 1)])


class TestTheSwimmingSeason:
    @pytest.mark.parametrize("giorno, etichetta", [
        (date(2025, 12, 14), "2025/26"),
        (date(2026, 2, 15), "2025/26"),
        (date(2026, 8, 31), "2025/26"),
        (date(2026, 9, 1), "2026/27"),
    ])
    def test_september_opens_and_august_closes(self, giorno, etichetta):
        assert rh.season_of(giorno)[1] == etichetta

    def test_december_and_february_are_the_same_winter(self):
        assert (rh.season_of(date(2025, 12, 14))
                == rh.season_of(date(2026, 2, 15))), (
            "il Christmas Swim e il Regionale sono la stessa preparazione: "
            "l'anno solare li separerebbe")


class TestWhatCountsAsAProgression:
    def test_one_season_is_not_a_direction(self, connection):
        _gara(connection, "a", date(2026, 1, 10), 100, 58.0)
        _gara(connection, "b", date(2026, 2, 10), 100, 57.5)
        _gara(connection, "c", date(2026, 3, 10), 100, 57.9)

        assert rh.progressions(connection) == [], (
            "tre gare in una stagione sola non descrivono una direzione")

    def test_too_few_races_are_an_anecdote(self, connection):
        _gara(connection, "a", date(2025, 1, 10), 100, 58.0)
        _gara(connection, "b", date(2026, 1, 10), 100, 57.5)

        assert rh.progressions(connection) == []

    def test_the_best_of_the_season_wins_not_the_average(self, connection):
        _gara(connection, "a", date(2025, 1, 10), 100, 60.0)
        _gara(connection, "b", date(2025, 2, 10), 100, 57.0)
        _gara(connection, "c", date(2026, 1, 10), 100, 58.0)

        stagioni = rh.progressions(connection)[0].seasons

        assert stagioni[0].best_s == pytest.approx(57.0)
        assert stagioni[0].races == 2


class TestTheDirection:
    def _tre_stagioni(self, connection, ultimo):
        _gara(connection, "a", date(2024, 1, 10), 100, 60.0)
        _gara(connection, "b", date(2025, 1, 10), 100, 59.0)
        _gara(connection, "c", date(2026, 1, 10), 100, ultimo)
        return rh.progressions(connection)[0]

    def test_faster_is_improved(self, connection):
        assert self._tre_stagioni(connection, 57.0).verdict == "migliorata"

    def test_slower_is_worsened(self, connection):
        assert self._tre_stagioni(connection, 61.0).verdict == "peggiorata"

    def test_the_same_time_twice_is_stable(self, connection):
        # 59,10 su 59,00 è lo 0,17%: sotto la soglia di rumore, non è un
        # peggioramento ed etichettarlo come tale insegna a non leggere.
        assert self._tre_stagioni(connection, 59.10).verdict == "stabile"

    def test_the_gap_to_the_record_is_not_the_gap_to_last_year(self, connection):
        progressione = self._tre_stagioni(connection, 61.0)

        assert progressione.delta_s == pytest.approx(2.0)
        assert progressione.gap_to_best_s == pytest.approx(2.0)
        assert progressione.best.best_s == pytest.approx(59.0)


class TestWhatTheSentenceSays:
    def test_a_skipped_season_is_declared(self, connection):
        _gara(connection, "a", date(2022, 1, 10), 50, 26.53)
        _gara(connection, "b", date(2023, 1, 10), 50, 26.53)
        _gara(connection, "c", date(2026, 1, 10), 50, 27.29)

        frase = rh._progression_summary(rh.progressions(connection)[0])

        assert "saltate" in frase, (
            "«più lento dell'anno scorso» quando l'anno scorso non hai "
            "gareggiato è una frase falsa")

    def test_the_sentence_says_when_it_ends(self, connection):
        _gara(connection, "a", date(2017, 1, 10), 100, 58.0)
        _gara(connection, "b", date(2018, 1, 10), 100, 57.36)
        _gara(connection, "c", date(2018, 5, 13), 100, 57.50)

        frase = rh._progression_summary(rh.progressions(connection)[0])

        assert "13/05/2018" in frase, (
            "una progressione che non dice quando finisce descrive un atleta "
            "che non esiste più")

    def test_the_sea_never_gets_a_progression(self, connection):
        for anno in (2024, 2025, 2026):
            connection.execute("""
                INSERT INTO races (race_id, race_date, meet, event_label,
                    distance_m, stroke, is_relay, relay_legs, pool_length_m,
                    time_s, status, timing, source_object_id, imported_at,
                    environment, distance_source)
                VALUES (?, ?, 'Mare', 'prova', 3000, NULL, false, NULL, NULL,
                        2700, 'valid', NULL, 'sha', ?, 'acque libere',
                        'event_field')
            """, [f"mare-{anno}", date(anno, 6, 1), datetime(2026, 1, 1)])

        assert rh.progressions(connection) == [], (
            "tre percorsi diversi chiamati tutti 3.000 non sono la stessa "
            "distanza nuotata tre volte")
