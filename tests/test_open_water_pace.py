"""Il passo obiettivo in mare: quello che la letteratura dice, e quello che lui fa.

## Il difetto che questi test impediscono

Esiste uno studio che dà la formula: i primi dieci della 10 km ai Mondiali 2023
tengono il 92,3% della propria velocità critica [OW-1]. È pubblicato bene, il
campione è serio, e applicarlo a questo atleta produrrebbe un passo obiettivo
circa un quarto più veloce di qualunque cosa abbia mai tenuto in mare.

Sarebbe un numero con una bibliografia sotto. Sarebbe sbagliato.

## Cosa difendono

1. **La banda della letteratura non produce mai un passo.** Serve a misurare la
   distanza da un professionista, che è un'altra domanda.
2. **Il passo esce solo dalle gare di questo atleta**, e solo quando la velocità
   critica con cui si confrontano è abbastanza vicina nel tempo.
3. **Una gara del 2019 divisa per una velocità critica del 2016 non misura il
   mare, misura tre anni.**
4. **Una distanza dichiarata che non regge non entra**: la quota sarebbe
   calcolata su un numeratore falso.
5. **Quando manca, «non lo so» dice anche quale prova lo sbloccherebbe.**
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import open_water_pace as owp
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _vasca(con, race_id, giorno, distanza, tempo):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source)
        VALUES (?, ?, 'Meet', 'stile libero', ?, 'stile', false, 25, ?, 'valid',
                'A', 'sha', ?, 'piscina', 'certified_pool')
    """, [race_id, giorno, distanza, tempo, datetime(2026, 1, 1)])


def _mare(con, race_id, giorno, distanza, tempo, meet="Gara"):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source)
        VALUES (?, ?, ?, 'prova', ?, NULL, false, NULL, ?, 'valid', NULL,
                'sha', ?, 'acque libere', 'event_field')
    """, [race_id, giorno, meet, distanza, tempo, datetime(2026, 1, 1)])


def _soglia(con, giorno=date(2026, 5, 24)):
    """Una coppia 400/200 che dà una velocità critica di 1,3644 m/s."""
    _vasca(con, "400", giorno, 400, 275.34)
    _vasca(con, "200", giorno, 200, 128.76)
    # Il metro con cui si giudica la credibilità delle distanze in mare.
    _vasca(con, "100", date(2018, 3, 11), 100, 55.32)
    _vasca(con, "1500", date(2026, 2, 15), 1500, 1139.55)


class TestTheLiteratureNeverBecomesATarget:
    def test_without_his_own_races_there_is_no_target(self, connection):
        _soglia(connection)

        assert owp.target_pace(connection, 10000) is None, (
            "la banda d'élite non produce un passo: se bastasse quella, "
            "questo modulo sarebbe una moltiplicazione")

    def test_the_literature_band_is_still_reported(self, connection):
        _soglia(connection)

        quadro = owp.summary(connection, 10000)

        assert quadro["literature_band_pct"] == (90, 93)
        assert "Mondiali" in quadro["literature_source"], (
            "la banda si mostra sempre, etichettata: la distanza fra lui e un "
            "professionista è essa stessa un'informazione")


class TestOnlyHisOwnRacesCount:
    def test_three_close_races_produce_a_band(self, connection):
        _soglia(connection)
        for indice, (giorno, tempo) in enumerate([
                (date(2026, 5, 1), 2700.0),
                (date(2026, 6, 1), 2800.0),
                (date(2026, 7, 1), 2750.0)]):
            _mare(connection, f"m{indice}", giorno, 3000, tempo)

        banda = owp.personal_band(connection, 3000)

        assert banda is not None
        assert 0.7 < banda[0] <= banda[1] < 0.95

    def test_two_races_are_not_a_band(self, connection):
        _soglia(connection)
        _mare(connection, "m1", date(2026, 5, 1), 3000, 2700.0)
        _mare(connection, "m2", date(2026, 6, 1), 3000, 2800.0)

        assert owp.personal_band(connection, 3000) is None, (
            "due gare non sono una popolazione, e una banda su due punti "
            "sembra una misura senza esserlo")

    def test_a_race_paired_with_an_old_threshold_does_not_count(self, connection):
        _soglia(connection, giorno=date(2016, 6, 15))
        for indice, giorno in enumerate([date(2019, 5, 1), date(2019, 6, 1),
                                         date(2019, 7, 1)]):
            _mare(connection, f"m{indice}", giorno, 3000, 2700.0)

        assert owp.personal_band(connection, 3000) is None, (
            "una gara del 2019 divisa per una soglia del 2016 misura il tempo "
            "passato, non il mare")

        osservate = owp.observations(connection)
        assert osservate and not any(una.usable for una in osservate)

    def test_a_different_distance_does_not_count(self, connection):
        _soglia(connection)
        for indice, giorno in enumerate([date(2026, 5, 1), date(2026, 6, 1),
                                         date(2026, 7, 1)]):
            _mare(connection, f"m{indice}", giorno, 1500, 1300.0)

        assert owp.personal_band(connection, 10000) is None, (
            "la quota cala con la distanza: usare un 1.500 per impostare un "
            "10.000 vuol dire partire troppo forte")

    def test_an_impossible_distance_never_enters(self, connection):
        _soglia(connection)
        # 2.000 m in 14'15": piu' veloce del suo miglior 100 in vasca.
        _mare(connection, "event05", date(2026, 6, 21), 2000, 855.0)

        assert owp.observations(connection) == [], (
            "la quota si calcola su un passo, e quella gara non ne ha uno: la "
            "distanza dichiarata e' smentita dai suoi tempi in vasca")


class TestWhenItCannotAnswer:
    def test_it_says_which_test_would_unblock_it(self, connection):
        _soglia(connection)
        _mare(connection, "event02", date(2019, 10, 6), 10000, 10846.0)

        perche = owp.why_unavailable(connection, 10000)

        assert "400 e un 200" in perche
        assert "stessa stagione" in perche, (
            "«dati insufficienti» non si puo' sbloccare; una prova precisa si'")

    def test_without_a_threshold_it_says_so_first(self, connection):
        _mare(connection, "m", date(2026, 6, 1), 3000, 2700.0)

        assert "velocità critica" in owp.why_unavailable(connection, 3000)

    def test_when_it_can_answer_there_is_no_reason(self, connection):
        _soglia(connection)
        for indice, giorno in enumerate([date(2026, 5, 1), date(2026, 6, 1),
                                         date(2026, 7, 1)]):
            _mare(connection, f"m{indice}", giorno, 3000, 2750.0)

        assert owp.why_unavailable(connection, 3000) == ""
        assert owp.summary(connection, 3000)["available"] is True
