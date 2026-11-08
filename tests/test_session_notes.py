"""Quello che l'atleta sa e i dati non possono sapere.

La finalità di una serie non sta nel file FIT. Senza, il coach può dire «il
passo è rallentato» e non «cedimento», e la differenza fra le due frasi è tutto
il valore di questo modulo.

Le note vanno nel diario in ``coach/``, non nel database: il database si
ricostruisce da zero, e una nota scritta lì dentro sparirebbe alla prima
ricostruzione (Regola Aurea n.3).
"""

from datetime import date, datetime

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach import athlete_files
from garmin_coach.app import build, security
from garmin_coach.database import SCHEMA

NOSTRA_ORIGINE = {"origin": "http://127.0.0.1:8765"}
GIORNO = date(2026, 8, 20)

NOTA = {"activity_id": "7", "day": GIORNO.isoformat(), "rpe": "7",
        "purpose": "soglia", "feeling": "spalla ok"}


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    for nome in ("atleta.md", "gare.md", "obiettivi.md"):
        (cartella / nome).write_text("# vuoto\n", encoding="utf-8")
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
        "(7, ?, ?, ?, 'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 1, 'sha', ?)",
        [datetime(2026, 8, 20, 20), datetime(2026, 8, 20, 20), GIORNO,
         datetime(2026, 1, 1)])
    con.close()
    monkeypatch.setattr("garmin_coach.paths.DATABASE", percorso)
    return percorso


@pytest.fixture
def client(database, coach_dir):
    return TestClient(build())


class TestValidation:
    @pytest.mark.parametrize("campo,valore,atteso", [
        ("rpe", "12", "da 1 a 10"),
        ("rpe", "0", "da 1 a 10"),
        ("rpe", "sette", "numero"),
        ("purpose", "divertimento", "Finalità non prevista"),
        ("activity_id", "", "identificativo"),
    ])
    def test_a_wrong_field_is_named(self, campo, valore, atteso):
        with pytest.raises(athlete_files.InvalidReference) as errore:
            athlete_files.validate_session_note(**{**NOTA, campo: valore})
        assert atteso.lower() in str(errore.value).lower()

    def test_an_empty_note_is_refused_instead_of_written(self):
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.validate_session_note(
                activity_id="7", day=GIORNO.isoformat())

    def test_not_declaring_the_purpose_is_a_legitimate_answer(self):
        nota = athlete_files.validate_session_note(
            activity_id="7", day=GIORNO.isoformat(), rpe="6")
        assert nota.purpose == "non dichiarata"

    def test_the_scale_is_the_one_the_data_showed(self):
        """CR10, ricavata dai 499 valori storici di workoutRpe: solo decine."""
        assert (athlete_files.RPE_MIN, athlete_files.RPE_MAX) == (1, 10)


class TestWritingGoesToTheDiaryNotTheDatabase:
    def test_a_note_is_written_and_read_back(self, coach_dir):
        nota = athlete_files.validate_session_note(**NOTA)
        athlete_files.add_session_note(nota)

        assert "fatica percepita: **7/10**" in " ".join(
            athlete_files.session_notes(7))

    def test_a_note_never_touches_the_database(self, client, database):
        prima = database.stat().st_mtime
        client.post("/sedute/nota/conferma",
                    data={**NOTA, security.FIELD: security.TOKEN},
                    headers=NOSTRA_ORIGINE)
        assert database.stat().st_mtime == prima, (
            "il database si ricostruisce da zero: una nota li dentro sparirebbe")

    def test_it_lands_in_the_week_of_the_session_not_of_today(self, coach_dir):
        athlete_files.add_session_note(athlete_files.validate_session_note(**NOTA))
        anno, settimana, _ = GIORNO.isocalendar()
        assert (coach_dir / "diario" / f"{anno}-W{settimana:02d}.md").exists()

    def test_notes_from_other_sessions_are_not_mixed_in(self, coach_dir):
        athlete_files.add_session_note(athlete_files.validate_session_note(**NOTA))
        athlete_files.add_session_note(athlete_files.validate_session_note(
            **{**NOTA, "activity_id": "8", "feeling": "altra seduta"}))

        assert "altra seduta" not in " ".join(athlete_files.session_notes(7))


class TestTheFormOnTheSessionPage:
    def test_the_session_page_offers_the_form(self, client):
        risposta = client.get("/sedute/7")
        assert 'action="/sedute/nota"' in risposta.text
        assert "Fatica percepita" in risposta.text

    def test_the_preview_shows_what_will_be_written(self, client):
        risposta = client.post("/sedute/nota",
                               data={**NOTA, security.FIELD: security.TOKEN},
                               headers=NOSTRA_ORIGINE)
        assert "Sto per aggiungere" in risposta.text
        assert "fatica percepita 7/10" in risposta.text
        assert athlete_files.session_notes(7) == [], "l'anteprima non scrive"

    def test_only_the_confirmation_writes(self, client):
        """Il giro completo: anteprima, poi conferma. La seconda da sola non vale."""
        from conftest import scrivi_nota

        scrivi_nota(client, NOTA, security.TOKEN)
        assert athlete_files.session_notes(7)

    def test_the_written_note_appears_on_the_session_page(self, client):
        from conftest import scrivi_nota

        scrivi_nota(client, NOTA, security.TOKEN)
        risposta = client.get("/sedute/7")
        assert "Quello che hai gia scritto" in risposta.text
        assert "spalla ok" in risposta.text

    @pytest.mark.parametrize("percorso", ["/sedute/nota", "/sedute/nota/conferma"])
    def test_a_write_from_another_site_is_refused(self, client, percorso):
        risposta = client.post(percorso,
                               data={**NOTA, security.FIELD: security.TOKEN},
                               headers={"origin": "https://sito-cattivo.example"})
        assert risposta.status_code == 403
        assert athlete_files.session_notes(7) == []
