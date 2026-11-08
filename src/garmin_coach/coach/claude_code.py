"""Il giudizio di Claude, attraverso l'abbonamento che l'atleta già paga.

## Perché non la Messages API

L'audit aveva raccomandato la Messages API su `httpx2`, perché non richiedeva
installazioni. Richiedeva però una chiave e una spesa a consumo, e l'atleta ha
deciso: niente API, si usano gli strumenti già pagati.

Misurato su questa macchina il 22/08/2026, dopo la decisione:

| | dove | stato |
|---|---|---|
| `claude` nel PATH | — | **assente** |
| eseguibile di Claude Code | `%APPDATA%\\Claude\\claude-code\\<versione>\\claude.exe` | **c'è**, 2.1.237 |
| sessione OAuth su disco | `~/.claude/.credentials.json` | **scaduta** |
| pacchetto `anthropic` | — | assente |

L'eseguibile esiste perché lo installa l'applicazione desktop. La sessione su
disco è scaduta perché l'applicazione rinnova il proprio accesso per conto suo e
non riscrive quel file: un `claude` lanciato da qui non lo sa rinnovare da solo.
Si risolve con **un accesso, una volta**, e non serve nessuna chiave.

## Come viene invocato, e perché con questi argomenti

    claude --print --output-format json --model sonnet
           --system-prompt <il contratto>
           --tools "" --strict-mcp-config --disable-slash-commands
           --no-session-persistence

- `--tools ""` toglie a Claude **ogni** strumento: niente shell, niente lettura
  di file, niente rete oltre la propria risposta. È ciò che rende vero il
  contratto: se un numero non è nel pacchetto, non è raggiungibile in nessun
  altro modo.
- `--strict-mcp-config` senza un `--mcp-config` spegne i server MCP. Senza,
  il server `garmin-coach` di questo stesso progetto sarebbe raggiungibile e il
  modello potrebbe interrogare il database — cioè aggirare il pacchetto dalla
  porta di servizio.
- `--no-session-persistence` non lascia la conversazione su disco.
- la cartella di lavoro è una cartella temporanea vuota, così non viene
  raccolto nessun `CLAUDE.md`: le istruzioni di sviluppo di questo repository
  non hanno niente a che fare con un giudizio sportivo.

## Cosa esce dal computer

Il pacchetto, che è lo stesso mostrato in pagina prima dell'invio: volumi,
passi, recupero, obiettivo dichiarato, limiti. Nessuna coordinata, nessun nome
dell'atleta, nessun file grezzo. È l'unica cosa che esce, ed esce solo quando
l'atleta preme un pulsante.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import fields
from pathlib import Path

from .contract import (CONFIDENCE, CoachContextPacket, CoachingResponse,
                       InvalidResponse, validate)

# Il modello. `sonnet` e non `opus` perché questo compito è un giudizio su venti
# fatti già calcolati, non un problema aperto, e sull'abbonamento il modello più
# grande si consuma dove serve davvero.
MODEL = "sonnet"

# Oltre questo, qualcosa è bloccato: una risposta a un pacchetto di tre chilobyte
# non impiega due minuti. Meglio dirlo che restare appesi.
TIMEOUT_S = 120

# Dove cercare l'eseguibile, in ordine. Il primo è la variabile che l'app
# desktop imposta ai propri processi figli: se questo codice gira dentro una
# sessione di Claude Code, l'eseguibile giusto è già indicato.
_ENV_HINT = "CLAUDE_CODE_EXECPATH"


class BrainUnavailable(RuntimeError):
    """Claude non è raggiungibile da qui, e c'è scritto cosa fare.

    Non è un errore da nascondere né da trasformare in una risposta vuota: è
    una condizione normale — nessun accesso, computer offline — che ha un
    rimedio preciso, e l'unica cosa utile è dirlo.
    """


def _candidates() -> list[Path]:
    trovati: list[Path] = []
    indicato = os.environ.get(_ENV_HINT)
    if indicato:
        trovati.append(Path(indicato))

    nel_percorso = shutil.which("claude")
    if nel_percorso:
        trovati.append(Path(nel_percorso))

    # L'installazione dell'applicazione desktop: una cartella per versione, e
    # la più recente è quella che l'applicazione sta usando.
    roaming = os.environ.get("APPDATA")
    if roaming:
        try:
            versioni = sorted(
                (Path(roaming) / "Claude" / "claude-code").glob("*/claude.exe"))
        except OSError:
            versioni = []
        trovati.extend(reversed(versioni))

    locale = Path.home() / ".claude" / "local" / "claude"
    trovati.extend([locale, locale.with_suffix(".exe")])
    return trovati


def executable() -> Path | None:
    """L'eseguibile di Claude Code su questo computer, se c'è."""
    for candidato in _candidates():
        try:
            if candidato.is_file():
                return candidato
        except OSError:
            continue
    return None


SYSTEM_PROMPT = """Sei il secondo allenatore di un nuotatore agonista italiano.

