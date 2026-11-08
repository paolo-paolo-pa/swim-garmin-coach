"""L'anteprima non vincola niente: è una cortesia, non un controllo.

Le due scritture dell'app — un riferimento in ``coach/riferimenti.md``, una nota
nel diario — passano da due route: una mostra cosa verrà scritto, l'altra
scrive. Ma la seconda non sa niente della prima. Accetta lo stesso gettone di
processo, rilegge i campi dal modulo e riesegue la validazione da capo.

Quattro conseguenze, tutte raggiungibili senza uscire dal browser dell'atleta:

1. **L'anteprima si salta.** Un `POST` diretto a ``…/conferma`` scrive.
2. **I campi cambiano fra l'anteprima e la conferma.** Si conferma un 400 in
   4:35 e si scrive un 400 in 3:35: l'anteprima ha mostrato il primo.
3. **Lo stesso invio vale due volte.** Ricaricare la pagina di conferma scrive
   la riga una seconda volta.
4. **Si annota una seduta che non esiste.** La nota viene scritta nel diario e
   la risposta è 404: il file dice una cosa che l'archivio smentisce.

Il gettone di processo difende dal CSRF — quello funziona ed è provato altrove.
Non difende da questi, perché non è legato a *cosa* si sta confermando.

Il danno resta piccolo — un tempo falso fra i riferimenti — ma è precisamente la
cosa che il progetto tiene più al sicuro: la distinzione fra un fatto e una
supposizione. Un riferimento confermato è il perno da cui usciranno CSS, passi e
tempi attesi.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach import athlete_files
from garmin_coach.app import build, confirmation, security
from garmin_coach.database import SCHEMA

GIORNO = date(2026, 8, 20)
SEDUTA_ESISTENTE = 7
SEDUTA_INVENTATA = 999_999

RIFERIMENTO = {
    "day": "2026-06-15", "distance_m": "400", "stroke": "stile",
    "pool": "25", "time": "4:35,10", "kind": "gara",
    "context": "regionali", "activity_id": "", "notes": "",
}

NOTA = {"activity_id": str(SEDUTA_ESISTENTE), "day": GIORNO.isoformat(),
        "rpe": "7", "purpose": "soglia", "feeling": "spalla ok"}

# I moduli dell'app li invia una pagina dell'app: il controllo dell'origine è
# soddisfatto, come lo sarebbe in un browser vero.
NOSTRA_ORIGINE = {"origin": "http://127.0.0.1:8765"}


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    for nome in ("atleta.md", "gare.md", "obiettivi.md"):
        (cartella / nome).write_text("# vuoto\n", encoding="utf-8")
    (cartella / "riferimenti.md").write_text(
        "# Riferimenti\n\n" + athlete_files.REFERENCE_HEADER + "\n"
        "|---|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
    monkeypatch.setattr("garmin_coach.paths.COACH", cartella)
    return cartella


@pytest.fixture
def database(tmp_path, monkeypatch):
    percorso = tmp_path / "coach.duckdb"
    con = duckdb.connect(str(percorso))
    con.execute(SCHEMA)
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        "activity_date, sport, is_swim, environment, distance_m, duration_s, "
        "pool_length_m, device_id, source_object_id, imported_at) VALUES "
        "(?, ?, ?, ?, 'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 1, 'sha', ?)",
        [SEDUTA_ESISTENTE, datetime(2026, 8, 20, 20), datetime(2026, 8, 20, 20),
         GIORNO, datetime(2026, 1, 1)])
    con.close()
    monkeypatch.setattr("garmin_coach.paths.DATABASE", percorso)
    return percorso


@pytest.fixture
def client(database, coach_dir):
    return TestClient(build())


def _righe_riferimenti(coach_dir) -> list[str]:
    testo = (coach_dir / "riferimenti.md").read_text(encoding="utf-8")
    return [r for r in testo.splitlines()
            if r.startswith("|") and "Data |" not in r and set(r) - set("|-: ")]


def _note_nel_diario(coach_dir) -> str:
    cartella = coach_dir / "diario"
    if not cartella.exists():
        return ""
    return "\n".join(f.read_text(encoding="utf-8")
                     for f in sorted(cartella.glob("*.md")))


def _campi_nascosti(risposta) -> dict:
    """I campi nascosti che l'anteprima mette nel proprio modulo di conferma.

    Si leggono dalla pagina come farebbe il browser, invece di costruirli a
    mano: se un giorno il modulo di conferma tornasse a rimandare i valori,
    questi test se ne accorgerebbero da soli.
    """
    import re
    return {nome: valore for nome, valore in re.findall(
        r'<input\b[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
        risposta.text)}


def _conferma(client, dove: str, anteprima, **sovrascrivi):
    """Invia la conferma esattamente come farebbe il modulo dell'anteprima."""
    return client.post(dove, data={**_campi_nascosti(anteprima), **sovrascrivi},
                       headers=NOSTRA_ORIGINE)


