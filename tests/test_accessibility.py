"""Le cose che rendono una pagina usabile anche quando non la si guarda bene.

Niente toolchain: nessun browser headless, nessun motore di regole da tenere
aggiornato. Solo i controlli che si possono fare leggendo l'HTML, che sono
anche quelli che si sbagliano davvero — un campo senza etichetta, un grafico
senza descrizione, un contorno di focus tolto perché «è brutto».

L'incarico chiede test accessibilità «senza introdurre una toolchain
sproporzionata»: questi sono quelli, e il loro limite è dichiarato in fondo.
"""

import re
from datetime import date, datetime, timedelta

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach.app import server
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

AREE = ["/", "/sedute", "/progressi", "/gare", "/chiedi"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    percorso = tmp_path / "coach.duckdb"
    con = duckdb.connect(str(percorso))
    con.execute(SCHEMA)
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
                                activity_date, sport, is_swim, environment,
                                distance_m, duration_s, pool_length_m, device_id,
                                source_object_id, imported_at)
        SELECT i, (DATE '2026-08-20' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::DATE,
               'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 1, 'sha',
               TIMESTAMP '2026-01-01'
        FROM range(1, 300) t(i)
    """)
    con.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, source_object_id, "
        "imported_at) SELECT (DATE '2026-08-20' - INTERVAL (i) DAY)::DATE, 55, "
        "'sha', TIMESTAMP '2026-01-01' FROM range(1, 300) t(i)")
    daily_status.build(con)
    con.close()
    monkeypatch.setattr("garmin_coach.paths.DATABASE", percorso)

    cartella = tmp_path / "coach"
    cartella.mkdir()
    for nome in ("atleta.md", "gare.md", "obiettivi.md", "riferimenti.md"):
        (cartella / nome).write_text("# vuoto\n", encoding="utf-8")
    monkeypatch.setattr("garmin_coach.paths.COACH", cartella)
    return TestClient(server.build())


@pytest.mark.parametrize("percorso", AREE)
class TestOgniPagina:
    def test_declares_its_language(self, client, percorso):
        """Senza `lang`, un lettore di schermo pronuncia l'italiano all'inglese."""
        assert 'lang="it"' in client.get(percorso).text

    def test_has_exactly_one_first_level_heading(self, client, percorso):
        corpo = client.get(percorso).text
        assert len(re.findall(r"<h1[ >]", corpo)) == 1

    def test_never_skips_a_heading_level(self, client, percorso):
        livelli = [int(n) for n in
                   re.findall(r"<h([1-6])[ >]", client.get(percorso).text)]
        for prima, dopo in zip(livelli, livelli[1:]):
            assert dopo <= prima + 1, (
                f"{percorso}: si salta da h{prima} a h{dopo}")

    def test_every_field_has_a_label_attached_to_it(self, client, percorso):
        corpo = client.get(percorso).text
        # Gli attributi si leggono senza dipendere dal loro ordine: un test che
        # pretende `aria-label` prima di `id` collauda il generatore di HTML,
        # non l'accessibilità.
        campi, etichettati_da_soli = [], set()
        for attributi in re.findall(r'<(?:input|select|textarea)\b([^>]*)>', corpo):
            trovato = re.search(r'\bid="([^"]+)"', attributi)
            if not trovato:
                continue
            campi.append(trovato.group(1))
            if 'aria-label="' in attributi:
                etichettati_da_soli.add(trovato.group(1))
        etichette = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', corpo))
        for campo in campi:
            assert campo in etichette or campo in etichettati_da_soli, (
                f"{percorso}: il campo «{campo}» non ha etichetta")

    def test_no_hidden_field_pretends_to_need_one(self, client, percorso):
        """I campi nascosti non hanno etichetta, e non devono averla."""
        nascosti = re.findall(r'<input\b[^>]*type="hidden"[^>]*>',
                              client.get(percorso).text)
        for campo in nascosti:
            assert "aria-label" not in campo


class TestQuelloCheNonSiVede:
    def test_the_chart_can_be_read_without_seeing_it(self, client):
        corpo = client.get("/progressi").text
        if "<svg" not in corpo:
            pytest.skip("nessun grafico in questo insieme di dati")
        assert 'role="img"' in corpo
        assert "aria-label" in corpo
        assert corpo.count("<title>") >= corpo.count("<rect")

    def test_the_focus_outline_is_never_removed(self):
        css = (server.Path(server.__file__).parent / "style.css").read_text(
            encoding="utf-8")
        assert "outline: none" not in css.replace(" ", " ")
        assert ":focus-visible" in css, (
            "senza contorno di focus, navigare da tastiera è impossibile")

    def test_the_page_works_in_both_light_and_dark(self):
        css = (server.Path(server.__file__).parent / "style.css").read_text(
            encoding="utf-8")
        assert "prefers-color-scheme: dark" in css

    def test_the_narrow_layout_is_declared(self):
        css = (server.Path(server.__file__).parent / "style.css").read_text(
            encoding="utf-8")
        assert "max-width: 420px" in css, "360 px è un vincolo, non un caso limite"

    def test_the_navigation_says_what_it_is(self, client):
        assert 'aria-label="Aree del coach"' in client.get("/").text

    def test_the_current_area_is_announced(self, client):
        assert 'aria-current="page"' in client.get("/").text


def test_what_these_tests_do_not_cover():
    """Il limite, dichiarato invece che taciuto.

    Questi controlli leggono l'HTML. Non misurano il contrasto reale dei
    colori, non seguono l'ordine di tabulazione e non provano un lettore di
    schermo vero: per quelli servirebbe un browser headless e un motore di
    regole, cioè una toolchain sproporzionata per cinque pagine.

    Il contrasto è stato scelto a mano — testo #1c1b19 su #fbfbfa in chiaro,
    #eceae7 su #17181a in scuro — e va riverificato se qualcuno tocca i colori.
    """
    assert True
