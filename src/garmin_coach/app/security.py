"""Perché un server che gira sul tuo computer ha comunque bisogno di difendersi.

## Il rischio vero, che non è ipotetico

Mentre l'app è aperta su ``127.0.0.1:8765``, il browser sta anche visitando il
resto del web. Una pagina qualunque può contenere un modulo che fa `POST` verso
`http://127.0.0.1:8765/gare/riferimenti/conferma` e inviarlo con JavaScript. Il
browser lo esegue: la richiesta parte dal computer giusto, quindi il server la
riceve come se l'avesse fatta l'atleta.

Non è un attacco esotico — è il motivo per cui esiste la protezione CSRF, e vale
identico per un server locale. Qui l'unica cosa che si può fare è scrivere in
``coach/``, quindi il danno massimo è un riferimento falso nel file dei tempi.
Basta perché valga la pena impedirlo: un tempo inventato che entra fra i
riferimenti confermati corrompe esattamente la cosa che questo progetto tiene
più al sicuro, cioè la distinzione fra un fatto e una supposizione.

## Le due difese, che servono entrambe

1. **Un gettone in ogni modulo.** Generato all'avvio, diverso a ogni
   esecuzione. Una pagina esterna non può leggerlo: la politica della stessa
   origine le impedisce di vedere il corpo delle nostre risposte.
2. **Il controllo dell'origine.** I browser mandano ``Origin`` su ogni `POST`
   fra siti diversi. Se non è il nostro, la richiesta non viene da qui.

Da sole basterebbero quasi. Insieme coprono anche il caso in cui una delle due
venga aggirata da un browser che si comporta in modo insolito.

## Nessuna sessione, nessun cookie

Non c'è login, non c'è un utente da riconoscere: c'è una persona sola davanti al
proprio computer. Aggiungere sessioni significherebbe aggiungere scadenze, e
scadenze significa un'app che a volte dice «rifai l'accesso» a chi è l'unico
essere umano che potrà mai aprirla.
"""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

from starlette.requests import Request

# Il gettone di questa esecuzione. Cambia a ogni avvio: un modulo lasciato
# aperto da ieri non funziona più, e va bene così — è un modulo, non un
# documento.
TOKEN = secrets.token_urlsafe(32)

# Il nome del campo nascosto. In italiano come tutto ciò che l'atleta potrebbe
# leggere guardando il sorgente della pagina.
FIELD = "gettone"

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class Rejected(Exception):
    """La richiesta non viene da questa applicazione."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _origin_is_ours(request: Request) -> bool:
    """Se la richiesta arriva da una nostra pagina.

    Si guarda ``Origin`` e, se manca, ``Referer``: alcuni browser mandano solo
    il secondo. Se mancano entrambi la richiesta **non** viene accettata sulla
    fiducia: un modulo nostro li manda sempre.
    """
    sorgente = request.headers.get("origin") or request.headers.get("referer")
    if not sorgente:
        return False
    try:
        pezzi = urlparse(sorgente)
    except ValueError:
        return False
    return pezzi.hostname in ALLOWED_HOSTS


def check(request: Request, form) -> None:
    """Lascia passare solo ciò che è partito da una pagina di questa app."""
    if not _origin_is_ours(request):
        raise Rejected(
            "Questa richiesta non è partita da una pagina di Garmin Coach. "
            "Se l'hai fatta tu, riapri la pagina e riprova.")
    inviato = str(form.get(FIELD, ""))
    # Confronto a tempo costante: qui non cambia molto, ma un confronto di
    # gettoni fatto con `==` è il genere di dettaglio che si copia altrove.
    if not hmac.compare_digest(inviato, TOKEN):
        raise Rejected(
            "Il modulo è scaduto: l'applicazione è stata riavviata da quando "
            "l'hai aperto. Ricarica la pagina e reinserisci i dati.")
