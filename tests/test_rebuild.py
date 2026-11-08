"""Ricostruzione, lock e digest canonico (D6).

La ricostruzione completa richiede l'export vero e dura minuti: quella si prova
a mano. Qui si provano le due cose da cui dipende la sua credibilità — che il
digest ignori ciò che deve cambiare e noti ciò che non deve, e che due scritture
non possano sovrapporsi.
"""

from datetime import datetime, timedelta

import duckdb
import pytest

from garmin_coach import rebuild
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _activity(con, activity_id, day, distance=3000.0, imported=None):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        "sport, is_swim, distance_m, source_object_id, imported_at) "
        "VALUES (?, ?, ?, 'lap_swimming', TRUE, ?, 'sha', ?)",
        [activity_id, datetime.combine(day, datetime.min.time()), day, distance,
         imported or datetime(2026, 8, 21)])


# ── Digest ─────────────────────────────────────────────────────────────────

def test_the_same_content_gives_the_same_digest():
    first = duckdb.connect(":memory:"); first.execute(SCHEMA)
    second = duckdb.connect(":memory:"); second.execute(SCHEMA)
    for con in (first, second):
        _activity(con, 1, datetime(2026, 6, 1).date())
        _activity(con, 2, datetime(2026, 6, 2).date())

    assert (rebuild.canonical_digest(first)["overall"]
            == rebuild.canonical_digest(second)["overall"])
    first.close(); second.close()


def test_the_order_of_insertion_does_not_change_the_digest():
    """Due ricostruzioni possono scrivere le stesse righe in ordine diverso.
    Se il digest cambiasse per questo, non direbbe niente sul contenuto."""
    first = duckdb.connect(":memory:"); first.execute(SCHEMA)
    second = duckdb.connect(":memory:"); second.execute(SCHEMA)
    _activity(first, 1, datetime(2026, 6, 1).date())
    _activity(first, 2, datetime(2026, 6, 2).date())
    _activity(second, 2, datetime(2026, 6, 2).date())
    _activity(second, 1, datetime(2026, 6, 1).date())

    assert (rebuild.canonical_digest(first)["overall"]
            == rebuild.canonical_digest(second)["overall"])
    first.close(); second.close()


def test_the_import_time_is_ignored():
    """`imported_at` DEVE cambiare fra due ricostruzioni: è un metadato
    sull'atto di importare, non sui dati importati. Includerlo farebbe fallire
    il confronto per il motivo sbagliato."""
    first = duckdb.connect(":memory:"); first.execute(SCHEMA)
    second = duckdb.connect(":memory:"); second.execute(SCHEMA)
    _activity(first, 1, datetime(2026, 6, 1).date(), imported=datetime(2026, 1, 1))
    _activity(second, 1, datetime(2026, 6, 1).date(), imported=datetime(2026, 8, 21))

    assert (rebuild.canonical_digest(first)["overall"]
            == rebuild.canonical_digest(second)["overall"])
    first.close(); second.close()


def test_a_changed_value_changes_the_digest():
    first = duckdb.connect(":memory:"); first.execute(SCHEMA)
    second = duckdb.connect(":memory:"); second.execute(SCHEMA)
    _activity(first, 1, datetime(2026, 6, 1).date(), distance=3000.0)
    _activity(second, 1, datetime(2026, 6, 1).date(), distance=3001.0)

    assert (rebuild.canonical_digest(first)["overall"]
            != rebuild.canonical_digest(second)["overall"])
    first.close(); second.close()


def test_a_missing_row_changes_the_digest(connection):
    _activity(connection, 1, datetime(2026, 6, 1).date())
    _activity(connection, 2, datetime(2026, 6, 2).date())
    before = rebuild.canonical_digest(connection)

    connection.execute("DELETE FROM activities WHERE activity_id = 2")
    after = rebuild.canonical_digest(connection)

    assert before["overall"] != after["overall"]
    assert rebuild.differences(before, after) == ["activities: da 2 a 1 righe"]


def test_the_differences_name_the_table_and_say_what_changed(connection):
    _activity(connection, 1, datetime(2026, 6, 1).date(), distance=3000.0)
    before = rebuild.canonical_digest(connection)

    connection.execute("UPDATE activities SET distance_m = 4000 WHERE activity_id = 1")
    changed = rebuild.differences(before, rebuild.canonical_digest(connection))

    assert changed == ["activities: stesse 1 righe, contenuto diverso"]


def test_the_run_log_is_left_out_of_the_digest(connection):
    """`ingest_runs` è per intero un registro di esecuzioni: due ricostruzioni
    ne hanno per forza righe diverse, ed è giusto così."""
    before = rebuild.canonical_digest(connection)
    connection.execute(
        "INSERT INTO ingest_runs (run_id, started_at, command) VALUES ('x', ?, 'test')",
        [datetime.now()])
    assert rebuild.canonical_digest(connection)["overall"] == before["overall"]


# ── Lock ───────────────────────────────────────────────────────────────────

@pytest.fixture
def lock_path(monkeypatch, tmp_path):
    target = tmp_path / "scrittura.lock"
    monkeypatch.setattr(rebuild, "LOCK", target)
    monkeypatch.setattr(rebuild.paths, "ensure_data_dirs", lambda: None)
    return target


def test_the_lock_is_released_when_the_work_ends(lock_path):
    with rebuild.single_writer("prova"):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_the_lock_is_released_even_when_the_work_fails(lock_path):
    """Un import fallito non deve lasciare il database bloccato per sempre."""
    with pytest.raises(ValueError):
        with rebuild.single_writer("prova"):
            raise ValueError("qualcosa è andato storto")
    assert not lock_path.exists()


def test_a_second_writer_is_refused_with_a_readable_reason(lock_path):
    with rebuild.single_writer("ricostruzione"):
        with pytest.raises(rebuild.DatabaseBusy) as caught:
            with rebuild.single_writer("sync"):
                pass
    messaggio = str(caught.value)
    assert "già in scrittura" in messaggio
    assert "ricostruzione" in messaggio, "deve dire chi ha il file"
    assert str(lock_path) in messaggio, "deve dire cosa rimuovere se serve"


def test_a_forgotten_lock_does_not_block_the_project_forever(lock_path):
    """Se un processo muore lasciando il lock, il progetto deve poter ripartire
    da solo: un blocco permanente sarebbe peggio del problema che previene."""
    import os
    lock_path.write_text("processo morto", encoding="utf-8")
    old = (datetime.now() - rebuild.STALE_LOCK_AFTER - timedelta(minutes=1)).timestamp()
    os.utime(lock_path, (old, old))

    with rebuild.single_writer("nuova esecuzione"):
        assert "nuova esecuzione" in lock_path.read_text(encoding="utf-8")