# ── 1. L'anteprima si salta ──────────────────────────────────────────────

class TestLAnteprimaNonSiPuoSaltare:
    def test_a_reference_cannot_be_written_without_previewing_it(
            self, client, coach_dir):
        risposta = client.post("/gare/riferimenti/conferma",
                               data={**RIFERIMENTO, security.FIELD: security.TOKEN},
                               headers=NOSTRA_ORIGINE)

        assert not _righe_riferimenti(coach_dir), (
            "un riferimento è stato scritto senza che nessuna anteprima lo "
            "avesse mai mostrato")
        assert risposta.status_code == 403

    def test_a_note_cannot_be_written_without_previewing_it(self, client,
                                                            coach_dir):
        client.post("/sedute/nota/conferma",
                    data={**NOTA, security.FIELD: security.TOKEN},
                    headers=NOSTRA_ORIGINE)

        assert "fatica percepita" not in _note_nel_diario(coach_dir), (
            "una nota è finita nel diario senza passare dall'anteprima")


# ── 2. Si scrive ciò che è stato mostrato ────────────────────────────────

class TestSiScriveQuelloCheSiEVisto:
    def test_the_time_shown_is_the_time_written(self, client, coach_dir):
        """L'anteprima mostra 4:35,10. Alla conferma il campo dice 3:35,10.

        Se la conferma rilegge il modulo invece del gettone, scrive il secondo:
        l'atleta ha approvato un numero e nel file ne compare un altro.
        """
        anteprima = client.post("/gare/riferimenti",
                                data={**RIFERIMENTO,
                                      security.FIELD: security.TOKEN},
                                headers=NOSTRA_ORIGINE)
        assert "4:35,10" in anteprima.text

        _conferma(client, "/gare/riferimenti/conferma", anteprima,
                  time="3:35,10")

        scritte = " ".join(_righe_riferimenti(coach_dir))
        assert "3:35" not in scritte, (
            "è stato scritto un tempo diverso da quello approvato")

    def test_the_activity_shown_is_the_activity_annotated(self, client,
                                                          coach_dir):
        anteprima = client.post("/sedute/nota",
                                data={**NOTA, security.FIELD: security.TOKEN},
                                headers=NOSTRA_ORIGINE)

        _conferma(client, "/sedute/nota/conferma", anteprima, rpe="2")

        assert "**2/10**" not in _note_nel_diario(coach_dir), (
            "la nota scritta ha una fatica percepita diversa da quella mostrata")


# ── 3. Una conferma vale una volta sola ──────────────────────────────────

class TestUnaConfermaValeUnaVoltaSola:
    def test_resending_the_same_confirmation_does_not_write_twice(
            self, client, coach_dir):
        """Ricaricare la pagina di conferma è il gesto più naturale del mondo.

        Oggi produce un secondo riferimento identico, e due righe uguali nel
        file dei tempi sono due prove dove ce n'era una: ogni media che le
        legge pesa quel giorno il doppio.
        """
        anteprima = client.post("/gare/riferimenti",
                                data={**RIFERIMENTO,
                                      security.FIELD: security.TOKEN},
                                headers=NOSTRA_ORIGINE)

        prima = _conferma(client, "/gare/riferimenti/conferma", anteprima)
        seconda = _conferma(client, "/gare/riferimenti/conferma", anteprima)

        righe = _righe_riferimenti(coach_dir)
        assert len(righe) == 1, f"scritte {len(righe)} righe invece di una"
        # E il secondo invio non è un errore: rivede l'esito del primo.
        assert seconda.status_code == prima.status_code == 200
        assert "riferimenti.md" in seconda.text

    def test_resending_the_same_note_does_not_write_twice(self, client,
                                                          coach_dir):
        anteprima = client.post("/sedute/nota",
                                data={**NOTA, security.FIELD: security.TOKEN},
                                headers=NOSTRA_ORIGINE)

        for _ in range(2):
            _conferma(client, "/sedute/nota/conferma", anteprima)

        assert _note_nel_diario(coach_dir).count("fatica percepita") == 1


