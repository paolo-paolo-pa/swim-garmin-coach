"""Le decisioni dell'atleta sulle gare, lette da ``coach/correzioni-gare.md``.

Il file vero è quello dell'atleta e non si tocca nei test: qui si verifica il
lettore su tabelle costruite a mano, nella stessa forma.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import race_corrections
from garmin_coach.database import SCHEMA

INTESTAZIONE = (
    "| Race ID | Stato | Data | Seduta Garmin | Distanza corretta | "
    "Decisione e motivo | Confermata il |\n"
    "|---|---|---|---:|---|---|---|\n"
)


@pytest.fixture
def file_gare(tmp_path, monkeypatch):
    """Scrive un finto ``correzioni-gare.md`` e ci punta il modulo."""
    def scrivi(*righe: str) -> None:
        (tmp_path / race_corrections.FILE).write_text(
            "# Correzioni\n\n" + INTESTAZIONE + "".join(righe),
            encoding="utf-8")
    monkeypatch.setattr(race_corrections.paths, "COACH", tmp_path)
    return scrivi


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


# ── Lettura ────────────────────────────────────────────────────────────────

def test_no_file_is_the_normal_state_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(race_corrections.paths, "COACH", tmp_path)
    assert race_corrections.declared() == []


def test_a_linked_race_carries_the_swim_it_is(file_gare):
    file_gare("| `icron-2019-09-01-event06` | `linked` | 2019-09-01 | "
              "10000000005 |  | stessa durata al secondo | 2026-08-25 |\n")

    una, = race_corrections.declared()

    assert una.race_id == "icron-2019-09-01-event06"
    assert una.verdict == race_corrections.LINKED
    assert una.activity_id == 10000000005
    assert una.confirmed_on == date(2026, 8, 25)
    assert una.is_linked


def test_a_separate_race_names_no_swim(file_gare):
    file_gare("| `icron-2026-08-23-event01` | `separate` | 2026-08-23 |  | "
              "1900 | place04 la mattina, place03 la sera | 2026-08-25 |\n")

    una, = race_corrections.declared()

    assert una.verdict == race_corrections.SEPARATE
    assert una.activity_id is None
    assert una.counted_distance_m == 1900


def test_the_other_tables_of_the_file_are_not_decisions(file_gare):
    """Il file contiene anche l'elenco delle distanze da recuperare, che è una
    tabella di righe senza race id: leggerle come decisioni le applicherebbe."""
    file_gare("| `icron-2026-08-23-event01` | `separate` | 2026-08-23 |  |  "
              "| motivo | 2026-08-25 |\n",
              "| 2020-09-12 | event03 | place16 | 44:25 | "
              "`AGONISTI_REGIONE` | niente | |\n")

    assert len(race_corrections.declared()) == 1


# ── Quello che il lettore si rifiuta di indovinare ─────────────────────────

def test_an_unknown_verdict_stops_everything(file_gare):
    """Una riga scritta per togliere una gara dal volume, se non viene capita,
    la lascia dentro le medie — e l'atleta crede di averla tolta."""
    file_gare("| `icron-2026-08-23-event01` | `forse` | 2026-08-23 |  |  | "
              "motivo | 2026-08-25 |\n")

    with pytest.raises(race_corrections.UnknownDecision, match="forse"):
        race_corrections.declared()


def test_a_link_without_a_swim_is_refused(file_gare):
    """Un collegamento senza la seduta non toglie il doppio conteggio: dice
    solo che qualcuno ci ha pensato."""
    file_gare("| `icron-2019-09-01-event06` | `linked` | 2019-09-01 | "
              " |  | motivo | 2026-08-25 |\n")

    with pytest.raises(race_corrections.UnknownDecision, match="quale seduta"):
        race_corrections.declared()


def test_an_unreadable_distance_stops_everything(file_gare):
    file_gare("| `icron-2026-08-23-event01` | `separate` | 2026-08-23 |  | "
              "quasi due chilometri | motivo | 2026-08-25 |\n")

    with pytest.raises(race_corrections.UnknownDecision, match="non si legge"):
        race_corrections.declared()


