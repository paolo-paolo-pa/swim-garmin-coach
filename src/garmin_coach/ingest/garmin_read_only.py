"""L'unico punto in cui il progetto parla con Garmin (D3).

## Perché esiste un muro

La libreria che usiamo — come tutte quelle per Garmin Connect — espone anche
creazione, modifica e **cancellazione** di attività e allenamenti. Sono lì, a
portata di un attributo, in un progetto la cui prima regola di sicurezza è che
nessuna scrittura raggiunga Garmin senza approvazione esplicita.

Un'allow-list dichiarata in un commento è una convenzione. Questa è un muro:
l'oggetto restituito da ``open_session`` **non ha** i metodi di scrittura, e
chiederglieli solleva un errore che nomina il problema.

## Perché non `garmin-py`

La Macro-proposta 3 proponeva di sostituire la libreria con `garmin-py`. Il
secondo audit ha bloccato la sostituzione, non il contratto: `garmin-py` ha una
stella su GitHub contro le 2.800 di quella in uso, espone la stessa superficie
di scrittura — quindi non porta alcun vantaggio di sicurezza — e cambiare il
percorso di autenticazione su un account già bloccato una volta con un 429
costa un rischio reale per un vantaggio di forma.

Il valore di D3 è il contratto, ed è tutto qui. La libreria è
un'implementazione sostituibile, che è esattamente ciò che questo modulo rende
possibile: il giorno che servisse, si cambia questo file e nient'altro.

## Ogni risposta viene salvata prima di essere letta

Una risposta che esiste solo come riga già trasformata non è rigjocabile. Se
domani si scopre che un campo era stato interpretato male — è già successo con
la lunghezza vasca, che arriva in centimetri mentre la distanza arriva in metri
— l'unico rimedio sarebbe richiedere tutto a Garmin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import source_catalog

# I soli metodi raggiungibili. Ognuno legge e basta.
# Aggiungerne uno è una decisione, non una comodità: la lista è corta perché
# ogni voce è una cosa che il progetto ha davvero bisogno di sapere.
ALLOWED = {
    "get_activities_by_date": "le attività di un intervallo di giorni",
    "get_user_summary": "il riepilogo di salute di un giorno",
    "get_sleep_data": "il sonno di una notte",
    "get_hrv_data": "l'HRV di una notte",
    "get_full_name": "il nome dell'account, per verificare il collegamento",
    # Aggiunto il 24/08/2026, ed è una decisione con un motivo misurato.
    #
    # L'export storico si ferma al 4 luglio 2026. Da allora il sync porta i
    # riepiloghi, ma i file FIT arrivavano **solo** dagli ZIP dell'export: di
    # conseguenza **36 nuotate su 36 successive a quella data non avevano un
    # solo lap** — 83 km, cioè l'intera preparazione corrente verso place22,
    # cieca al dettaglio. E il numero cresceva ogni giorno.
    #
    # Scarica e basta: restituisce i byte del file originale così come Garmin
    # lo conserva. Non modifica niente sul servizio.
    "download_activity": "il file originale di un'attività, per averne i lap",
}

# Non è la lista completa dei metodi di scrittura della libreria — cambia con le
# versioni. Serve a dare un errore che spiega, invece di un AttributeError, alla
# categoria di chiamate che non deve mai partire da qui.
KNOWN_WRITES = {
    "upload_activity", "delete_activity", "set_activity_name", "set_activity_type",
    "add_weigh_in", "delete_weigh_in", "add_body_composition",
    "upload_workout", "delete_workout", "schedule_workout",
    "add_blood_pressure", "set_blood_pressure",
}


class WriteAttempted(PermissionError):
    """Qualcuno ha provato a scrivere su Garmin passando da qui."""


class NotAllowed(AttributeError):
    """Un metodo di lettura non previsto dal contratto."""


@dataclass
class ReadOnlyGarmin:
    """Il client Garmin, con la sola superficie di lettura dichiarata.

    Ogni risposta viene salvata come snapshot **prima** di tornare al chiamante,
    così il dato grezzo esiste su disco anche se il codice che lo interpreta
    cambia idea.
    """

    client: object
    capture: bool = True
    captured: list = field(default_factory=list)

    def __getattr__(self, name: str):
        if name in KNOWN_WRITES:
            raise WriteAttempted(
                f"'{name}' scrive su Garmin Connect e non è raggiungibile da "
                "qui. Nessuna scrittura verso Garmin senza approvazione "
                "esplicita e monouso dell'atleta.")
        if name not in ALLOWED:
            raise NotAllowed(
                f"'{name}' non è nel contratto di sola lettura. I metodi "
                f"disponibili sono: {', '.join(sorted(ALLOWED))}. "
                "Aggiungerne uno è una decisione da prendere in "
                "ingest/garmin_read_only.py, non da fare al volo.")

        method = getattr(self.client, name)

        def call(*arguments, **keywords):
            payload = method(*arguments, **keywords)
            if self.capture and payload is not None:
                day = str(arguments[0]) if arguments else "senza-data"
                described = source_catalog.capture(payload, name, day[:10])
                self.captured.append(described)
            return payload

        return call


@dataclass(frozen=True)
class Capabilities:
    """Che cosa questa installazione sa davvero fare, verificato invece che
    assunto. Una libreria aggiornata può aver rinominato un metodo, e accorgersene
    a metà di un sync significa lasciare i dati a metà."""

    library: str
    version: str | None
    available: tuple
    missing: tuple

    @property
    def usable(self) -> bool:
        return not self.missing

    def explain(self) -> str:
        if self.usable:
            return (f"{self.library} {self.version or '(versione ignota)'}: "
                    f"tutti i {len(self.available)} metodi previsti sono presenti.")
        return (f"{self.library} {self.version or '(versione ignota)'} non "
                f"espone: {', '.join(self.missing)}. Lo storico locale resta "
                "interrogabile; è l'aggiornamento dei dati recenti a fermarsi.")


def probe(client: object) -> Capabilities:
    """Verifica che il client offra davvero ciò che il contratto promette."""
    version = None
    try:
        import garminconnect
        version = getattr(garminconnect, "__version__", None)
    except ImportError:
        pass

    present = tuple(name for name in sorted(ALLOWED) if callable(getattr(client, name, None)))
    absent = tuple(name for name in sorted(ALLOWED) if name not in present)
    return Capabilities("garminconnect", version, present, absent)


def wrap(client: object, capture: bool = True) -> ReadOnlyGarmin:
    """Il client dietro il muro. È l'unico modo previsto per ottenerne uno."""
    return ReadOnlyGarmin(client=client, capture=capture)
