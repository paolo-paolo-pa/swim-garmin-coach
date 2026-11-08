"""Il muro fra il progetto e Garmin (D3).

La Macro-proposta 3 chiedeva un'allow-list dei soli comandi di lettura. Questi
test verificano che sia un muro e non una convenzione: che i metodi di scrittura
**non siano raggiungibili**, non che ci si ricordi di non chiamarli.
"""

import pytest

from garmin_coach.ingest import garmin_read_only


class FakeClient:
    """Un client con la stessa forma di quello vero: legge e scrive."""

    def __init__(self):
        self.deleted = []

    def get_activities_by_date(self, start, end):
        return [{"activityId": 1, "startTimeGMT": f"{start} 08:00:00"}]

    def get_user_summary(self, day):
        return {"restingHeartRate": 52, "giorno": day}

    def get_sleep_data(self, day):
        return {"dailySleepDTO": {"sleepTimeSeconds": 27000}}

    def get_hrv_data(self, day):
        return {"hrvSummary": {"lastNightAvg": 44}}

    def get_full_name(self):
        return "Paolo"

    def download_activity(self, activity_id, dl_fmt=None):
        """Il file originale di un'attività.

        Nel contratto dal 24/08/2026: senza, le sedute successive all'export
        non possono avere un dettaglio, perché i FIT arrivavano soltanto dagli
        ZIP dell'export — fermi al 4 luglio 2026.
        """
        return b"PK\x03\x04finto-zip"

    # Le due che non devono mai partire da qui.
    def delete_activity(self, activity_id):
        self.deleted.append(activity_id)
        return "cancellata"

    def upload_workout(self, workout):
        return "caricato"


@pytest.fixture
def wrapped(monkeypatch):
    """Il client dietro il muro, senza scrivere snapshot su disco."""
    return garmin_read_only.wrap(FakeClient(), capture=False)


def test_reading_works(wrapped):
    assert wrapped.get_user_summary("2026-08-20")["restingHeartRate"] == 52
    assert wrapped.get_full_name() == "Paolo"


def test_deleting_an_activity_is_not_reachable(wrapped):
    """Non «non va chiamato»: non esiste da questa parte del muro."""
    with pytest.raises(garmin_read_only.WriteAttempted, match="scrive su Garmin"):
        wrapped.delete_activity(12345)


def test_uploading_a_workout_is_not_reachable(wrapped):
    with pytest.raises(garmin_read_only.WriteAttempted):
        wrapped.upload_workout({})


def test_the_underlying_client_is_never_touched_by_a_refused_call(wrapped):
    with pytest.raises(garmin_read_only.WriteAttempted):
        wrapped.delete_activity(999)
    assert wrapped.client.deleted == [], "la chiamata non deve arrivare al client"


def test_a_read_method_outside_the_contract_is_refused_too(wrapped):
    """L'allow-list non è «tutto tranne le scritture»: è una lista chiusa.
    Un metodo di lettura nuovo è una decisione, non una comodità."""
    with pytest.raises(garmin_read_only.NotAllowed, match="contratto"):
        wrapped.get_devices()


def test_the_error_says_what_is_available(wrapped):
    with pytest.raises(garmin_read_only.NotAllowed) as caught:
        wrapped.get_qualcosa_di_inventato()
    assert "get_sleep_data" in str(caught.value)


def test_every_response_is_saved_before_being_read(monkeypatch, tmp_path):
    """Criterio D2: una risposta che esiste solo come riga già trasformata non
    è rigiocabile. Se domani si scopre che un campo era letto male, l'unico
    rimedio sarebbe richiedere tutto a Garmin."""
    from garmin_coach.ingest import source_catalog
    monkeypatch.setattr(source_catalog, "RAW", tmp_path / "raw")
    monkeypatch.setattr(source_catalog.paths, "ROOT", tmp_path)

    client = garmin_read_only.wrap(FakeClient())
    client.get_user_summary("2026-08-20")

    saved = list((tmp_path / "raw").rglob("*.json"))
    assert len(saved) == 1
    assert "2026-08-20" in str(saved[0])
    assert "restingHeartRate" in saved[0].read_text(encoding="utf-8")
    assert len(client.captured[0].sha256) == 64


def test_the_probe_reports_what_the_library_really_offers():
    capabilities = garmin_read_only.probe(FakeClient())
    assert capabilities.usable
    assert set(capabilities.available) == set(garmin_read_only.ALLOWED)


def test_a_library_missing_a_method_is_reported_not_discovered_mid_sync():
    """Accorgersene a metà di un sync significa lasciare i dati a metà."""

    class Older:
        def get_activities_by_date(self, start, end):
            return []

    capabilities = garmin_read_only.probe(Older())
    assert not capabilities.usable
    assert "get_sleep_data" in capabilities.missing
    assert "storico locale resta interrogabile" in capabilities.explain()
