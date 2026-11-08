"""Il doppio clic, e i flussi che non devono richiedere il terminale.

Il criterio del §10 della Macro-proposta 4 dice: dopo l'installazione iniziale,
un utente non tecnico completa i suoi compiti senza aprire una riga di comando.
Il launcher è l'unico punto in cui quella promessa si mantiene o si perde, e un
`.cmd` rotto non lo scopre nessuno finché non serve.
"""

import pathlib
import re
import subprocess
import sys

import pytest

from garmin_coach import paths
from garmin_coach.app import server

LAUNCHER = paths.ROOT / "Garmin Coach.cmd"


class TestTheDoubleClick:
    def test_the_launcher_exists_where_a_person_would_look_for_it(self):
        assert LAUNCHER.exists(), (
            "il launcher sta nella radice del progetto, non in una sottocartella: "
            "è la prima cosa che si cerca aprendo la cartella")

    def test_it_is_readable_by_a_human_who_opens_it(self):
        testo = LAUNCHER.read_text(encoding="utf-8", errors="replace")
        assert "garmin_coach app" in testo
        assert testo.lstrip().startswith("@echo off")

    def test_it_says_what_to_do_when_the_environment_is_missing(self):
        """Un launcher che fallisce in silenzio è peggio di nessun launcher."""
        testo = LAUNCHER.read_text(encoding="utf-8", errors="replace")
        assert "venv" in testo
        assert "pause" in testo, "senza pausa, la finestra sparisce con l'errore"

    def test_it_uses_the_interpreter_of_the_project_not_the_system_one(self):
        testo = LAUNCHER.read_text(encoding="utf-8", errors="replace")
        assert ".venv" in testo


class TestTheCommandBehindIt:
    def test_the_app_command_is_offered_by_the_command_line(self):
        risultato = subprocess.run(
            [sys.executable, "-m", "garmin_coach", "--help"],
            capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
        assert "app" in risultato.stdout

    def test_the_server_binds_only_to_this_computer(self):
        assert server.HOST == "127.0.0.1", (
            "un bind su 0.0.0.0 esporrebbe i dati dell'atleta alla rete locale")

    def test_the_port_can_be_changed_when_it_is_taken(self):
        risultato = subprocess.run(
            [sys.executable, "-m", "garmin_coach", "--help"],
            capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
        assert "--port" in risultato.stdout


class TestNoTelemetry:
    """Nessun dato lascia il computer senza richiesta esplicita."""

    APP = pathlib.Path(server.__file__).resolve().parent
    ANALISI = pathlib.Path(server.__file__).resolve().parents[1] / "analysis"

    @pytest.mark.parametrize("cartella", ["app", "analysis"])
    def test_no_module_reaches_the_network(self, cartella):
        radice = pathlib.Path(server.__file__).resolve().parents[1] / cartella
        for sorgente in radice.glob("*.py"):
            testo = sorgente.read_text(encoding="utf-8")
            for vietato in ("import requests", "urllib.request", "http.client",
                            "socket.create_connection", "httpx.get"):
                assert vietato not in testo, f"{sorgente.name}: {vietato}"

    def test_the_stylesheet_never_points_outside(self):
        css = (self.APP / "style.css").read_text(encoding="utf-8")
        assert "@import" not in css
        assert "http" not in css, "nessun font e nessuna immagine da un CDN"

    def test_the_only_javascript_does_not_talk_to_anyone(self):
        from garmin_coach.app import pages
        for vietato in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon",
                        "http://", "https://"):
            assert vietato not in pages.COPIA_JS, (
                f"il JavaScript dell'app contiene {vietato}")


class TestTheOnePageGuide:
    GUIDA = paths.DOCS / "GUIDA.md"

    def test_it_exists_and_is_one_page(self):
        assert self.GUIDA.exists()
        righe = self.GUIDA.read_text(encoding="utf-8").splitlines()
        assert len(righe) < 140, (
            "una guida che non sta in una pagina è una guida che nessuno legge")

    def test_it_covers_the_four_things_a_person_does(self):
        testo = self.GUIDA.read_text(encoding="utf-8").lower()
        for cosa in ("aprire", "guardare", "approfondire", "correggere"):
            assert cosa in testo

    def test_every_command_it_promises_actually_exists(self):
        """Un README che promette un comando inesistente è il difetto che
        l'incarico §11 vieta esplicitamente."""
        testo = self.GUIDA.read_text(encoding="utf-8")
        comandi = set(re.findall(r"garmin_coach (\w+)", testo))

        risultato = subprocess.run(
            [sys.executable, "-m", "garmin_coach", "--help"],
            capture_output=True, text=True, cwd=paths.ROOT, timeout=120)
        for comando in comandi:
            assert comando in risultato.stdout, (
                f"la guida promette «garmin_coach {comando}», che non esiste")
