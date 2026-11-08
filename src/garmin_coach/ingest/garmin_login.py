"""La connessione a Garmin Connect: stato, attesa obbligatoria, accesso.

Separato dal download dei dati perché è un problema diverso e più delicato.
Garmin blocca per numero di richieste, non per credenziali sbagliate, e ogni
tentativo inutile peggiora la situazione invece di migliorarla.

Tre principi:

1. **Non bussare se è inutile.** Se un tentativo è fallito da poco, il modulo si
   rifiuta di riprovare e dice quanto manca. È la protezione che serviva la prima
   volta e non c'era.
2. **Dire sempre a che punto siamo.** ``status()`` risponde senza contattare
   Garmin: mai una richiesta di rete solo per sapere come stiamo messi.
3. **Le credenziali non si conservano.** Passano dall'atleta alla libreria
   Garmin. Sul disco resta un token, escluso da Git.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths

TOKEN_STORE = paths.DATA / "garmin_token"
ATTEMPTS_LOG = paths.DATA / "garmin_login_attempts.json"

# Quanto aspettare prima di riprovare, per esito del tentativo precedente.
# Dopo un 429 l'attesa è lunga: è un blocco per numero di richieste e riprovare
# subito lo rinnova. Dopo un errore di credenziali basta poco, perché il
# problema è la password e non il numero di tentativi.
COOLDOWN_AFTER_RATE_LIMIT = timedelta(minutes=60)
COOLDOWN_AFTER_FAILURE = timedelta(minutes=2)

# Quanti tentativi conserva il registro. Serve a spiegare cosa è successo, non
# a fare statistica.
ATTEMPTS_KEPT = 10


class RateLimited(RuntimeError):
    """Garmin ha risposto 429: troppe richieste dallo stesso indirizzo IP.

    Non è un problema di credenziali. Ogni nuovo tentativo estende il blocco
    invece di superarlo: l'unica mossa utile è aspettare.
    """


class CooldownActive(RuntimeError):
    """Un tentativo recente è fallito: riprovare ora peggiorerebbe le cose."""

    def __init__(self, remaining: timedelta, reason: str) -> None:
        self.remaining = remaining
        self.reason = reason
        minutes = max(1, int(remaining.total_seconds() // 60))
        super().__init__(
            f"Ultimo tentativo fallito ({reason}). "
            f"Riprovare fra circa {minutes} minuti.")


# Un solo tentativo per strategia invece dei tre di default. La libreria prova
# più strategie in sequenza: con i tre predefiniti un solo comando di accesso
# poteva produrre sei richieste, ed è così che si finisce nel rate limit invece
# di superarlo.
LOGIN_ATTEMPTS = 1


@dataclass(frozen=True)
class Status:
    connected: bool
    token_path: Path
    last_attempt: datetime | None
    last_outcome: str | None
    cooldown_remaining: timedelta | None

    @property
    def can_try_now(self) -> bool:
        return self.cooldown_remaining is None

    def headline(self) -> str:
        if self.connected:
            return "Connesso a Garmin Connect."
        if self.cooldown_remaining:
            minutes = max(1, int(self.cooldown_remaining.total_seconds() // 60))
            return f"Non connesso. Attendere ancora circa {minutes} minuti."
        if self.last_outcome:
            return f"Non connesso. Ultimo tentativo: {self.last_outcome}."
        return "Non connesso. Nessun tentativo di accesso finora."


# Il 429 non arriva sempre come eccezione. La libreria prova più strategie in
# sequenza: le prime possono essere respinte con 429 e finire soltanto nel log,
# mentre l'eccezione finale parla d'altro — tipicamente di autenticazione dopo
# un codice di verifica che non poteva funzionare. Senza guardare il log, il
# tentativo verrebbe classificato come "password sbagliata" e il freno
# durerebbe due minuti invece di un'ora.
_RATE_LIMIT_PATTERN = re.compile(r"429|rate limit|toomanyrequests", re.IGNORECASE)


class _RateLimitWatcher(logging.Handler):
    """Ascolta i messaggi della libreria durante l'accesso e nota i 429."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.seen = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _RATE_LIMIT_PATTERN.search(record.getMessage()):
                self.seen = True
        except Exception:  # noqa: BLE001 - un handler non deve mai far fallire il chiamante
            pass


@contextlib.contextmanager
def _watch_for_rate_limit():
    watcher = _RateLimitWatcher()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(watcher)
    if previous_level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    try:
        yield watcher
    finally:
        root.removeHandler(watcher)
        root.setLevel(previous_level)


