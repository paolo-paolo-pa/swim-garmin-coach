"""La memoria storica: trovare precedenti senza inventare cause.

È la funzione con il rischio più alto di tutto il progetto. Un atleta solo,
nove anni e decine di confronti possibili producono associazioni casuali da
soli; e una frase come «dopo blocchi così ti sei fermato» suona vera anche
quando non lo è.

I test qui difendono tre cose: che il 2017-2020 non sparisca in silenzio, che
non compaia linguaggio causale, e che un periodo senza precedenti venga
dichiarato tale invece di essere accostato al meno peggio.
"""

import itertools
from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis import chart, progress
from garmin_coach.analysis.insight import Status
from garmin_coach.database import SCHEMA

FINE = date(2026, 8, 20)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


_IDENTIFICATIVO = itertools.count(1)


def nuota(con, day: date, distance_m: float = 3000):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, sport, "
        "is_swim, environment, distance_m, duration_s, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, 'pool', ?, 3600, 'sha', ?)",
        [next(_IDENTIFICATIVO),
         datetime.combine(day, datetime.min.time()).replace(hour=20),
         day, distance_m, datetime(2026, 1, 1)])


def blocco(con, fine: date, km_settimana: float, sedute_settimana: int = 3):
    """Quattro settimane a un volume dato."""
    metri = km_settimana * 1000 / sedute_settimana
    for settimana in range(4):
        for seduta in range(sedute_settimana):
            giorno = fine - timedelta(days=settimana * 7 + seduta)
            nuota(con, giorno, metri)


class TestTheOldYearsNeverDisappearInSilence:
    def test_a_block_from_2018_can_be_a_precedent_for_one_from_2026(self, connection):
        """Se la somiglianza usasse il carico, i quattro anni senza
        cardiofrequenzimetro sparirebbero senza che nessuno lo sappia."""
        blocco(connection, FINE, km_settimana=15)
        blocco(connection, date(2018, 5, 20), km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        anni = {caso["start"][:4] for caso in packet.comparisons}
        assert "2018" in anni

    def test_every_case_declares_what_the_watch_measured_back_then(self, connection):
        blocco(connection, FINE, km_settimana=15)
        blocco(connection, date(2018, 5, 20), km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        for caso in packet.comparisons:
            assert caso["epoch"], "ogni caso porta la propria epoca del dato"
        vecchio = [c for c in packet.comparisons if c["start"].startswith("2018")][0]
        assert "non misurava la frequenza cardiaca" in vecchio["epoch"]

    @pytest.mark.parametrize("giorno,atteso", [
        (date(2018, 3, 1), "non misurava la frequenza cardiaca"),
        (date(2022, 3, 1), "l'HRV non esisteva ancora"),
        (date(2026, 3, 1), "HRV"),
    ])
    def test_the_epoch_matches_when_each_sensor_started(self, giorno, atteso):
        assert atteso in progress.epoch_of(giorno)


class TestNoCausalLanguage:
    def test_what_happened_after_is_described_never_explained(self, connection):
        blocco(connection, FINE, km_settimana=15)
        blocco(connection, date(2024, 5, 20), km_settimana=15)
        for giorno in range(1, 29):        # un mese di riposo dopo quel blocco
            pass

        packet = progress.observation(connection, until=FINE, today=FINE)
        whole = " ".join([packet.observation] + packet.limitations).lower()

        for vietato in ("ti ha stancato", "a causa di", "ha provocato",
                        "quindi ti fermerai", "succedera di nuovo"):
            assert vietato not in whole, f"linguaggio causale: {vietato}"
        assert "non è una risposta del corpo" in whole, (
            "la pagina lascia credere che il volume delle settimane dopo sia "
            "l'effetto del blocco: è il rilievo A4.3")

    def test_the_similarity_criterion_is_stated_out_loud(self, connection):
        blocco(connection, FINE, km_settimana=15)
        blocco(connection, date(2024, 5, 20), km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        assert any("solo su volume e sedute" in limite
                   for limite in packet.limitations)


class TestWhenThereIsNoPrecedent:
    def test_a_period_without_precedents_says_so(self, connection):
        blocco(connection, FINE, km_settimana=40)          # volume mai visto
        blocco(connection, date(2024, 5, 20), km_settimana=8)

        packet = progress.observation(connection, until=FINE, today=FINE)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert "senza precedenti confrontabili" in packet.observation
        assert not packet.comparisons

    def test_an_empty_archive_does_not_crash(self, connection):
        packet = progress.observation(connection, today=FINE)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert not packet.comparisons

    def test_four_weeks_without_swimming_are_not_a_block(self, connection):
        blocco(connection, date(2024, 5, 20), km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        assert packet.status == Status.INSUFFICIENT_DATA
        assert "non risultano nuotate" in packet.observation


class TestTheCasesAreRealAndOpenable:
    def test_overlapping_blocks_are_not_shown_twice(self, connection):
        """Due blocchi che si sovrappongono raccontano la stessa storia."""
        blocco(connection, FINE, km_settimana=15)
        for spostamento in range(0, 4):    # quattro finestre sullo stesso periodo
            blocco(connection, date(2024, 5, 20) + timedelta(days=spostamento * 7),
                   km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)
        fini = [caso["end"] for caso in packet.comparisons]

        for prima in range(len(fini)):
            for dopo in range(prima + 1, len(fini)):
                distanza = abs((date.fromisoformat(fini[prima])
                                - date.fromisoformat(fini[dopo])).days)
                assert distanza >= progress.BLOCK_WEEKS * 7

    def test_the_current_block_never_matches_itself(self, connection):
        blocco(connection, FINE, km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        for caso in packet.comparisons:
            assert date.fromisoformat(caso["end"]) < FINE - timedelta(weeks=4)

    def test_each_case_reports_all_three_follow_up_windows(self, connection):
        blocco(connection, FINE, km_settimana=15)
        blocco(connection, date(2024, 5, 20), km_settimana=15)

        packet = progress.observation(connection, until=FINE, today=FINE)

        for caso in packet.comparisons:
            assert [e["days"] for e in caso["what_you_did_after"]] == [7, 14, 28]


class TestTheChart:
    def test_an_empty_series_produces_an_empty_chart_not_a_crash(self):
        grafico = chart.weekly_bars([])
        assert grafico.is_empty
        assert "Nessuna settimana" in grafico.descrizione

    def test_bars_are_proportional_to_the_biggest_week(self):
        from garmin_coach.analysis.volume import Week
        settimane = [Week(date(2026, 8, 3), 3, 10000, 3600, 3, None),
                     Week(date(2026, 8, 10), 3, 20000, 3600, 3, None)]

        grafico = chart.weekly_bars(settimane)

        assert grafico.barre[1].altezza == chart.BASE
        assert grafico.barre[0].altezza == chart.BASE / 2

    def test_every_bar_can_be_read_by_a_screen_reader(self):
        from garmin_coach.analysis.volume import Week
        grafico = chart.weekly_bars([Week(date(2026, 8, 3), 3, 10000, 3600, 3, None)])

        assert "10.0 km in 3 sedute" in grafico.barre[0].titolo

    def test_the_geometry_is_computed_here_so_the_page_does_not_have_to(self):
        """Regola Aurea n.8: l'altezza di una barra è una divisione, e le
        divisioni nei template sono vietate."""
        from garmin_coach.analysis.volume import Week
        grafico = chart.weekly_bars([Week(date(2026, 8, 3), 3, 10000, 3600, 3, None)])

        barra = grafico.barre[0]
        for campo in ("x", "y", "larghezza", "altezza"):
            assert isinstance(getattr(barra, campo), (int, float))
