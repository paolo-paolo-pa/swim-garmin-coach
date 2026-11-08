"""La settimana, e la metà di risposta che manca.

L'incarico chiede piano contro eseguito. **Il piano non esiste nel sistema**: lo
fa l'allenatore umano, altrove, e nessuno lo ha mai scritto qui dentro.

Questa pagina mostra la metà che c'è e dichiara che l'altra manca, invece di
inventare un piano dai dati e poi confrontarci l'eseguito. Sarebbe la forma più
elegante di autoinganno: si confronterebbe l'atleta con sé stesso e si
chiamerebbe aderenza.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import paths
from garmin_coach.analysis import week
from garmin_coach.database import SCHEMA

LUNEDI = date(2026, 8, 17)


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    (cartella / "diario").mkdir(parents=True)
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def connection(coach_dir):
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _seduta(con, activity_id, giorno, distanza=3000, ambiente="pool",
            sport="lap_swimming", nuoto=True, ora=7):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, environment, distance_m, duration_s, "
        " source_object_id, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, 3600, "
        " 'sha', ?)",
        [activity_id,
         datetime.combine(giorno, datetime.min.time()).replace(hour=ora),
         giorno, sport, nuoto, ambiente, distanza, datetime(2026, 1, 1)])


def _nota(coach_dir, activity_id, giorno, finalita, rpe=None):
    percorso = coach_dir / "diario" / "2026-W34.md"
    testo = percorso.read_text(encoding="utf-8") if percorso.exists() else "# W34\n"
    righe = [f"\n## {giorno}\n", f"**Seduta {activity_id}** del {giorno}"]
    if rpe is not None:
        righe.append(f"- fatica percepita: **{rpe}/10** (CR10)")
    righe.append(f"- finalità: **{finalita}**")
    percorso.write_text(testo + "\n".join(righe) + "\n", encoding="utf-8")


class TestLaSettimanaContaQuelloCheEStatoFatto:
    def test_it_starts_on_monday(self):
        """Perché «la settimana scorsa» significhi la stessa cosa ovunque."""
        assert week.monday_of(date(2026, 8, 22)) == LUNEDI
        assert week.monday_of(LUNEDI) == LUNEDI

    def test_it_counts_sessions_and_metres(self, connection):
        _seduta(connection, 1, LUNEDI)
        _seduta(connection, 2, LUNEDI + __import__("datetime").timedelta(days=2))

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.sessions == 2
        assert settimana.distance_km == pytest.approx(6.0)
        assert settimana.days_trained == 2

    def test_open_water_and_pool_stay_apart(self, connection):
        _seduta(connection, 1, LUNEDI, 3000, "pool")
        _seduta(connection, 2, LUNEDI, 5000, "open_water",
                sport="open_water_swimming", ora=19)

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.pool_km == pytest.approx(3.0)
        assert settimana.open_water_km == pytest.approx(5.0)

    def test_other_sports_are_counted_apart_and_not_added(self, connection):
        """Sommare la corsa al nuoto risponderebbe a una domanda che l'atleta
        non ha fatto."""
        _seduta(connection, 1, LUNEDI)
        _seduta(connection, 2, LUNEDI, 10000, None, sport="running",
                nuoto=False, ora=19)

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.sessions == 1
        assert settimana.other_sports_sessions == 1
        assert settimana.distance_km == pytest.approx(3.0)


class TestLaFinalitaVieneDalDiarioENonSiIndovina:
    def test_a_declared_purpose_is_read_from_the_diary(self, connection,
                                                       coach_dir):
        _seduta(connection, 1, LUNEDI, 4000)
        _nota(coach_dir, 1, LUNEDI.isoformat(), "soglia", rpe=8)

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.by_purpose["soglia"] == pytest.approx(4.0)
        assert settimana.declared_n == 1

    def test_a_session_without_a_note_is_not_guessed(self, connection):
        """Non sparisce e non viene indovinata: entra in «non dichiarata», che
        è un numero che l'atleta può far scendere scrivendo."""
        _seduta(connection, 1, LUNEDI, 3000)

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.by_purpose["non dichiarata"] == pytest.approx(3.0)
        assert settimana.declared_n == 0
        assert settimana.declared_share == 0.0

    def test_the_coverage_of_the_declarations_is_visible(self, connection,
                                                         coach_dir):
        for i in range(4):
            _seduta(connection, i + 1,
                    LUNEDI + __import__("datetime").timedelta(days=i))
        _nota(coach_dir, 1, LUNEDI.isoformat(), "fondo")

        settimana = week.of_week(connection, LUNEDI)

        assert settimana.declared_share == pytest.approx(0.25)


class TestLaFaticaPercepitaNonDiventaUnaMediaDiUnaSola:
    def test_one_rpe_is_not_an_average_of_the_week(self, connection, coach_dir):
        """Su una sola seduta non è una media della settimana: è quella seduta."""
        _seduta(connection, 1, LUNEDI)
        _nota(coach_dir, 1, LUNEDI.isoformat(), "fondo", rpe=9)

        assert week.of_week(connection, LUNEDI).avg_rpe is None

    def test_two_make_one(self, connection, coach_dir):
        _seduta(connection, 1, LUNEDI)
        _seduta(connection, 2, LUNEDI + __import__("datetime").timedelta(days=1))
        _nota(coach_dir, 1, LUNEDI.isoformat(), "fondo", rpe=6)
        _nota(coach_dir, 2, LUNEDI.isoformat(), "soglia", rpe=8)

        assert week.of_week(connection, LUNEDI).avg_rpe == pytest.approx(7.0)


class TestLeUltimeSettimane:
    def test_it_returns_them_from_the_most_recent(self, connection):
        _seduta(connection, 1, LUNEDI)

        settimane = week.recent(connection, today=date(2026, 8, 22), weeks=3)

        assert len(settimane) == 3
        assert settimane[0].start == LUNEDI
        assert settimane[1].start < settimane[0].start
