"""Gare, riferimenti confermati, e l'unica scrittura dell'applicazione.

Due cose vanno difese qui più di tutte:

1. **Che il coach non inventi un tempo.** Finché l'atleta non conferma una
   prova, CSS, ritmi e previsioni restano chiusi — e la pagina deve dirlo, non
   tacere e mostrare una tabella vuota.
2. **Che nessuno scriva in `coach/` al posto suo.** Un server locale è
   raggiungibile da qualunque pagina web aperta nello stesso browser: la
   protezione CSRF non è teoria, è la ragione per cui questa route esiste così.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach import athlete_files
from garmin_coach.analysis import races
from garmin_coach.analysis.insight import Status
from garmin_coach.app import build, security
from garmin_coach.database import SCHEMA

NOSTRA_ORIGINE = {"origin": "http://127.0.0.1:8765"}

VALIDO = {
    "day": "2024-03-10", "distance_m": "400", "stroke": "stile", "pool": "25",
    "time": "4:38,20", "kind": "gara", "context": "Regionali",
    "activity_id": "", "notes": "",
}


# ── Lettura e scrittura del formato ──────────────────────────────────────

class TestTheTimeFormatSwimmersActuallyUse:
    @pytest.mark.parametrize("testo,secondi", [
        ("1:02,4", 62.4),
        ("1:02.4", 62.4),
        ("4:35,10", 275.1),
        ("58,9", 58.9),
        ("28", 28.0),
    ])
    def test_it_accepts_how_a_swimmer_writes_a_time(self, testo, secondi):
        assert athlete_files.parse_swim_time(testo) == pytest.approx(secondi)

    @pytest.mark.parametrize("testo", ["", "ciao", "1:2:3", "1:75,0", "-4"])
    def test_it_refuses_what_is_not_a_time(self, testo):
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.parse_swim_time(testo)

    def test_it_writes_back_the_way_it_reads(self):
        assert athlete_files.format_swim_time(278.2) == "4:38,20"


class TestValidationRefusesInsteadOfGuessing:
    @pytest.mark.parametrize("campo,valore,atteso", [
        ("day", "", "data"),
        ("day", "2099-01-01", "futuro"),
        ("distance_m", "333", "Distanza"),
        ("stroke", "crawl", "Stile"),
        ("pool", "33", "Vasca"),
        ("time", "0:04,0", "passo"),
        ("activity_id", "non-un-numero", "numero"),
    ])
    def test_a_wrong_field_is_named_in_the_message(self, campo, valore, atteso):
        with pytest.raises(athlete_files.InvalidReference) as errore:
            athlete_files.validate_reference(**{**VALIDO, campo: valore})
        assert atteso.lower() in str(errore.value).lower()

    def test_a_typo_is_refused_not_silently_corrected(self):
        """Un 400 in quattro secondi è un errore di battitura. Correggerlo da
        soli significherebbe inventare il tempo dell'atleta."""
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.validate_reference(**{**VALIDO, "time": "0:04,0"})

    def test_a_pipe_in_a_note_cannot_break_the_table(self):
        riferimento = athlete_files.validate_reference(
            **{**VALIDO, "notes": "corsia 3 | malato\ndue righe"})
        assert "|" not in riferimento.notes
        assert "\n" not in riferimento.notes


# ── Scrittura nel file vero, in una copia usa e getta ────────────────────

@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    """Una cartella `coach/` finta, per non toccare quella dell'atleta."""
    cartella = tmp_path / "coach"
    cartella.mkdir()
    (cartella / "riferimenti.md").write_text(
        "# Riferimenti\n\n"
        "| Data | Distanza | Stile | Vasca | Tempo | Tipo | Contesto | Seduta Garmin | Note |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| 2020-01-01 (esempio) | 100 | stile | 25 | 1:00,0 | gara | esempio | | esempio |\n"
        "\n## Le tue prove confermate\n\n"
        "| Data | Distanza | Stile | Vasca | Tempo | Tipo | Contesto | Seduta Garmin | Note |\n"
        "|---|---|---|---|---|---|---|---|---|\n",
        encoding="utf-8")
    (cartella / "gare.md").write_text("# Gare\n", encoding="utf-8")
    (cartella / "atleta.md").write_text("# Profilo\n", encoding="utf-8")
    (cartella / "obiettivi.md").write_text("# Obiettivi\n", encoding="utf-8")
    monkeypatch.setattr("garmin_coach.paths.COACH", cartella)
    return cartella


