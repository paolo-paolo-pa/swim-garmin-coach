"""Le serie e la struttura della seduta: cosa si legge e cosa si inferisce.

## Il rischio che questi test presidiano

R1 del piano: **un lap non è una serie.** Una ricostruzione sbagliata è peggio di
nessuna ricostruzione, perché somiglia a un allenamento vero e nessuno la mette
in dubbio.

Qui ci sono due strati con due livelli di fiducia diversi, e i test servono a
non farli scivolare uno nell'altro:

1. **Le ripetute si leggono.** Lap uguali di fila sono un fatto aritmetico.
2. **I blocchi si inferiscono**, e solo perché l'atleta ha dichiarato che le sue
   sedute hanno sempre la stessa forma. Quando i dati non ci stanno dentro, la
   risposta è `non riconosciuta`.

## Cosa difendono

- Due ripetute non sono una serie.
- Un cambio di distanza, di nuotata, di ritmo o un riposo molto più lungo
  chiudono un gruppo: sono i quattro modi in cui una serie finisce davvero.
- Il riposo prima della prima ripetuta non appartiene alla serie.
- Il defaticamento troppo lungo non è un defaticamento e non viene chiamato così.
- «Non ci sono lap» e «i lap non formano serie» sono due messaggi diversi,
  perché mandano a guardare due posti diversi.
"""

from datetime import datetime

import duckdb
import pytest

from garmin_coach.analysis import session_structure as ss
from garmin_coach.database import SCHEMA

ATTIVITA = 999


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _lap(con, indice, distanza, durata, stroke="freestyle", riposo=False):
    con.execute("""
        INSERT INTO activity_laps (activity_id, lap_index, duration_s,
            distance_m, stroke, is_rest, source_object_id, imported_at,
            environment)
        VALUES (?, ?, ?, ?, ?, ?, 'sha', ?, 'pool')
    """, [ATTIVITA, indice, durata, distanza, stroke, riposo,
          datetime(2026, 1, 1)])


def _serie(con, partenza, ripetute, distanza, durata, riposo=20.0,
           stroke="freestyle"):
    """Scrive una serie: nuotata, riposo, nuotata, riposo…"""
    indice = partenza
    for numero in range(ripetute):
        if numero:
            _lap(con, indice, 0, riposo, stroke=None, riposo=True)
            indice += 1
        _lap(con, indice, distanza, durata, stroke=stroke)
        indice += 1
    return indice


class TestReadingTheRepetitions:
    def test_six_equal_laps_are_a_set(self, connection):
        _serie(connection, 0, 6, 100, 90.0)

        trovate = ss.sets(connection, ATTIVITA)

        assert len(trovate) == 1
        assert trovate[0].label == "6×100 freestyle"
        assert trovate[0].total_m == 600

    def test_two_equal_laps_are_not_a_set(self, connection):
        _serie(connection, 0, 2, 100, 90.0)

        assert ss.sets(connection, ATTIVITA) == [], (
            "due 100 di fila capitano in qualunque riscaldamento")

    def test_a_change_of_distance_closes_the_set(self, connection):
        fine = _serie(connection, 0, 4, 100, 90.0)
        _serie(connection, fine, 4, 50, 42.0)

        trovate = ss.sets(connection, ATTIVITA)

        assert [una.label for una in trovate] == ["4×100 freestyle",
                                                  "4×50 freestyle"]

    def test_a_change_of_stroke_closes_the_set(self, connection):
        fine = _serie(connection, 0, 3, 100, 90.0)
        _serie(connection, fine, 3, 100, 95.0, stroke="backstroke")

        assert len(ss.sets(connection, ATTIVITA)) == 2

    def test_a_much_longer_rest_closes_the_set(self, connection):
        # 5×100 con recupero 20", poi 2 minuti, poi altri 5×100: sono due serie.
        indice = _serie(connection, 0, 5, 100, 90.0, riposo=20.0)
        _lap(connection, indice, 0, 120.0, stroke=None, riposo=True)
        _serie(connection, indice + 1, 5, 100, 90.0, riposo=20.0)

        trovate = ss.sets(connection, ATTIVITA)

        assert len(trovate) == 2, (
            "due minuti di stacco dentro un recupero da venti secondi non "
            "sono un recupero: sono la fine della serie")

    def test_a_drifting_group_splits_when_it_leaves_the_band(self, connection):
        indice = 0
        for durata in (90.0, 90.0, 90.0, 115.0, 115.0, 115.0):
            if indice:
                _lap(connection, indice, 0, 20.0, stroke=None, riposo=True)
                indice += 1
            _lap(connection, indice, 100, durata)
            indice += 1

        trovate = ss.sets(connection, ATTIVITA)

        assert len(trovate) == 2, (
            "dentro lo stesso gruppo stavano succedendo due lavori diversi")

    def test_the_rest_before_the_first_rep_is_not_part_of_the_set(self, connection):
        _lap(connection, 0, 0, 300.0, stroke=None, riposo=True)
        _serie(connection, 1, 4, 100, 90.0, riposo=15.0)

        una = ss.sets(connection, ATTIVITA)[0]

        assert una.median_rest_s == pytest.approx(15.0), (
            "cinque minuti prima della serie appartengono a ciò che c'era "
            "prima, non a questa serie")