def looks_rate_limited(error: BaseException) -> bool:
    """Vero se il 429 compare nell'errore o in una delle sue cause."""
    seen = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _RATE_LIMIT_PATTERN.search(str(current)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _read_attempts() -> list[dict]:
    if not ATTEMPTS_LOG.exists():
        return []
    try:
        return json.loads(ATTEMPTS_LOG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def record_attempt(outcome: str) -> None:
    """Annota l'esito di un tentativo. Nessuna credenziale finisce qui dentro:
    solo l'ora e una parola."""
    paths.ensure_data_dirs()
    attempts = _read_attempts()
    attempts.append({"at": datetime.now(timezone.utc).isoformat(), "outcome": outcome})
    ATTEMPTS_LOG.write_text(
        json.dumps(attempts[-ATTEMPTS_KEPT:], indent=2), encoding="utf-8")


def cooldown_remaining() -> tuple[timedelta, str] | None:
    """Quanto manca prima che abbia senso riprovare, e perché."""
    attempts = _read_attempts()
    if not attempts:
        return None
    last = attempts[-1]
    if last.get("outcome") == "ok":
        return None
    try:
        when = datetime.fromisoformat(last["at"])
    except (KeyError, ValueError):
        return None

    outcome = last.get("outcome", "errore")
    wait = (COOLDOWN_AFTER_RATE_LIMIT if outcome == "rate_limited"
            else COOLDOWN_AFTER_FAILURE)
    elapsed = datetime.now(timezone.utc) - when
    if elapsed >= wait:
        return None
    reason = ("blocco per numero di richieste" if outcome == "rate_limited"
              else outcome)
    return wait - elapsed, reason


def has_token() -> bool:
    return TOKEN_STORE.exists() and any(TOKEN_STORE.iterdir())


def status() -> Status:
    """Come siamo messi. Non contatta Garmin: risponde da quello che c'è su disco."""
    attempts = _read_attempts()
    last = attempts[-1] if attempts else {}
    when = None
    if last.get("at"):
        try:
            when = datetime.fromisoformat(last["at"])
        except ValueError:
            when = None
    cooldown = cooldown_remaining()
    return Status(
        connected=has_token(),
        token_path=TOKEN_STORE,
        last_attempt=when,
        last_outcome=last.get("outcome"),
        cooldown_remaining=cooldown[0] if cooldown else None,
    )


def connect_client():
    """Apre la sessione Garmin usando il token già salvato.

    Non accetta credenziali. Se il token non c'è, dice quale comando eseguire.
    """
    try:
        from garminconnect import Garmin
    except ImportError as error:  # pragma: no cover - dipende dall'ambiente
        raise RuntimeError(
            "La libreria 'garminconnect' non è installata. "
            "Installarla con: pip install garminconnect") from error

    if not has_token():
        raise RuntimeError(
            "Nessun accesso Garmin salvato. Eseguire una volta sola:\n"
            "    garmin_coach connect\n"
            "Le credenziali non vengono conservate: resta solo un token locale.")

    client = Garmin()
    client.login(tokenstore=str(TOKEN_STORE))
    return client


def _save_tokens(client, destination: Path) -> None:
    """Scrive su disco il token ottenuto con l'accesso.

    Il nome dell'oggetto che conserva i token è cambiato fra le versioni della
    libreria: era ``client.garth``, ora è ``client.client``. Provarli in ordine
    costa nulla ed evita che un accesso riuscito venga buttato via per un
    attributo rinominato — è successo, e il codice di verifica era già stato
    consumato.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for attribute in ("client", "garth"):
        holder = getattr(client, attribute, None)
        dump = getattr(holder, "dump", None)
        if callable(dump):
            try:
                dump(str(destination))
                return
            except Exception as error:  # noqa: BLE001
                errors.append(f"{attribute}.dump: {type(error).__name__}")
    raise RuntimeError(
        "Accesso riuscito ma il token non è stato salvato: nessun modo noto di "
        "scriverlo in questa versione della libreria garminconnect. "
        + ("Tentativi: " + "; ".join(errors) if errors else "")
        + " Aggiornare la libreria con: pip install --upgrade garminconnect")


def log_in(email: str, password: str, mfa_prompt=None,
           force: bool = False) -> str:
    """Primo accesso. Le credenziali passano di qui e non vengono mai scritte.

    Si rifiuta di provare se un tentativo recente è fallito, a meno che non gli
    si dica esplicitamente di forzare.
    """
    from garminconnect import Garmin, GarminConnectTooManyRequestsError

    if not force:
        pending = cooldown_remaining()
        if pending:
            raise CooldownActive(*pending)

    paths.ensure_data_dirs()
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    client = Garmin(email=email, password=password, prompt_mfa=mfa_prompt,
                    retry_attempts=LOGIN_ATTEMPTS)
    try:
        with _watch_for_rate_limit() as watcher:
            client.login()
    except GarminConnectTooManyRequestsError as error:
        record_attempt("rate_limited")
        raise RateLimited(str(error)) from error
    except Exception as error:
        if watcher.seen or looks_rate_limited(error):
            record_attempt("rate_limited")
            raise RateLimited(
                "Garmin ha respinto l'accesso per numero di richieste (429). "
                "L'errore finale parla d'altro, ma la causa è quella: il codice "
                "di verifica non poteva funzionare su una sessione già bloccata."
            ) from error
        record_attempt("credenziali o rete")
        raise

    _save_tokens(client, TOKEN_STORE)
    record_attempt("ok")
    return str(TOKEN_STORE)


def verify_connection() -> dict:
    """Una sola chiamata leggera per confermare che il token funziona davvero.

    Un token salvato non è una connessione funzionante: senza questa prova si
    scoprirebbe il problema solo al primo sync.
    """
    client = connect_client()
    name = client.get_full_name()
    return {"ok": True, "account": name}
