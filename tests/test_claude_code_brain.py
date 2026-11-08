"""Claude come cervello, senza chiave API e senza spesa a consumo.

## La decisione che ha cambiato il ponte

L'audit aveva raccomandato la Messages API su `httpx2`, perché non richiedeva
installazioni. L'atleta ha deciso diversamente: niente API a consumo, si usano
gli strumenti già pagati. L'eseguibile di Claude Code c'è — lo installa
l'applicazione desktop — e parla con l'abbonamento.

## Cosa questi test difendono

1. **Il pacchetto resta l'unica fonte.** `--tools ""` toglie a Claude ogni
   strumento e `--strict-mcp-config` spegne i server MCP. Senza il secondo, il
   server `garmin-coach` di questo stesso progetto sarebbe raggiungibile: il
   modello potrebbe interrogare il database e aggirare il contratto dalla porta
   di servizio, e il validatore non avrebbe modo di accorgersene perché i numeri
   sarebbero veri.
2. **Il validatore vale anche per Claude.** Un `fact_id` inventato o un numero
   che il pacchetto non contiene fanno rifiutare la risposta, esattamente come
   per qualunque altro cervello.
3. **Il confine medico lo mette il progetto**, non la buona volontà del modello.
4. **Il ripiego si dichiara.** Se Claude non risponde, la pagina resta utile ma
   dice con quale voce sta parlando. Una risposta locale spacciata per quella di
   Claude sarebbe la bugia più comoda di tutto il progetto.
"""

import json
import pathlib
import subprocess
from datetime import date

import pytest

from garmin_coach.coach import claude_code
from garmin_coach.coach.contract import CoachContextPacket, Fact


@pytest.fixture
def packet():
    uno = CoachContextPacket(question="Posso spingere?",
                            observation_date=date(2026, 8, 22))
    uno.goal = {"event_name": "event02 place22", "days_to_event": 42}
    uno.add(Fact(fact_id="swim_km_7d", label="Nuoto negli ultimi 7 giorni",
                 value=21.78, unit="km", display="21,78 km",
                 window="ultimi 7 giorni"))
    return uno


RISPOSTA_MINIMA = {
    "verdict": "Il lavoro c'è, la prova al passo obiettivo no.",
    "primary_focus": "Verificare la tenuta invece di aggiungere volume.",
    "confidence": "moderate",
    "why": ["swim_km_7d"],
}


def _stdout(risposta: dict) -> str:
    return json.dumps({"type": "result", "is_error": False,
                       "result": json.dumps(risposta, ensure_ascii=False)})


@pytest.fixture
def finto_claude(monkeypatch, tmp_path):
    """Un eseguibile finto, e la memoria di come è stato invocato."""
    binario = tmp_path / "claude.exe"
    binario.write_text("", encoding="utf-8")
    invocazioni: list[dict] = []

    def falso_run(argomenti, **opzioni):
        cartella = opzioni.get("cwd")
        # La cartella temporanea esiste **solo** durante la chiamata: un
        # controllo fatto dopo troverebbe un percorso cancellato e passerebbe
        # sempre, cioè non controllerebbe niente.
        vuota = (cartella is not None
                 and not list(pathlib.Path(cartella).iterdir()))
        invocazioni.append({"args": argomenti, "input": opzioni.get("input", ""),
                            "cwd": cartella, "cwd_vuota": vuota})
        return subprocess.CompletedProcess(
            argomenti, 0, stdout=falso_run.stdout, stderr=falso_run.stderr)

    falso_run.stdout = _stdout(RISPOSTA_MINIMA)
    falso_run.stderr = ""
    monkeypatch.setattr(claude_code.subprocess, "run", falso_run)
    return {"binario": binario, "invocazioni": invocazioni, "run": falso_run}


# ── 1. Il pacchetto resta l'unica fonte ──────────────────────────────────

