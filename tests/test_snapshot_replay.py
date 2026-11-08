"""Rigiocare le catture invece di richiederle a Garmin (D2, D6).

Il criterio dice: *il database si ricostruisce senza rete da export + snapshot
già acquisiti*. Questi test verificano la metà che riguarda gli snapshot.
"""

import json

import pytest

from garmin_coach.ingest.snapshot_replay import SnapshotClient


@pytest.fixture
def catture(tmp_path):
    """Due giorni di catture che si sovrappongono, come succede davvero: il
    sync riscarica sempre qualche giorno all'indietro perché Garmin corregge i
    dati del giorno prima."""
    def scrivi(day, endpoint, payload):
        folder = tmp_path / day
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{endpoint}.json").write_text(
            json.dumps(payload), encoding="utf-8")

    scrivi("2026-08-18", "get_activities_by_date", [
        {"activityId": 1, "distance": 3000.0},
        {"activityId": 2, "distance": 2000.0},
    ])
    # La seconda cattura rivede l'attività 2 e ne aggiunge una nuova.
    scrivi("2026-08-20", "get_activities_by_date", [
        {"activityId": 2, "distance": 2100.0},
        {"activityId": 3, "distance": 1500.0},
    ])
    scrivi("2026-08-18", "get_user_summary", {"restingHeartRate": 52})
    scrivi("2026-08-18", "get_sleep_data", {"dailySleepDTO": {"sleepTimeSeconds": 27000}})
    return SnapshotClient(tmp_path)


def test_activities_are_read_from_disk(catture):
    found = catture.get_activities_by_date("2026-08-01", "2026-08-31")
    assert {a["activityId"] for a in found} == {1, 2, 3}


def test_a_reviewed_activity_keeps_its_latest_version(catture):
    """Garmin corregge i dati del giorno prima. Fra due catture della stessa
    attività vince l'ultima vista, che è la più corretta."""
    found = {a["activityId"]: a for a in
             catture.get_activities_by_date("2026-08-01", "2026-08-31")}
    assert found[2]["distance"] == 2100.0


def test_the_interval_is_respected(catture):
    """Rigiocare tutto quando si chiede una finestra riscriverebbe giorni che
    il chiamante non ha chiesto."""
    found = catture.get_activities_by_date("2026-08-19", "2026-08-31")
    assert {a["activityId"] for a in found} == {2, 3}


def test_health_is_served_day_by_day(catture):
    assert catture.get_user_summary("2026-08-18")["restingHeartRate"] == 52
    assert catture.get_sleep_data("2026-08-18")["dailySleepDTO"]["sleepTimeSeconds"] == 27000


def test_a_day_never_captured_is_absent_not_invented(catture):
    """Regola Aurea n.5: un giorno senza cattura non diventa un giorno vuoto
    con valori a zero. Semplicemente non c'è."""
    assert catture.get_user_summary("2026-01-01") is None
    assert catture.get_hrv_data("2026-08-18") is None


def test_no_captures_at_all_is_not_an_error(tmp_path):
    """Su un'installazione che non ha mai sincronizzato la ricostruzione deve
    funzionare lo stesso, con il solo export."""
    client = SnapshotClient(tmp_path / "mai-esistita")
    assert client.get_activities_by_date("2026-01-01", "2026-12-31") == []
    assert client.coverage()["days"] == 0


def test_the_coverage_says_what_can_be_rebuilt(catture):
    coverage = catture.coverage()
    assert coverage["days"] == 2
    assert coverage["first"] == "2026-08-18"
    assert coverage["last"] == "2026-08-20"


def test_there_is_no_way_to_write_through_this_client(catture):
    """Non c'è niente su cui scrivere: è una proprietà della forma, non una
    regola da ricordare."""
    for name in ("delete_activity", "upload_workout", "add_weigh_in"):
        assert not hasattr(catture, name)


def test_replaying_the_same_captures_twice_gives_the_same_answer(catture):
    """È la proprietà su cui poggia il digest canonico di D6."""
    first = catture.get_activities_by_date("2026-08-01", "2026-08-31")
    second = catture.get_activities_by_date("2026-08-01", "2026-08-31")
    assert first == second
