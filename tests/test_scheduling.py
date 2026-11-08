"""L'aggiornamento automatico dei dati.

I test non registrano attività pianificate vere: sostituiscono la chiamata a
``schtasks`` e verificano che le si passi il comando giusto, che un rifiuto di
Windows non venga nascosto, e che il registro delle esecuzioni resti leggibile.
"""

from datetime import datetime, timedelta

import pytest

from garmin_coach import scheduling


class FakePython:
    """Un percorso che dice se esiste, senza toccare il disco."""

    def __init__(self, exists=True):
        self._exists = exists

    def exists(self):
        return self._exists

    def __str__(self):
        return r"C:\progetto\.venv\Scripts\pythonw.exe"


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_run(arguments):
        recorded.append(arguments)
        return FakeResult()

    monkeypatch.setattr(scheduling, "_run", fake_run)
    monkeypatch.setattr(scheduling, "PYTHON", FakePython())
    return recorded


def test_install_asks_windows_for_three_runs_a_day(calls):
    hours = scheduling.install()

    assert hours == "06:30, 14:30, 22:30"
    arguments = calls[0]
    assert "/Create" in arguments
    # `update` e non `sync`: il sync da solo porta i riepiloghi e lascia fuori
    # il dettaglio. Al 24/08/2026 questo significava 36 nuotate su 36
    # successive all'export senza un lap — l'intera preparazione verso place22
    # invisibile a ogni analisi che guardi dentro una seduta.
    assert "garmin_coach update" in " ".join(arguments)
    assert arguments[arguments.index("/MO") + 1] == "8"


def test_install_without_python_says_so(monkeypatch):
    monkeypatch.setattr(scheduling, "PYTHON", FakePython(exists=False))
    with pytest.raises(scheduling.SchedulerUnavailable, match="Python"):
        scheduling.install()


def test_a_refusal_from_windows_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(scheduling, "PYTHON", FakePython())
    monkeypatch.setattr(scheduling, "_run",
                        lambda _a: FakeResult(1, stderr="ERRORE: accesso negato."))
    with pytest.raises(scheduling.SchedulerUnavailable, match="accesso negato"):
        scheduling.install()


def test_removing_what_is_not_there_is_not_an_error(monkeypatch):
    monkeypatch.setattr(scheduling, "_run", lambda _a: FakeResult(1))
    assert scheduling.remove() is False


def test_every_sync_leaves_a_trace(monkeypatch, tmp_path):
    log = tmp_path / "sync.log"
    monkeypatch.setattr(scheduling, "LOG", log)
    monkeypatch.setattr(scheduling.paths, "ensure_data_dirs", lambda: None)

    scheduling.append_to_log("sync 2026-08-18 → 2026-08-21: 8 attività\n  scale: ok")

    last = scheduling.last_logged_run()
    assert last is not None
    assert "8 attività" in last.line
    assert "scale: ok" in last.line, "il riepilogo su più righe resta leggibile"
    assert abs(last.when - datetime.now(last.when.tzinfo)) < timedelta(minutes=1)


def test_a_log_that_says_nothing_reports_nothing(monkeypatch, tmp_path):
    """Un registro illeggibile non deve diventare una data inventata."""
    log = tmp_path / "sync.log"
    log.write_text("righe senza forma\naltre righe\n", encoding="utf-8")
    monkeypatch.setattr(scheduling, "LOG", log)
    assert scheduling.last_logged_run() is None