class TestWritingAReference:
    def test_a_written_reference_can_be_read_back_identical(self, coach_dir):
        riferimento = athlete_files.validate_reference(**VALIDO)
        athlete_files.add_reference(riferimento)

        riletti = athlete_files.references()

        assert len(riletti) == 1
        assert riletti[0].seconds == pytest.approx(riferimento.seconds)
        assert riletti[0].distance_m == 400

    def test_the_example_row_is_never_read_as_a_real_time(self, coach_dir):
        assert athlete_files.references() == []

    def test_it_writes_into_the_last_table_not_the_example_one(self, coach_dir):
        athlete_files.add_reference(athlete_files.validate_reference(**VALIDO))
        testo = (coach_dir / "riferimenti.md").read_text(encoding="utf-8")

        posizione_esempio = testo.index("(esempio)")
        posizione_nuova = testo.index("2024-03-10")
        assert posizione_nuova > posizione_esempio

    def test_a_hand_written_broken_row_does_not_hide_the_good_ones(self, coach_dir):
        percorso = coach_dir / "riferimenti.md"
        percorso.write_text(
            percorso.read_text(encoding="utf-8")
            + "| 2023-05-05 | 400 | stile | 25 | non-un-tempo | gara | | | |\n"
              "| 2023-06-06 | 200 | stile | 25 | 2:10,0 | gara | | | |\n",
            encoding="utf-8")

        riletti = athlete_files.references()

        assert [r.distance_m for r in riletti] == [200]

    def test_it_refuses_to_invent_the_file(self, coach_dir):
        (coach_dir / "riferimenti.md").unlink()
        with pytest.raises(athlete_files.InvalidReference):
            athlete_files.add_reference(athlete_files.validate_reference(**VALIDO))


# ── Quello che resta bloccato, e lo dice ─────────────────────────────────

