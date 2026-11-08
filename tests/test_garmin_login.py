"""La gestione della connessione a Garmin.

Il punto delicato non è l'accesso riuscito: è quello fallito. Garmin blocca per
numero di richieste, e riprovare subito allunga il blocco invece di superarlo.
Questi test verificano che il sistema si trattenga da solo.
"""

from datetime import datetime, timedelta, timezone

import pytest

from garmin_coach import paths
from garmin_coach.ingest import garmin_login


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Ogni test lavora su una cartella dati sua."""
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "STAGING", tmp_path / "staging")
    monkeypatch.setattr(garmin_login, "TOKEN_STORE", tmp_path / "garmin_token")
    monkeypatch.setattr(garmin_login, "ATTEMPTS_LOG",
                        tmp_path / "garmin_login_attempts.json")
    return tmp_path


def test_no_attempt_no_cooldown(isolated):
    assert garmin_login.cooldown_remaining() is None
    assert garmin_login.status().can_try_now is True


def test_rate_limit_starts_a_long_cooldown(isolated):
    garmin_login.record_attempt("rate_limited")
    pending = garmin_login.cooldown_remaining()

    assert pending is not None
    remaining, reason = pending
    assert remaining <= garmin_login.COOLDOWN_AFTER_RATE_LIMIT
    assert remaining > timedelta(minutes=50)
    assert "numero di richieste" in reason


def test_ordinary_failure_starts_a_short_cooldown(isolated):
    garmin_login.record_attempt("credenziali o rete")
    remaining, _ = garmin_login.cooldown_remaining()
    assert remaining <= garmin_login.COOLDOWN_AFTER_FAILURE


def test_success_clears_the_cooldown(isolated):
    garmin_login.record_attempt("rate_limited")
    garmin_login.record_attempt("ok")
    assert garmin_login.cooldown_remaining() is None


def test_cooldown_expires_with_time(isolated, monkeypatch):
    garmin_login.record_attempt("rate_limited")
    later = datetime.now(timezone.utc) + timedelta(hours=2)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(garmin_login, "datetime", Clock)
    assert garmin_login.cooldown_remaining() is None


def test_login_refuses_during_cooldown(isolated):
    garmin_login.record_attempt("rate_limited")
    with pytest.raises(garmin_login.CooldownActive) as error:
        garmin_login.log_in("chi@esempio.it", "segreta")
    assert "Riprovare fra circa" in str(error.value)


def test_force_bypasses_the_cooldown(isolated, monkeypatch):
    """Il blocco è una protezione, non una prigione: se l'atleta sa che il
    limite è passato deve poter forzare."""
    garmin_login.record_attempt("rate_limited")
    attempted = {}

    class FakeGarmin:
        def __init__(self, **kwargs):
            attempted["chiamato"] = True

        def login(self):
            return None

        class garth:
            @staticmethod
            def dump(path):
                pass

    import garminconnect
    monkeypatch.setattr(garminconnect, "Garmin", FakeGarmin)
    garmin_login.log_in("chi@esempio.it", "segreta", force=True)
    assert attempted.get("chiamato") is True


def test_attempts_log_never_contains_credentials(isolated):
    garmin_login.record_attempt("rate_limited")
    testo = garmin_login.ATTEMPTS_LOG.read_text(encoding="utf-8")

    assert "password" not in testo.lower()
    assert "@" not in testo          # nessuna email
    assert "rate_limited" in testo


def test_attempts_log_stays_short(isolated):
    for _ in range(25):
        garmin_login.record_attempt("credenziali o rete")
    import json
    entries = json.loads(garmin_login.ATTEMPTS_LOG.read_text(encoding="utf-8"))
    assert len(entries) == garmin_login.ATTEMPTS_KEPT


def test_status_says_what_to_do_without_touching_the_network(isolated):
    state = garmin_login.status()
    assert state.connected is False
    assert "Nessun tentativo" in state.headline()

    garmin_login.record_attempt("rate_limited")
    assert "Attendere" in garmin_login.status().headline()


def test_connect_client_points_to_the_guided_script(isolated):
    with pytest.raises(RuntimeError) as error:
        garmin_login.connect_client()
    assert "garmin_coach connect" in str(error.value)


# ── Il 429 nascosto ─────────────────────────────────────────────────────────
# Garmin puo respingere le prime strategie con 429 e far fallire l'ultima con
# un errore di autenticazione. Senza riconoscerlo, il freno durerebbe due
# minuti invece di un'ora e l'atleta continuerebbe a bussare a una porta chiusa.

def test_rate_limit_recognised_in_the_cause_chain():
    root = ConnectionError("Mobile login returned 429 - IP rate limited by Garmin")
    final = RuntimeError("Widget MFA failed: Enter MFA code for login")
    final.__cause__ = root
    assert garmin_login.looks_rate_limited(final) is True


def test_ordinary_error_is_not_mistaken_for_a_rate_limit():
    assert garmin_login.looks_rate_limited(ValueError("password errata")) is False


def test_rate_limit_seen_only_in_the_log_still_counts(isolated, monkeypatch):
    import logging

    import garminconnect

    class FailsAfterRateLimit:
        def __init__(self, **kwargs):
            pass

        def login(self):
            logging.getLogger("garminconnect").warning(
                "mobile+cffi returned 429: rate limited by Garmin")
            raise garminconnect.GarminConnectAuthenticationError(
                "Widget MFA failed: Enter MFA code for login")

    monkeypatch.setattr(garminconnect, "Garmin", FailsAfterRateLimit)
    with pytest.raises(garmin_login.RateLimited):
        garmin_login.log_in("chi@esempio.it", "segreta")

    remaining, reason = garmin_login.cooldown_remaining()
    assert remaining > timedelta(minutes=50), "deve scattare l'attesa lunga"
    assert "numero di richieste" in reason


# ── Salvataggio del token ───────────────────────────────────────────────────
# Un accesso riuscito buttato via per un attributo rinominato costa il codice
# di verifica, che e monouso. Vale la pena provare piu nomi.

class _Holder:
    def __init__(self, fails=False):
        self.fails = fails
        self.written = None

    def dump(self, path):
        if self.fails:
            raise RuntimeError("non scrivibile")
        self.written = path


def test_token_saved_via_current_attribute(isolated):
    class NewLibrary:
        def __init__(self):
            self.client = _Holder()

    client = NewLibrary()
    garmin_login._save_tokens(client, isolated / "token")
    assert client.client.written is not None


def test_token_saved_via_legacy_attribute(isolated):
    class OldLibrary:
        def __init__(self):
            self.garth = _Holder()

    client = OldLibrary()
    garmin_login._save_tokens(client, isolated / "token")
    assert client.garth.written is not None


def test_unknown_shape_explains_instead_of_crashing(isolated):
    class Alien:
        pass

    with pytest.raises(RuntimeError) as error:
        garmin_login._save_tokens(Alien(), isolated / "token")
    message = str(error.value)
    assert "Accesso riuscito" in message
    assert "upgrade garminconnect" in message


def test_first_working_attribute_wins(isolated):
    class Both:
        def __init__(self):
            self.client = _Holder(fails=True)
            self.garth = _Holder()

    client = Both()
    garmin_login._save_tokens(client, isolated / "token")
    assert client.garth.written is not None, "deve ripiegare sul secondo nome"