# ── La distanza ────────────────────────────────────────────────────────────

def test_distances_are_read_in_metres_and_kilometres():
    assert race_corrections.parse_counted_distance("1900") == (1900, False)
    assert race_corrections.parse_counted_distance("1900 m") == (1900, False)
    assert race_corrections.parse_counted_distance("1,9 km") == (1900, False)
    assert race_corrections.parse_counted_distance("") == (None, False)


def test_unknown_is_not_the_same_as_no_correction():
    """«Non ho corretto niente» e «so che il numero è sbagliato e non so quale
    sia» sono due cose diverse: comprimerle perderebbe la differenza."""
    assert race_corrections.parse_counted_distance("sconosciuta") == (None, True)
    assert race_corrections.parse_counted_distance("") == (None, False)


# ── Applicazione ───────────────────────────────────────────────────────────

def test_removing_a_row_removes_the_correction(connection, file_gare):
    """La tabella si rifà dal file: togliere una riga dal markdown toglie
    davvero la correzione, invece di lasciarla in archivio per sempre."""
    file_gare("| `icron-a` | `exclude` | 2025-06-21 |  |  | giro ridotto | "
              "2026-08-25 |\n")
    race_corrections.apply(connection)
    assert connection.execute("SELECT count(*) FROM race_quality").fetchone()[0] == 1

    file_gare()
    race_corrections.apply(connection)
    assert connection.execute("SELECT count(*) FROM race_quality").fetchone()[0] == 0


def test_the_report_counts_what_it_did(connection, file_gare):
    file_gare("| `icron-a` | `linked` | 2019-09-01 | 10000000005 |  | m | 2026-08-25 |\n",
              "| `icron-b` | `exclude` | 2025-06-21 |  |  | m | 2026-08-25 |\n",
              "| `icron-c` | `separate` | 2026-08-23 |  | 1900 | m | 2026-08-25 |\n")

    assert race_corrections.apply(connection) == {
        "decisioni": 3, "collegate": 1, "escluse": 1, "distanze_corrette": 1}


# ── I casi che nessuno ha ancora guardato ──────────────────────────────────

def test_a_race_sharing_a_day_with_a_swim_needs_a_human(connection):
    """Il programma non può sapere se quella gara è quella nuotata: c'è una
    nuotata quel giorno, e nessuno ha guardato. Il criterio C19 lo fa emergere
    invece di lasciar indovinare."""
    connection.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        "sport, is_swim, environment, distance_m, duration_s, "
        "source_object_id, imported_at) VALUES (1, ?, ?, 'open_water_swimming',"
        " TRUE, 'open_water', 4068, 4237, 'sha', ?)",
        [datetime(2026, 8, 23, 18, 36), date(2026, 8, 23), datetime(2026, 1, 1)])
    connection.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, venue, source_object_id, "
        "imported_at) VALUES ('icron-event01', ?, '3* event01', 'fondo', "
        "2500, FALSE, 1535, 'valid', 'acque libere', 'place04', 'sha', ?)",
        [date(2026, 8, 23), datetime(2026, 1, 1)])

    da_guardare = race_corrections.unexamined(connection)

    assert [riga[0] for riga in da_guardare] == ["icron-event01"]


def test_a_race_alone_in_its_day_needs_nobody(connection):
    connection.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, source_object_id, imported_at) "
        "VALUES ('icron-sola', ?, 'gara', 'fondo', 3000, FALSE, 2700, 'valid', "
        "'acque libere', 'sha', ?)",
        [date(2026, 8, 23), datetime(2026, 1, 1)])

    assert race_corrections.unexamined(connection) == []


# ── La correzione deve arrivare a ogni superficie ──────────────────────────
#
# La migrazione 0017 applicava la distanza corretta solo dentro
# `counted_swims`, cioè solo al volume: la pagina Gare avrebbe continuato a
# mostrare place04 a 2.500 m con il passo di 1:01,4 per 100, quello che l'atleta
# aveva appena dichiarato impossibile. Due superfici, due risposte alla stessa
# domanda (Regola Aurea n.8).

