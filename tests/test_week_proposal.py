"""La distribuzione settimanale proposta: dove passa il confine.

## La tensione che questi test presidiano

Il piano elenca fra i **non obiettivi** che il progetto «non genera come
funzione centrale calendari o programmi completi e non sostituisce l'allenatore
umano». Questo modulo ci si avvicina più di ogni altro, e l'atleta l'ha chiesto.

Il confine tenuto è: **una distribuzione, non un allenamento.** Quanti metri,
dove, a che passo — mai quale serie. I test difendono quel confine e le fonti
di ogni numero.

## Cosa difendono

1. Il volume proposto viene dalle **sue** settimane recenti, non da una tabella.
2. I passi vengono dalla **sua** velocità critica; senza, non compaiono.
3. Il lavoro specifico in mare **non** eredita il passo di soglia in vasca — è
   l'errore che l'intera scheda `dal-passo-in-vasca-al-passo-in-mare` esiste
   per impedire.
4. L'etichetta di «proposta» c'è sempre, e con essa il fatto che il programma
   dell'allenatore, se esiste, vince.
5. Senza storia di volume la proposta non si fa.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach import athlete_files
from garmin_coach.analysis import week_proposal as wp
from garmin_coach.database import SCHEMA

OGGI = date(2026, 8, 23)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(athlete_files.paths, "COACH", tmp_path)
    return tmp_path


def _storia(con, settimane=40, km=15.0):
    """Abbastanza settimane con nuotate perché la fascia di volume esista."""
    for numero in range(settimane):
        giorno = OGGI - timedelta(weeks=numero)
        con.execute("""
            INSERT INTO activities (activity_id, activity_date, start_time_utc,
                sport, is_swim, duration_s, distance_m, source_object_id,
                imported_at)
            VALUES (?, ?, ?, 'lap_swimming', true, 3600, ?, 'sha', ?)
        """, [numero, giorno,
              datetime(giorno.year, giorno.month, giorno.day, 7),
              km * 1000, datetime(2026, 1, 1)])


def _soglia(con):
    """Una coppia 400/200 che dà una velocità critica utilizzabile."""
    for race_id, distanza, tempo in (("400", 400, 275.34), ("200", 200, 128.76)):
        con.execute("""
            INSERT INTO races (race_id, race_date, meet, event_label,
                distance_m, stroke, is_relay, pool_length_m, time_s, status,
                timing, source_object_id, imported_at, environment,
                distance_source)
            VALUES (?, DATE '2026-05-24', 'Meet', 'stile libero', ?, 'stile',
                    false, 25, ?, 'valid', 'A', 'sha', ?, 'piscina',
                    'certified_pool')
        """, [race_id, distanza, tempo, datetime(2026, 1, 1)])


class TestWhenItRefuses:
    def test_without_volume_history_there_is_no_proposal(self, connection,
                                                         coach_dir):
        quadro = wp.propose(connection, today=OGGI)

        assert not quadro.available
        assert "storia di volume" in quadro.why


class TestWhereTheNumbersComeFrom:
    def test_the_volume_is_his_recent_weeks(self, connection, coach_dir):
        _storia(connection, km=15.0)

        quadro = wp.propose(connection, today=OGGI)

        assert quadro.available
        assert quadro.weekly_km == pytest.approx(15.0, abs=0.5)
        assert any("ultime" in una for una in quadro.basis), (
            "il volume viene dalle sue settimane recenti, non da una tabella")

    def test_the_paces_come_from_his_critical_speed(self, connection, coach_dir):
        _storia(connection)
        _soglia(connection)

        quadro = wp.propose(connection, today=OGGI)
        soglia = [una for una in quadro.sessions if una.purpose == "soglia"][0]

        # CSS = 73,29 s/100 m; la soglia sta a ±2 s.
        assert soglia.pace_band is not None
        assert 71 < soglia.pace_band[0] < 72
        assert 75 < soglia.pace_band[1] < 76

    def test_without_a_critical_speed_the_paces_disappear(self, connection,
                                                          coach_dir):
        _storia(connection)

        quadro = wp.propose(connection, today=OGGI)
        aerobico = [una for una in quadro.sessions
                    if una.purpose == "aerobico"][0]

        assert aerobico.pace_band is None
        assert "velocità critica" in aerobico.pace_display
        assert any("velocità critica" in una for una in quadro.caveats)

    def test_the_distribution_adds_up_to_the_weekly_volume(self, connection,
                                                           coach_dir):
        _storia(connection, km=20.0)

        quadro = wp.propose(connection, today=OGGI)
        totale = sum(una.distance_m for una in quadro.sessions)

        assert totale == pytest.approx(20000, abs=500)


class TestTheBoundaryItDoesNotCross:
    def test_the_sea_work_does_not_inherit_the_pool_threshold(self, connection,
                                                              coach_dir, monkeypatch):
        _storia(connection)
        _soglia(connection)
        (coach_dir / "gare.md").write_text(
            "| Data | Gara | Distanza | Ambiente | Vasca | Priorita | Obiettivo | Note |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 2026-10-03 | event02 place22 | 10 km | acque libere | - | A | - | - |\n",
            encoding="utf-8")

        quadro = wp.propose(connection, today=OGGI)
        specifico = [una for una in quadro.sessions
                     if una.purpose == "specifico gara"][0]

        assert specifico.environment == "acque libere"
        assert specifico.pace_band is None, (
            "usare il passo di soglia in vasca per il lavoro in mare è "
            "l'errore che la scheda dal-passo-in-vasca-al-passo-in-mare "
            "esiste per impedire")
        assert "non sulla velocità critica in vasca" in specifico.pace_display

    def test_it_always_says_it_is_a_proposal(self, connection, coach_dir):
        _storia(connection)

        avvertenze = " ".join(wp.propose(connection, today=OGGI).caveats)

        assert "non un allenamento" in avvertenze
        assert "lo decide il tuo allenatore" in avvertenze

    def test_it_says_the_real_programme_wins(self, connection, coach_dir):
        _storia(connection)

        avvertenze = " ".join(wp.propose(connection, today=OGGI).caveats)

        assert "programma-settimanale.md" in avvertenze, (
            "la proposta è un ripiego dichiarato, non un'alternativa alla pari")