class TestClaudeCannotReachAnythingButThePacket:
    def test_every_tool_is_disabled(self, packet, finto_claude):
        claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        argomenti = finto_claude["invocazioni"][0]["args"]
        assert "--tools" in argomenti
        assert argomenti[argomenti.index("--tools") + 1] == "", (
            "Claude ha degli strumenti: potrebbe leggere file o eseguire "
            "comandi invece di limitarsi al pacchetto")

    def test_mcp_servers_are_off(self, packet, finto_claude):
        """Senza questo, il server MCP di questo progetto sarebbe raggiungibile.

        È il caso peggiore possibile: i numeri sarebbero veri, quindi il
        validatore li accetterebbe, e il pacchetto smetterebbe di essere il
        confine senza che nessuno se ne accorga.
        """
        claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        assert "--strict-mcp-config" in finto_claude["invocazioni"][0]["args"]

    def test_it_runs_in_an_empty_directory(self, packet, finto_claude):
        """Nessun CLAUDE.md di questo repository deve entrare in un giudizio sportivo."""
        claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        assert finto_claude["invocazioni"][0]["cwd_vuota"], (
            "Claude gira in una cartella con dei file: potrebbe raccogliere "
            "istruzioni di sviluppo che non c'entrano con un giudizio sportivo")

    def test_what_leaves_the_computer_is_the_packet_and_nothing_else(
            self, packet, finto_claude):
        claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        inviato = finto_claude["invocazioni"][0]["input"]
        assert "swim_km_7d" in inviato
        for vietato in ("latitude", "longitude", "startLatitude", "device_id",
                        "source_object_id"):
            assert vietato not in inviato, f"nel pacchetto esce {vietato}"

    def test_the_session_is_not_left_on_disk(self, packet, finto_claude):
        claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        assert "--no-session-persistence" in finto_claude["invocazioni"][0]["args"]


# ── 2. Il validatore vale anche per Claude ───────────────────────────────

class TestTheContractAppliesToClaudeToo:
    """Il validatore non fa sconti a Claude.

    Dopo un rifiuto il modello ha **un** secondo tentativo, con scritto cosa ha
    sbagliato: alla prima prova contro il modello vero la stessa domanda è stata
    respinta una volta e passata la volta dopo, e un errore intermittente in
    pagina è peggio di un errore stabile. Se sbaglia anche la seconda, non
    passa: si ripiega sul locale, dicendolo.
    """

    def test_an_invented_fact_id_never_reaches_the_athlete(self, packet,
                                                           finto_claude):
        finto_claude["run"].stdout = _stdout(
            {**RISPOSTA_MINIMA, "why": ["hrv_trend_che_non_esiste"]})

        with pytest.raises(claude_code.BrainUnavailable) as fermo:
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)
        assert "hrv_trend_che_non_esiste" in str(fermo.value)

    def test_an_invented_number_never_reaches_the_athlete(self, packet,
                                                          finto_claude):
        finto_claude["run"].stdout = _stdout(
            {**RISPOSTA_MINIMA,
             "verdict": "Hai nuotato 38,4 km e puoi permetterti di spingere."})

        with pytest.raises(claude_code.BrainUnavailable) as fermo:
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)
        assert "38" in str(fermo.value)

    def test_a_diagnosis_never_reaches_the_athlete(self, packet, finto_claude):
        finto_claude["run"].stdout = _stdout(
            {**RISPOSTA_MINIMA,
             "primary_focus": "Fermati: stai andando verso una tendinite."})

        with pytest.raises(claude_code.BrainUnavailable):
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

    def test_a_refusal_is_retried_once_with_the_reason_and_no_more(
            self, packet, finto_claude):
        finto_claude["run"].stdout = _stdout(
            {**RISPOSTA_MINIMA, "why": ["non_esiste"]})

        with pytest.raises(claude_code.BrainUnavailable):
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

        assert len(finto_claude["invocazioni"]) == 2, (
            "il secondo tentativo non c'e' stato, oppure ce ne sono stati piu' "
            "di due: insistere costa abbonamento per peggiorare l'attesa")
        assert "non_esiste" in finto_claude["invocazioni"][1]["input"], (
            "il secondo tentativo non dice al modello cosa aveva sbagliato")

    def test_a_second_answer_that_respects_the_contract_is_accepted(
            self, packet, finto_claude):
        sbagliata = _stdout({**RISPOSTA_MINIMA, "why": ["non_esiste"]})
        buona = _stdout(RISPOSTA_MINIMA)
        risposte = iter([sbagliata, buona])

        vero_run = claude_code.subprocess.run

        def alterna(argomenti, **opzioni):
            finto_claude["run"].stdout = next(risposte)
            return vero_run(argomenti, **opzioni)

        claude_code.subprocess.run = alterna
        try:
            risposta = claude_code.ClaudeCodeBrain(
                finto_claude["binario"]).judge(packet)
        finally:
            claude_code.subprocess.run = vero_run

        assert risposta.verdict.startswith("Il lavoro c'è")

    def test_the_medical_boundary_is_added_even_if_the_model_forgets_it(
            self, packet, finto_claude):
        risposta = claude_code.ClaudeCodeBrain(
            finto_claude["binario"]).judge(packet)

        assert any("fisioterapista" in riga for riga in risposta.boundary)

    def test_extra_keys_from_the_model_do_not_break_the_answer(
            self, packet, finto_claude):
        finto_claude["run"].stdout = _stdout(
            {**RISPOSTA_MINIMA, "chiave_inventata": "qualcosa"})

        risposta = claude_code.ClaudeCodeBrain(
            finto_claude["binario"]).judge(packet)

        assert risposta.verdict.startswith("Il lavoro c'è")

    def test_the_answer_carries_the_digest_of_the_facts_it_saw(
            self, packet, finto_claude):
        risposta = claude_code.ClaudeCodeBrain(
            finto_claude["binario"]).judge(packet)

        assert risposta.packet_digest == packet.digest
        assert "Claude" in risposta.model


