"""Un'anteprima che vincola, invece di una che illustra.

## Cosa non funzionava

Le due scritture dell'app passavano da due route: una mostrava cosa sarebbe
stato scritto, l'altra scriveva. La seconda però non sapeva niente della prima.
Rileggeva i campi dal modulo, rifaceva la validazione da capo, e accettava lo
stesso gettone di processo che accetta ogni altro modulo.

Quattro conseguenze, tutte raggiungibili senza uscire dal browser dell'atleta:

1. l'anteprima si saltava — un `POST` diretto a ``…/conferma`` scriveva;
2. i campi potevano cambiare fra anteprima e conferma: si approvava un 400 in
   4:35 e si scriveva un 400 in 3:35;
3. ricaricare la pagina di conferma scriveva la riga una seconda volta;
4. si annotava una seduta inesistente: la nota finiva nel diario e la risposta
   era 404.

Il gettone di processo difende dal CSRF, e quello funziona. Non difendeva da
questi, perché non era legato a **cosa** si stava confermando.

## Il gettone di anteprima

Alla conferma non viaggiano più i campi: viaggia un identificativo opaco, e i
campi stanno qui, dalla parte del server, esattamente come l'anteprima li ha
mostrati. Non c'è niente da manomettere, perché non c'è niente da rimandare.

Un identificativo casuale conservato dal server è più forte di un gettone
firmato: un gettone firmato è valido finché non scade e chiunque lo abbia in
mano lo può rigiocare, mentre questo si consuma quando viene speso. Firmare
servirebbe se il server non potesse ricordare — qui ricorda, ed è un processo
solo con una persona sola davanti.

## Perché scade

Mezz'ora. Un'anteprima aperta ieri e confermata oggi conferma qualcosa che
l'atleta non sta più guardando; e ``date.today()`` nel frattempo può essere
cambiato, il che renderebbe valida una data che al momento dell'anteprima era
nel futuro.

## Perché il secondo invio non è un errore

Ricaricare la pagina di conferma è il gesto più naturale del mondo. Il gettone
speso non viene dimenticato: resta con il proprio esito, così il secondo invio
rivede *«scritto in coach/riferimenti.md»* invece di un rifiuto. Scrive una
volta sola e lo dice una volta sola — che è quello che l'atleta si aspetta.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Il nome del campo nascosto che porta il gettone dell'anteprima. In italiano
# come tutto ciò che l'atleta potrebbe leggere guardando il sorgente della
# pagina, e diverso da quello del gettone antifalsificazione: sono due difese
# distinte e confonderle vorrebbe dire poterne dimenticare una.
FIELD = "conferma"

# Quanto vale un'anteprima. Il tempo di leggerla, non il tempo di dimenticarla.
VALID_FOR = timedelta(minutes=30)

# Quante conferme già spese si ricordano, per riconoscere un doppio invio.
# Sono due moduli in tutto: qualunque numero oltre la decina è già generoso.
REMEMBERED = 32


class Rejected(Exception):
    """La conferma non corrisponde a nessuna anteprima valida."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Pending:
    """Cosa l'atleta ha visto, in attesa che dica di sì."""

    kind: str            # "riferimento" oppure "nota"
    payload: dict        # i campi già validati, nella forma esatta mostrata
    issued_at: datetime


@dataclass
class _Store:
    """Le anteprime in attesa e quelle già spese, di questo processo.

    In memoria e non su disco: un'anteprima non sopravvive a un riavvio, e non
    deve. Il modulo si riapre e si ricompila in dieci secondi.
    """

    pending: dict = field(default_factory=dict)
    spent: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def clear(self) -> None:
        with self.lock:
            self.pending.clear()
            self.spent.clear()


STORE = _Store()


def issue(kind: str, payload: dict, now: datetime | None = None) -> str:
    """Registra ciò che l'anteprima sta mostrando e restituisce il suo gettone."""
    token = secrets.token_urlsafe(24)
    with STORE.lock:
        _forget_expired(now or datetime.now())
        STORE.pending[token] = Pending(kind=kind, payload=dict(payload),
                                       issued_at=now or datetime.now())
    return token


def redeem(kind: str, token: str, now: datetime | None = None) -> Pending:
    """Consuma un'anteprima. Una volta sola, e solo se è ancora la sua.

    Solleva ``Rejected`` con una frase leggibile: le tre ragioni per cui una
    conferma non vale — mai vista, scaduta, già spesa — sono tre situazioni
    diverse per chi le legge, e vanno dette diverse.
    """
    adesso = now or datetime.now()
    with STORE.lock:
        # La pulizia viene **dopo** la ricerca: buttare via le scadute prima
        # farebbe dire «questa anteprima non esiste» a chi invece ne ha una
        # scaduta, e sono due frasi che portano a due gesti diversi.
        if token in STORE.spent:
            raise AlreadyConfirmed(STORE.spent[token])

        attesa = STORE.pending.get(token)
        if attesa is None:
            raise Rejected(
                "Questa conferma non corrisponde a nessuna anteprima. Le "
                "scritture passano sempre dalla schermata che mostra cosa "
                "verrà scritto: torna indietro e ricomincia da lì.")
        if attesa.kind != kind:
            raise Rejected(
                "Questa conferma appartiene a un altro modulo. Torna indietro "
                "e ricomincia dall'anteprima giusta.")
        if adesso - attesa.issued_at > VALID_FOR:
            del STORE.pending[token]
            raise Rejected(
                "L'anteprima è di più di mezz'ora fa. Ricontrolla i dati e "
                "confermala di nuovo: così sei sicuro di approvare quello che "
                "stai guardando adesso.")

        del STORE.pending[token]
        _forget_expired(adesso)
        return attesa


def remember(token: str, outcome: str) -> None:
    """Ricorda com'è finita, così un secondo invio rivede l'esito e non scrive."""
    with STORE.lock:
        STORE.spent[token] = outcome
        while len(STORE.spent) > REMEMBERED:
            STORE.spent.pop(next(iter(STORE.spent)))


class AlreadyConfirmed(Exception):
    """Questa conferma è già stata scritta. Non è un errore: è un doppio invio."""

    def __init__(self, outcome: str):
        super().__init__(outcome)
        self.outcome = outcome


def _forget_expired(now: datetime) -> None:
    """Va chiamata con il lock già preso."""
    scadute = [t for t, p in STORE.pending.items() if now - p.issued_at > VALID_FOR]
    for token in scadute:
        del STORE.pending[token]
