"""Distanza percorsa senza bracciate, riconosciuta dai lap.

## Perché sui lap e non sul riepilogo

Due tentativi sui campi di riepilogo sono stati misurati e scartati (audit
§A1.7): i metri per bracciata sbagliavano l'unità, e le bracciate contro
cadenza × durata erano confuse dai riposi inclusi in ``duration_s``. La firma
di place20 si vede solo lap per lap.

## La firma

I 28 lap di place20, guardati in fila: cinque hanno cadenza fra 21 e 28 —
l'orologio **stava misurando** — e gli altri ventitré coprono 800-1500 m ciascuno
con cadenza 0, 1, 2. Il 79% della distanza è stato percorso senza bracciare.

## Il criterio che ho scartato, e perché è importante

Il primo criterio era «quota di distanza in lap senza cadenza». Misurato su
1.191 attività, le quattro peggiori erano al 98-100% — e fra queste c'è
**place07 2019, 5.800 m a 1:26,0**, che è uno dei migliori risultati veri
dell'atleta e sta in `coach/gare.md` come riferimento.

Il motivo: in acque libere molti orologi non registrano affatto la cadenza.
Zero cadenza su tutta l'attività significa «non misurata», non «non nuotata».

Il discriminante vero è l'**alternanza**: l'orologio ha dimostrato di saper
misurare, in quella stessa attività, e ciononostante gran parte della distanza
è passata senza bracciate. Restringendo alle attività con almeno un lap a
cadenza piena, place20 diventa il massimo assoluto — 0,79 — e place07 esce.

## Cosa succede sull'archivio vero

Due segnalazioni su 1.187 attività: place20, che l'atleta ha già escluso, e il
16/07/2019 — 2.500 m in 54 minuti con 148 bracciate in totale, cioè un'altra
anomalia che vale la pena guardare.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import corrections, paths
from garmin_coach.database import SCHEMA

GIORNO = date(2025, 9, 20)


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    (cartella / "correzioni-dati.md").write_text("# vuoto\n", encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def connection(coach_dir):
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _attivita(con, activity_id, ambiente="open_water", distanza=25000.0):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        " sport, is_swim, environment, distance_m, duration_s, "
        " source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'open_water_swimming', TRUE, ?, ?, 20000, 'sha', ?)",
        [activity_id, datetime(2025, 9, 20, 7), GIORNO, ambiente, distanza,
         datetime(2026, 1, 1)])


def _lap(con, activity_id, indice, distanza, cadenza, riposo=False):
    con.execute(
        "INSERT INTO activity_laps (activity_id, lap_index, start_time_utc, "
        " duration_s, distance_m, avg_cadence_spm, is_rest, source_object_id, "
        " imported_at) VALUES (?, ?, ?, 900, ?, ?, ?, 'fit://x', ?)",
        [activity_id, indice, datetime(2025, 9, 20, 7, indice), distanza,
         cadenza, riposo, datetime(2026, 1, 1)])


class TestRiconosceLaFirmaDiplace20:
    def test_an_activity_where_most_distance_has_no_strokes_is_flagged(
            self, connection):
        """Cinque lap con cadenza vera e venti senza: l'orologio misurava."""
        _attivita(connection, 1)
        for i in range(20):
            _lap(connection, 1, i, 950, 0)
        for i in range(20, 25):
            _lap(connection, 1, i, 950, 26)

        segnalate = corrections.flag_automatically(connection)

        assert any(s["activity_id"] == 1 for s in segnalate)
        assert any("bracciate" in s["check"] for s in segnalate)

    def test_the_reason_says_how_much_of_the_distance_was_silent(
            self, connection):
        """Una segnalazione senza il proprio numero non si può valutare."""
        _attivita(connection, 1)
        for i in range(20):
            _lap(connection, 1, i, 950, 0)
        for i in range(20, 25):
            _lap(connection, 1, i, 950, 26)
        corrections.flag_automatically(connection)

        motivo = connection.execute(
            "SELECT reason FROM activity_quality WHERE activity_id = 1"
        ).fetchone()[0]
        assert "%" in motivo


class TestNonSegnalaUnaNuotataVERA:
    def test_a_swim_where_the_watch_never_measured_cadence_is_left_alone(
            self, connection):
        """Il caso place07 2019, che il primo criterio segnalava al 100%.

        In acque libere molti orologi non registrano la cadenza. Zero cadenza
        su **tutta** l'attività significa «non misurata», non «non nuotata» — e
        segnalare uno dei migliori risultati veri dell'atleta avrebbe insegnato
        a ignorare le segnalazioni.
        """
        _attivita(connection, 1, distanza=5800.0)
        for i in range(6):
            _lap(connection, 1, i, 967, 0)

        assert not corrections.flag_automatically(connection)

    def test_a_pool_session_with_kick_sets_is_left_alone(self, connection):
        """Le vasche a gambe hanno cadenza zero e coprono distanza.

        Sono lap corti: il filtro sulla lunghezza del lap le lascia fuori senza
        bisogno di sapere che cosa siano.
        """
        _attivita(connection, 1, ambiente="pool", distanza=3000.0)
        for i in range(8):
            _lap(connection, 1, i, 100, 0)          # 800 m a gambe
        for i in range(8, 30):
            _lap(connection, 1, i, 100, 28)

        assert not corrections.flag_automatically(connection)

    def test_rest_laps_never_count_as_silent_distance(self, connection):
        """Un lap di riposo non ha bracciate, ed è quello che deve fare."""
        _attivita(connection, 1, ambiente="pool", distanza=3000.0)
        for i in range(10):
            _lap(connection, 1, i, 400, 0, riposo=True)
        for i in range(10, 20):
            _lap(connection, 1, i, 400, 28)

        assert not corrections.flag_automatically(connection)


class TestNonSiRompeQuandoIDatiNonCiSono:
    def test_an_archive_without_laps_produces_no_flags_and_no_error(
            self, connection):
        """Prima della Fase 5 `activity_laps` è vuota. Il rilevatore tace
        invece di rompersi o di segnalare tutto."""
        _attivita(connection, 1)

        assert corrections.flag_automatically(connection) == []

    def test_the_athlete_decision_still_wins(self, connection, coach_dir):
        (coach_dir / "correzioni-dati.md").write_text(
            "| Activity ID | Stato | Data | Ambito | Motivo | Confermata |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | `keep` | 2025-09-20 | tutto | L'ho guardata, va bene. | 2026-08-22 |\n",
            encoding="utf-8")
        _attivita(connection, 1)
        for i in range(20):
            _lap(connection, 1, i, 950, 0)
        for i in range(20, 25):
            _lap(connection, 1, i, 950, 26)

        corrections.apply(connection)
        corrections.flag_automatically(connection)

        stato = connection.execute(
            "SELECT status, decided_by FROM activity_quality WHERE activity_id = 1"
        ).fetchone()
        assert stato == ("keep", "athlete")