# ── 3. Quando Claude non c'è, si dice cosa fare ──────────────────────────

class TestWhenClaudeCannotAnswer:
    def test_an_unreadable_desktop_installation_is_skipped(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))

        def negato(_percorso, _pattern):
            raise PermissionError("cartella non leggibile")

        monkeypatch.setattr(claude_code.Path, "glob", negato)

        assert claude_code._candidates(), (
            "un'installazione non leggibile non deve interrompere la ricerca "
            "degli altri percorsi")

    def test_an_unreadable_candidate_is_not_a_page_error(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(claude_code, "_candidates", lambda: [tmp_path])

        def negato(_percorso):
            raise PermissionError("accesso negato")

        monkeypatch.setattr(claude_code.Path, "is_file", negato)

        assert claude_code.executable() is None

    def test_an_expired_login_becomes_an_instruction_not_a_stack_trace(self):
        messaggio = claude_code._diagnosi(
            "Failed to authenticate: OAuth session expired and could not be refreshed")

        assert "abbonamento" in messaggio
        assert "chiave API" in messaggio
        assert "claude" in messaggio

    def test_text_instead_of_json_is_refused_instead_of_guessed(
            self, packet, finto_claude):
        finto_claude["run"].stdout = json.dumps(
            {"is_error": False, "result": "Direi che puoi spingere."})

        with pytest.raises(claude_code.BrainUnavailable):
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)

    def test_a_missing_executable_says_so(self, packet, tmp_path):
        cervello = claude_code.ClaudeCodeBrain(tmp_path / "non-esiste.exe")
        cervello.binario = None

        with pytest.raises(claude_code.BrainUnavailable):
            cervello.judge(packet)

    def test_a_timeout_does_not_hang_the_page(self, packet, finto_claude,
                                              monkeypatch):
        def scade(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="claude",
                                            timeout=claude_code.TIMEOUT_S)

        monkeypatch.setattr(claude_code.subprocess, "run", scade)

        with pytest.raises(claude_code.BrainUnavailable) as fermo:
            claude_code.ClaudeCodeBrain(finto_claude["binario"]).judge(packet)
        assert "locale" in str(fermo.value)


class TestTheNeutralDirectory:
    """La cartella in cui gira Claude, e il guasto che l'ha resa stabile.

    La prima versione ne creava una temporanea per chiamata. Su Windows il
    processo figlio la tiene ancora come directory corrente quando Python prova
    a cancellarla: `PermissionError: [WinError 32]`, e la pagina moriva con uno
    stack trace invece di dare la risposta. Successo alla prima invocazione vera
    contro l'eseguibile reale.
    """

    def test_it_is_the_same_directory_every_time(self):
        prima = claude_code._neutral_directory()
        dopo = claude_code._neutral_directory()

        assert prima == dopo
        assert prima.is_dir()

    def test_it_carries_no_project_instructions(self):
        """Un CLAUDE.md lì dentro entrerebbe in un giudizio sportivo."""
        cartella = claude_code._neutral_directory()

        assert not list(cartella.glob("CLAUDE.md"))
        assert not list(cartella.glob(".claude"))