class TestDidYouHoldIt:
    def test_a_steady_set_is_held(self, connection):
        _serie(connection, 0, 6, 100, 90.0)

        assert ss.sets(connection, ATTIVITA)[0].drift_pct == pytest.approx(0.0)

    def test_a_fading_set_says_so(self, connection):
        indice = 0
        for durata in (88.0, 89.0, 90.0, 94.0, 95.0, 96.0):
            if indice:
                _lap(connection, indice, 0, 20.0, stroke=None, riposo=True)
                indice += 1
            _lap(connection, indice, 100, durata)
            indice += 1

        una = ss.sets(connection, ATTIVITA)[0]

        assert una.drift_pct > 1.5
        assert "calando" in ss._tenuta(una)


class TestTheDeclaredStructure:
    def _seduta_tipo(self, connection):
        """Riscaldamento, attivazione, parte centrale, defaticamento."""
        indice = _serie(connection, 0, 4, 50, 45.0)          # 200 m
        indice = _serie(connection, indice, 4, 100, 88.0)    # 400 m
        indice = _serie(connection, indice, 8, 200, 180.0)   # 1600 m
        _serie(connection, indice, 3, 100, 110.0)            # 300 m

    def test_the_four_parts_are_found(self, connection):
        self._seduta_tipo(connection)

        nomi = [uno.name for uno in ss.blocks(connection, ATTIVITA)]

        assert nomi == ["riscaldamento", "attivazione", "parte centrale",
                        "defaticamento"]

    def test_the_main_part_is_the_one_with_most_metres(self, connection):
        self._seduta_tipo(connection)

        centrale = [uno for uno in ss.blocks(connection, ATTIVITA)
                    if uno.name == "parte centrale"][0]

        assert centrale.total_m == 1600

    def test_the_warm_up_is_declared_not_inferred(self, connection):
        self._seduta_tipo(connection)

        primo = ss.blocks(connection, ATTIVITA)[0]

        assert primo.confidence == "dichiarata", (
            "il riscaldamento è primo perché l'atleta dice che c'è sempre e "
            "viene sempre prima, non perché sia più lento")

    def test_two_similar_groups_of_the_same_distance_are_one_set(self, connection):
        # 6×100 a 88" e 5×100 a 92" con lo stesso recupero non sono due serie:
        # sono un 11×100. Separarle richiederebbe di sapere cosa aveva in testa
        # l'allenatore, e l'orologio non lo registra.
        indice = _serie(connection, 0, 6, 100, 88.0)
        _serie(connection, indice, 5, 100, 92.0)

        trovate = ss.sets(connection, ATTIVITA)

        assert len(trovate) == 1 and trovate[0].reps == 11

    def test_a_long_final_block_is_not_a_cool_down(self, connection):
        indice = _serie(connection, 0, 4, 50, 45.0)          # 200 m
        indice = _serie(connection, indice, 8, 100, 88.0)    # 800 m
        _serie(connection, indice, 6, 50, 48.0)              # 300 m, il 23%

        nomi = [uno.name for uno in ss.blocks(connection, ATTIVITA)]

        assert "defaticamento" not in nomi
        assert "lavoro dopo la parte centrale" in nomi, (
            "cinquecento metri dopo il lavoro principale non sono un "
            "defaticamento, e chiamarli così cambierebbe la lettura")

    def test_when_the_longest_set_is_first_it_refuses(self, connection):
        indice = _serie(connection, 0, 10, 200, 180.0)       # 2000 m, primo
        _serie(connection, indice, 3, 100, 100.0)

        quadro = ss.as_page_dict(connection, ATTIVITA)

        assert quadro["available"] is False
        assert "il lavoro più lungo è il primo" in quadro["why"]
        assert quadro["sets"], "le serie restano, è la divisione a mancare"


class TestTheTwoWaysOfNotKnowing:
    def test_no_laps_at_all_says_so(self, connection):
        quadro = ss.as_page_dict(connection, ATTIVITA)

        assert "non ha lap dettagliati" in quadro["why"]

    def test_laps_without_repetitions_say_something_else(self, connection):
        for indice, distanza in enumerate((75, 125, 200, 50)):
            _lap(connection, indice, distanza, distanza * 1.1)

        quadro = ss.as_page_dict(connection, ATTIVITA)

        assert "4 tratti nuotati" in quadro["why"], (
            "«non ci sono lap» manda a guardare l'import, «i lap non formano "
            "serie» manda a guardare la seduta: sono due posti diversi")