# ── 4. Non si annota una seduta che non esiste ───────────────────────────

class TestNonSiAnnotaCheNonEsiste:
    def test_a_note_on_an_unknown_activity_is_refused_before_being_written(
            self, client, coach_dir):
        """La risposta è già 404. Il file però è già stato scritto.

        Una nota nel diario che punta a una seduta inesistente non si vedrà mai
        nella pagina della seduta — e resterà lì a dire una cosa che l'archivio
        non conferma.
        """
        inventata = {**NOTA, "activity_id": str(SEDUTA_INVENTATA)}

        anteprima = client.post("/sedute/nota", data={
            **inventata, security.FIELD: security.TOKEN}, headers=NOSTRA_ORIGINE)
        _conferma(client, "/sedute/nota/conferma", anteprima)

        assert f"Seduta {SEDUTA_INVENTATA}" not in _note_nel_diario(coach_dir), (
            "è stata annotata una seduta che non è in archivio")
        assert anteprima.status_code == 404, (
            "l'anteprima ha mostrato una seduta che non esiste invece di dirlo")


# ── 5. Il meccanismo che rende vere le quattro cose sopra ────────────────

class TestIlGettoneDiAnteprima:
    """Le garanzie del meccanismo, provate senza passare dalle pagine.

    Servono a far fallire il test giusto: se un giorno si rompe la scadenza, il
    guasto deve apparire qui e non travestito da difetto della pagina Gare.
    """

    def setup_method(self):
        confirmation.STORE.clear()

    def test_a_token_is_spent_exactly_once(self):
        gettone = confirmation.issue("riferimento", {"a": 1})

        assert confirmation.redeem("riferimento", gettone).payload == {"a": 1}
        with pytest.raises(confirmation.Rejected):
            confirmation.redeem("riferimento", gettone)

    def test_a_token_of_one_form_does_not_work_on_the_other(self):
        gettone = confirmation.issue("nota", {"activity_id": "7"})

        with pytest.raises(confirmation.Rejected):
            confirmation.redeem("riferimento", gettone)

    def test_an_old_preview_is_not_confirmable(self):
        """Confermare oggi un'anteprima di ieri approva qualcosa che non si sta
        più guardando — e che nel frattempo può essere diventato invalido,
        perché la validazione dipende da `date.today()`."""
        emesso = datetime(2026, 8, 20, 9, 0)
        gettone = confirmation.issue("riferimento", {"a": 1}, now=emesso)

        with pytest.raises(confirmation.Rejected) as rifiuto:
            confirmation.redeem("riferimento", gettone,
                                now=emesso + confirmation.VALID_FOR
                                + timedelta(seconds=1))
        assert "mezz'ora" in rifiuto.value.reason

    def test_the_payload_cannot_be_reached_from_the_token(self):
        """Il gettone è opaco: non contiene i valori, li indica.

        Un gettone firmato che *porta* i valori si può leggere, e si può
        rigiocare finché non scade. Questo si consuma.
        """
        gettone = confirmation.issue("riferimento", {"time": "4:35,10"})
        assert "4:35" not in gettone and "time" not in gettone

    def test_an_invented_token_is_refused_with_a_sentence_a_person_can_read(self):
        with pytest.raises(confirmation.Rejected) as rifiuto:
            confirmation.redeem("riferimento", "inventato")
        assert "anteprima" in rifiuto.value.reason.lower()

    def test_the_stored_values_are_a_copy(self):
        """Chi ha emesso il gettone non può cambiare cosa è stato approvato
        modificando il dizionario che aveva in mano."""
        campi = {"time": "4:35,10"}
        gettone = confirmation.issue("riferimento", campi)
        campi["time"] = "3:35,10"

        assert confirmation.redeem("riferimento", gettone).payload["time"] == "4:35,10"