def add_race(con, race_id: str, day: str, distance_m: float | None,
             time_s: float = 3600.0, environment: str = "acque libere"):
    con.execute(
        "INSERT INTO races (race_id, race_date, meet, event_label, distance_m, "
        "is_relay, time_s, status, environment, source_object_id, imported_at) "
        "VALUES (?, ?, 'gara', 'fondo', ?, FALSE, ?, 'valid', ?, 'sha', ?)",
        [race_id, date.fromisoformat(day), distance_m, time_s, environment,
         datetime(2026, 1, 1)])


def correct(con, race_id: str, verdict: str = "separate", **campi):
    con.execute(
        "INSERT INTO race_quality (race_id, verdict, activity_id, "
        " counted_distance_m, distance_is_unknown, reason, decided_by, "
        " applied_at) VALUES (?, ?, ?, ?, ?, 'motivo', 'athlete', ?)",
        [race_id, verdict, campi.get("activity_id"),
         campi.get("counted_distance_m"),
         campi.get("distance_is_unknown", False), datetime(2026, 8, 25)])


def test_the_corrected_distance_reaches_the_race_views(connection):
    add_race(connection, "icron-place04", "2026-08-23", 2500, time_s=1535)
    correct(connection, "icron-place04", counted_distance_m=1900)

    riga = connection.execute(
        "SELECT distance_m, declared_distance_m, distance_corrected "
        "FROM open_water_races WHERE race_id = 'icron-place04'").fetchone()

    assert riga == (1900, 2500, True)


def test_the_declared_distance_stays_visible(connection):
    """Senza, fra un anno qualcuno scambia il numero giusto per un difetto e lo
    «ripara»."""
    add_race(connection, "icron-place04", "2026-08-23", 2500)
    correct(connection, "icron-place04", counted_distance_m=1900)

    assert connection.execute(
        "SELECT declared_distance_m FROM canonical_races").fetchone()[0] == 2500


def test_an_excluded_race_disappears_from_the_views(connection):
    add_race(connection, "icron-event05", "2025-06-21", 2000)
    correct(connection, "icron-event05", verdict="exclude")

    assert connection.execute("SELECT count(*) FROM canonical_races").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM open_water_races").fetchone()[0] == 0


def test_a_race_without_a_time_still_counts_its_metres(connection):
    """`personal_races` scarta le gare senza tempo, ed è giusto per leggere una
    prestazione. Per contare metri nuotati no: due gare in archivio non hanno un
    tempo, e restano gare che l'atleta ha nuotato."""
    add_race(connection, "icron-senza-tempo", "2026-05-10", 3000, time_s=None)

    assert connection.execute("SELECT count(*) FROM personal_races").fetchone()[0] == 0
    assert connection.execute(
        "SELECT distance_m FROM counted_swims WHERE origin = 'race'"
    ).fetchone()[0] == 3000


def test_the_two_ways_of_linking_a_swim_become_one(connection):
    """Il collegamento arriva da `coach/gare-dichiarate.md` in
    `races.activity_id` e da `coach/correzioni-gare.md` in
    `race_quality.activity_id`: chi legge non deve conoscerle entrambe."""
    add_race(connection, "icron-a", "2026-05-10", 3000)
    correct(connection, "icron-a", verdict="linked", activity_id=42)
    add_race(connection, "dichiarata-b", "2026-05-11", 3000)
    connection.execute(
        "UPDATE races SET activity_id = 99 WHERE race_id = 'dichiarata-b'")

    collegamenti = dict(connection.execute(
        "SELECT race_id, activity_id FROM canonical_races").fetchall())

    assert collegamenti == {"icron-a": 42, "dichiarata-b": 99}
    assert connection.execute(
        "SELECT count(*) FROM counted_swims WHERE origin = 'race'").fetchone()[0] == 0