Ricevi un pacchetto di fatti già calcolati e devi produrre un giudizio.

Regole non negoziabili:
1. Non puoi usare nessun numero che non compaia nel pacchetto. Nessuna stima,
   nessun arrotondamento nuovo, nessun valore "tipico" preso da altrove.
2. Ogni conclusione va appoggiata a `fact_id` presenti nel pacchetto, elencati
   in `why`. Un `fact_id` inventato invalida tutta la risposta.
3. Nessuna diagnosi, nessuna previsione di infortunio, nessun parere medico.
4. Non dichiarare cause: i dati mostrano associazioni. Scrivi osservazioni.
5. Se i dati non bastano, scrivilo. "Non lo so ancora" è una risposta corretta;
   una frase generica che riempie un campo non lo è.
6. Parli all'atleta in italiano, dandogli del tu, senza gergo inutile.
7. Non sostituisci il suo allenatore umano: prepari una decisione da discutere
   con lui.

Rispondi **soltanto** con un oggetto JSON, senza testo prima o dopo e senza
blocchi di codice, con esattamente queste chiavi:

{
  "verdict": "una frase o due: dove sta adesso rispetto all'obiettivo",
  "primary_focus": "la sola cosa su cui concentrarsi ora",
  "focus_drift": "sì | no | incerto",
  "focus_drift_why": "perché",
  "what_is_working": ["..."],
  "what_needs_attention": ["..."],
  "actions_next_7_days": ["..."],
  "direction_next_21_days": ["..."],
  "scenario_next_42_days": ["..."],
  "what_to_avoid": ["..."],
  "confidence": "high | moderate | low",
  "why": ["fact_id"],
  "counterpoints": ["fact_id"],
  "questions_for_athlete": ["..."],
  "boundary": ["..."],
  "next_check": "cosa guardare la prossima volta, e quando"
}"""


def _prompt(packet: CoachContextPacket) -> str:
    return ("Ecco il pacchetto di fatti. Rispondi con il solo JSON richiesto.\n\n"
            + json.dumps(packet.as_dict(), ensure_ascii=False, indent=1,
                         default=str))


def _neutral_directory() -> Path:
    """Una cartella vuota, stabile, in cui far girare Claude.

    Vuota perché nella cartella del progetto verrebbe raccolto `CLAUDE.md`, e le
    istruzioni di sviluppo di questo repository non hanno niente a che fare con
    un giudizio sportivo.

    **Stabile** e non temporanea perché su Windows la versione temporanea si
    rompeva: il processo figlio tiene ancora la cartella come propria directory
    corrente quando Python prova a cancellarla, e la pagina moriva con un
    `PermissionError` invece di dare la risposta. Una cartella vuota che resta
    non costa niente e non ha quella corsa.
    """
    cartella = Path(tempfile.gettempdir()) / "garmin-coach-brain"
    cartella.mkdir(exist_ok=True)
    return cartella


def _run(binario: Path, prompt: str) -> str:
    """Esegue Claude Code e restituisce il testo della risposta."""
    argomenti = [
        str(binario), "--print", "--output-format", "json",
        "--model", MODEL,
        "--system-prompt", SYSTEM_PROMPT,
        "--tools", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    try:
        esito = subprocess.run(
            argomenti, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
            cwd=_neutral_directory())
    except subprocess.TimeoutExpired:
        raise BrainUnavailable(
            f"Claude non ha risposto entro {TIMEOUT_S} secondi. "
            "Riprova, oppure usa la lettura locale che è già in pagina.")
    except OSError as errore:
        raise BrainUnavailable(
            f"Non sono riuscito ad avviare Claude Code: {errore}")

    uscita = (esito.stdout or "").strip()
    if not uscita:
        raise BrainUnavailable(_diagnosi(esito.stderr or "", binario))

    try:
        involucro = json.loads(uscita)
    except json.JSONDecodeError:
        # Claude Code stampa in chiaro anche i propri errori — l'accesso
        # scaduto arriva così, su stdout e senza essere JSON.
        raise BrainUnavailable(_diagnosi(uscita, binario))

    if involucro.get("is_error") or "result" not in involucro:
        raise BrainUnavailable(
            _diagnosi(str(involucro.get("result", uscita)), binario))
    return str(involucro["result"])


def _diagnosi(messaggio: str, binario: Path | None = None) -> str:
    """Da un errore di Claude Code a una frase che dice cosa fare.

    L'accesso scaduto è **il** caso normale su questo computer, e senza questa
    traduzione l'atleta leggerebbe «OAuth session expired» in una dashboard
    italiana e non saprebbe che si risolve con un comando e nessuna chiave.
    """
    testo = (messaggio or "").strip()
    minuscolo = testo.lower()
    if "oauth" in minuscolo or "authenticate" in minuscolo or "login" in minuscolo:
        # Il percorso completo, e non «lancia claude»: l'eseguibile non è nel
        # PATH di questo computer, quindi il consiglio corto sarebbe un
        # consiglio che non funziona.
        comando = f'& "{binario}"' if binario else "claude"
        return ("Claude Code è installato ma il suo accesso è scaduto. Si "
                "rinnova una volta sola e non serve nessuna chiave API: apri "
                "PowerShell, esegui questo comando, entra con il tuo "
                f"abbonamento, poi ricarica questa pagina.  {comando}")
    if "credit" in minuscolo or "usage limit" in minuscolo or "rate limit" in minuscolo:
        return ("Claude ha risposto che il limite d'uso dell'abbonamento è "
                "esaurito per adesso. La lettura locale qui sotto resta valida.")
    return ("Claude Code non ha risposto come previsto. Il messaggio che ha "
            f"dato è: {testo[:300]}")


_LIST_FIELDS = {"what_is_working", "what_needs_attention", "actions_next_7_days",
                "direction_next_21_days", "scenario_next_42_days",
                "what_to_avoid", "why", "counterpoints",
                "questions_for_athlete", "boundary"}

_TEXT_FIELDS = {"verdict", "primary_focus", "focus_drift", "focus_drift_why",
                "next_check"}


def _parse(testo: str, packet: CoachContextPacket, modello: str) -> CoachingResponse:
    """Il JSON del modello, diventato una risposta del contratto.

    Il modello può circondare il JSON di cortesie nonostante le istruzioni.
    Si prende ciò che sta fra la prima graffa e l'ultima, e se lì dentro non
    c'è un oggetto si rifiuta: non si tenta di indovinare.
    """
    inizio, fine = testo.find("{"), testo.rfind("}")
    if inizio < 0 or fine <= inizio:
        raise BrainUnavailable(
            "Claude ha risposto con del testo invece che con il JSON "
            "richiesto, e non lo interpreto a occhio.")
    try:
        corpo = json.loads(testo[inizio:fine + 1])
    except json.JSONDecodeError as errore:
        raise BrainUnavailable(f"La risposta di Claude non è JSON valido: {errore}")

    ammessi = {f.name for f in fields(CoachingResponse)}
    risposta = CoachingResponse(
        verdict="", primary_focus="", packet_digest=packet.digest,
        model=modello, generated_on=packet.observation_date)

    for chiave, valore in corpo.items():
        if chiave not in ammessi:
            continue          # una chiave in più non è un motivo per buttare tutto
        if chiave in _LIST_FIELDS:
            voci = valore if isinstance(valore, list) else [valore]
            setattr(risposta, chiave,
                    [str(v).strip() for v in voci if str(v).strip()])
        elif chiave in _TEXT_FIELDS:
            setattr(risposta, chiave, str(valore).strip())
        elif chiave == "confidence" and str(valore).strip() in CONFIDENCE:
            risposta.confidence = str(valore).strip()

    # Il confine non è una gentilezza del modello: lo mette il progetto, sempre,
    # anche se il modello se ne dimentica.
    frase = ("Questo non è un parere medico. Dolore che non passa, o che cambia "
             "il modo in cui nuoti, si guarda con un fisioterapista.")
    if frase not in risposta.boundary:
        risposta.boundary.append(frase)

    validate(risposta, packet)
    return risposta


class ClaudeCodeBrain:
    """Claude come cervello, attraverso l'eseguibile di Claude Code.

    Non tiene stato fra una domanda e l'altra: ogni giudizio parte dal proprio
    pacchetto. È voluto — una conversazione che ricorda la risposta precedente
    finirebbe per citare numeri di ieri come se fossero di oggi, e il
    validatore non avrebbe modo di accorgersene.
    """

    name = "Claude (Claude Code, abbonamento)"

    def __init__(self, binario: Path | None = None):
        self.binario = binario or executable()

    @property
    def available(self) -> bool:
        return self.binario is not None

    def unavailable_because(self) -> str:
        return ("Non trovo Claude Code su questo computer. Serve "
                "l'applicazione desktop di Claude, oppure `claude` "
                "raggiungibile dal PATH.")

    def judge(self, packet: CoachContextPacket) -> CoachingResponse:
        """Chiede il giudizio, e se il contratto lo respinge lo richiede una volta.

        ## Perché un secondo tentativo, e perché uno solo

        Alla prima prova contro il modello vero, la risposta è stata respinta per
        un numero fuori pacchetto — «60», comparso in una frase di contorno. La
        seconda, sullo stesso pacchetto, è passata pulita. Il rifiuto è quindi
        **intermittente**, ed è il caso peggiore per chi usa la pagina: la stessa
        domanda a volte risponde e a volte mostra un errore.

        Il rimedio non è ammorbidire il validatore. Il validatore ha ragione: un
        numero che il pacchetto non contiene non deve arrivare all'atleta, punto.
        Il rimedio è **dire al modello cosa ha sbagliato e lasciarglielo
        riscrivere** — che è ciò che si farebbe con una persona.

        Uno solo, e non «finché non passa»: se sbaglia due volte sullo stesso
        pacchetto, il problema non è la distrazione, e insistere costa
        abbonamento per peggiorare l'attesa. Lì si ripiega sul locale, dicendolo.
        """
        if not self.binario:
            raise BrainUnavailable(self.unavailable_because())

        try:
            return _parse(_run(self.binario, _prompt(packet)), packet, self.name)
        except InvalidResponse as respinta:
            richiesta = (
                f"{_prompt(packet)}\n\n"
                "ATTENZIONE: la tua risposta precedente è stata respinta dal "
                f"contratto per questo motivo:\n{respinta}\n"
                "Riscrivila per intero rispettando il motivo qui sopra. Non "
                "spiegare l'errore: produci solo il JSON corretto.")
            try:
                return _parse(_run(self.binario, richiesta), packet, self.name)
            except InvalidResponse as ancora:
                raise BrainUnavailable(
                    "Claude ha risposto due volte con qualcosa che il contratto "
                    f"non lascia passare: {ancora} Qui sotto trovi la lettura "
                    "locale, che è deterministica.")