@pytest.fixture
def database(tmp_path, monkeypatch):
    percorso = tmp_path / "coach.duckdb"
    con = duckdb.connect(str(percorso))
    con.execute(SCHEMA)
    # Un solo INSERT invece di quattrocento: la fixture costava quattro secondi
    # a test, cioe piu di tutto il resto della suite messo insieme.
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, activity_date, sport,
                                is_swim, environment, distance_m, duration_s,
                                source_object_id, imported_at)
        SELECT i,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::DATE,
               'lap_swimming', TRUE, 'pool', 3000, 3600, 'sha', TIMESTAMP '2026-01-01'
        FROM range(1, 400) t(i)
    """)
    con.close()
    monkeypatch.setattr("garmin_coach.paths.DATABASE", percorso)
    return percorso


class TestWhatStaysBlockedUntilTheAthleteConfirmsATime:
    def test_without_references_no_predicted_time_appears(self, database, coach_dir):
        with duckdb.connect(str(database), read_only=True) as connection:
            packet = races.observation(connection, today=date(2026, 8, 21))

        assert not packet.comparisons
        testo = " ".join([packet.observation] + packet.limitations).lower()
        assert "tempo di gara atteso" in testo
        assert "non calcolabile" in testo

    def test_each_blocked_function_says_what_is_missing(self, database, coach_dir):
        with duckdb.connect(str(database), read_only=True) as connection:
            packet = races.observation(connection, today=date(2026, 8, 21))

        limiti = " ".join(packet.limitations)
        for cosa, _perche in races.BLOCKED_BY_MISSING_REFERENCES:
            assert cosa in limiti, f"{cosa} bloccata senza dirlo"

    def test_a_confirmed_time_appears_in_the_curve(self, database, coach_dir):
        athlete_files.add_reference(athlete_files.validate_reference(**VALIDO))

        with duckdb.connect(str(database), read_only=True) as connection:
            packet = races.observation(connection, today=date(2026, 8, 21))

        assert len(packet.comparisons) == 1
        assert packet.comparisons[0]["time_display"] == "4:38,20"

    def test_the_tolerated_volume_band_is_never_a_prescription(self, database, coach_dir):
        with duckdb.connect(str(database), read_only=True) as connection:
            packet = races.observation(connection, today=date(2026, 8, 21))

        limiti = " ".join(packet.limitations).lower()
        assert "non quello che puoi sostenere" in limiti
        for vietato in ("puoi arrivare a", "dovresti fare", "aumenta a"):
            assert vietato not in limiti

    def test_without_a_declared_race_it_does_not_invent_one(self, database, coach_dir):
        with duckdb.connect(str(database), read_only=True) as connection:
            packet = races.observation(connection, today=date(2026, 8, 21))

        assert packet.status == Status.INSUFFICIENT_DATA
        assert "non la inventa" in packet.observation


# ── La protezione della scrittura ────────────────────────────────────────

@pytest.fixture
def client(database, coach_dir):
    return TestClient(build())


class TestNobodyElseCanWriteIntoCoach:
    def test_a_post_without_the_token_is_refused(self, client):
        risposta = client.post("/gare/riferimenti", data=VALIDO,
                               headers=NOSTRA_ORIGINE)
        assert risposta.status_code == 403

    def test_a_post_from_another_site_is_refused_even_with_the_token(self, client):
        """È l'attacco vero: una pagina qualunque aperta nello stesso browser
        può inviare un modulo verso 127.0.0.1."""
        risposta = client.post(
            "/gare/riferimenti", data={**VALIDO, security.FIELD: security.TOKEN},
            headers={"origin": "https://sito-cattivo.example"})
        assert risposta.status_code == 403

    def test_a_post_without_any_origin_is_refused(self, client):
        risposta = client.post(
            "/gare/riferimenti", data={**VALIDO, security.FIELD: security.TOKEN})
        assert risposta.status_code == 403

    def test_the_refusal_explains_itself_in_italian(self, client):
        risposta = client.post("/gare/riferimenti", data=VALIDO,
                               headers=NOSTRA_ORIGINE)
        assert "Traceback" not in risposta.text
        assert "riprova" in risposta.text.lower()


class TestNothingIsWrittenWithoutSeeingItFirst:
    def test_the_form_only_leads_to_a_preview(self, client, coach_dir):
        risposta = client.post(
            "/gare/riferimenti", data={**VALIDO, security.FIELD: security.TOKEN},
            headers=NOSTRA_ORIGINE)

        assert risposta.status_code == 200
        assert "Sto per aggiungere" in risposta.text
        assert athlete_files.references() == [], "l'anteprima non deve scrivere"

    def test_the_preview_shows_exactly_what_will_be_written(self, client):
        risposta = client.post(
            "/gare/riferimenti", data={**VALIDO, security.FIELD: security.TOKEN},
            headers=NOSTRA_ORIGINE)

        assert "4:38,20" in risposta.text
        assert "400 m stile" in risposta.text

    def test_only_the_confirmation_writes(self, client, coach_dir):
        """Il giro completo, come lo fa una persona: prima si vede, poi si scrive.

        Prima questo test andava dritto alla conferma, e passava: era il difetto
        scritto dentro il collaudo. Ora la conferma senza anteprima non vale, e
        c'e un test apposta che lo pretende.
        """
        from conftest import scrivi_riferimento

        scrivi_riferimento(client, VALIDO, security.TOKEN)

        assert len(athlete_files.references()) == 1

    def test_an_invalid_form_comes_back_with_the_values_still_in_it(self, client):
        risposta = client.post(
            "/gare/riferimenti",
            data={**VALIDO, "time": "0:04,0", security.FIELD: security.TOKEN},
            headers=NOSTRA_ORIGINE)

        assert risposta.status_code == 400
        assert "fuori da quello che" in risposta.text
        assert 'value="Regionali"' in risposta.text, (
            "rifiutare un modulo svuotandolo è il modo di non farlo usare mai")

    def test_writing_never_touches_the_database(self, client, database, coach_dir):
        prima = database.stat().st_mtime
        client.post("/gare/riferimenti/conferma",
                    data={**VALIDO, security.FIELD: security.TOKEN},
                    headers=NOSTRA_ORIGINE)
        assert database.stat().st_mtime == prima, (
            "le scritture umane vivono in coach/, il database resta generato")
