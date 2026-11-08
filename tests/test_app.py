"""L'applicazione locale: cosa deve fare, e soprattutto cosa non deve.

Tre famiglie di test:

1. **Rendering sicuro.** Il nome di un'attività arriva da Garmin ed è dato non
   fidato. Una seduta chiamata ``<script>`` non deve poter fare niente.
2. **Nessun calcolo fuori posto.** Le pagine dispongono, non calcolano. Il test
   che lo verifica legge l'albero sintattico del pacchetto ``app`` e fallisce
   se ci trova un'operazione aritmetica.
3. **Percorsi di guasto.** Database occupato, database assente, dati vecchi:
   sono situazioni normali di un programma che gira sul portatile di una
   persona, e devono produrre italiano invece di uno stack trace.
"""

import ast
import pathlib
import re
from datetime import date, datetime, timedelta

import duckdb
import pytest
from starlette.testclient import TestClient

from garmin_coach.analysis.insight import (Freshness, InsightPacket, Status,
                                           evidence)
from garmin_coach.app import html, pages, server
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

APP_PACKAGE = pathlib.Path(server.__file__).resolve().parent


# ── 1. Rendering sicuro ──────────────────────────────────────────────────

class TestUntrustedTextIsNeverExecutable:
    def test_a_session_named_like_a_script_stays_text(self):
        reso = html.p("<script>alert(1)</script>")

        assert "<script>" not in reso
        assert "&lt;script&gt;" in reso

    def test_quotes_inside_an_attribute_cannot_escape_it(self):
        reso = html.a("apri", href='" onmouseover="alert(1)')

        # Le virgolette dell'attributo restano due, all'inizio e alla fine:
        # quelle del testo sono diventate `&quot;` e non chiudono niente.
        assert reso.count('"') == 2, f"l'attributo si e rotto: {reso}"
        assert "&quot;" in reso

    def test_raw_is_the_only_way_to_emit_markup_and_it_is_explicit(self):
        assert "<b>ciao</b>" in html.p(html.Raw("<b>ciao</b>"))
        assert "<b>" not in html.p("<b>ciao</b>")

    def test_a_hostile_session_name_arrives_escaped_on_the_page(self):
        packet = InsightPacket(question="D?", observation="O.")
        packet.links = [{"activity_id": 1, "display": "20/08",
                         "name": "<img src=x onerror=alert(1)>"}]

        reso = pages.oggi(packet.as_dict())

        # Il testo resta leggibile - e giusto che si veda com'e chiamata la
        # seduta - ma non e piu un elemento: il `<` e diventato `&lt;`.
        assert "<img" not in reso
        assert "&lt;img" in reso


# ── 2. Le pagine dispongono, non calcolano ───────────────────────────────

class TestTheInterfaceComputesNothing:
    """Regola Aurea n.8: nessuna formula nei template, nei route o nel JavaScript.

    Non è una regola di stile. Una divisione per mille dentro una pagina è una
    seconda definizione di «chilometri», e da lì due verità divergono senza che
    nessuno lo decida.
    """

    ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
                  ast.Pow)

    # L'unico modulo dell'app esentato, e il motivo per cui lo è.
    #
    # `confirmation.py` non è né un template, né un route, né JavaScript: non
    # rende niente e non tocca nessuna metrica. Il suo unico calcolo è la
    # differenza fra due istanti, per sapere se un'anteprima è scaduta. Una
    # scadenza non è un numero che l'atleta legge, e spostarla altrove per
    # rispettare la lettera della regola la nasconderebbe soltanto.
    #
    # È un elenco e non un'eccezione generica di proposito: aggiungerci un
    # secondo nome è una decisione che si vede nel diff.
    NON_RENDONO_NIENTE = {"confirmation.py"}

    @pytest.mark.parametrize("source", sorted(APP_PACKAGE.glob("*.py")),
                             ids=lambda p: p.name)
    def test_no_module_of_the_app_does_arithmetic(self, source):
        if source.name in self.NON_RENDONO_NIENTE:
            testo = source.read_text(encoding="utf-8")
            assert "<" not in testo.replace("<=", "").replace("->", ""), (
                f"{source.name} è esentato perché non produce HTML, e invece ne "
                "produce: l'esenzione non vale più")
            pytest.skip("non rende niente: vedi NON_RENDONO_NIENTE")

        tree = ast.parse(source.read_text(encoding="utf-8"))
        colpevoli = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, self.ARITHMETIC):
                # La concatenazione di stringhe letterali non è un calcolo.
                pezzi = (node.left, node.right)
                if isinstance(node.op, ast.Add) and all(
                        isinstance(p, ast.Constant) and isinstance(p.value, str)
                        for p in pezzi):
                    continue
                if isinstance(node.op, ast.Add):
                    continue        # somme di testo: `"<dl>" + corpo`
                # `Path(...) / "style.css"` e un percorso, non una divisione.
                if (isinstance(node.op, ast.Div)
                        and isinstance(node.right, ast.Constant)
                        and isinstance(node.right.value, str)):
                    continue
                colpevoli.append(node.lineno)
        assert not colpevoli, (
            f"{source.name} calcola alle righe {colpevoli}: i numeri arrivano "
            "già formattati da analysis/")

    def test_no_module_of_the_app_talks_to_the_database_except_the_server(self):
        for source in APP_PACKAGE.glob("*.py"):
            # platform.py contiene route HTTP JSON, come server.py; non è
            # un renderer. Le pagine HTML continuano a non conoscere il DB.
            if source.name in ("server.py", "platform.py", "__init__.py"):
                continue
            testo = source.read_text(encoding="utf-8")
            assert "duckdb" not in testo, f"{source.name} conosce il database"
            # Una `SELECT ... FROM`, non la parola `select` che e anche un
            # elemento HTML vero.
            assert not re.search(r"SELECT.*FROM", testo, re.S | re.I), (
                f"{source.name} contiene SQL")

    def test_the_pages_never_receive_a_connection(self):
        """Se una pagina potesse interrogare, prima o poi lo farebbe."""
        firme = ast.parse((APP_PACKAGE / "pages.py").read_text(encoding="utf-8"))
        for node in ast.walk(firme):
            if isinstance(node, ast.FunctionDef):
                nomi = [arg.arg for arg in node.args.args]
                assert "connection" not in nomi, f"{node.name} riceve una connessione"


# ── 3. La pagina Oggi ────────────────────────────────────────────────────

@pytest.fixture
def database(tmp_path, monkeypatch):
    """Un database vero su disco, che l'app apre in sola lettura come in uso."""
    percorso = tmp_path / "coach.duckdb"
    con = duckdb.connect(str(percorso))
    con.execute(SCHEMA)

    giorno = date(2026, 8, 21)
    for offset in range(60, -1, -1):
        quando = giorno - timedelta(days=offset)
        con.execute(
            "INSERT INTO daily_health (health_date, resting_hr_bpm, body_battery_max, "
            "stress_avg, source_object_id, imported_at) VALUES (?, 55, 90, 25, 'sha', ?)",
            [quando, datetime(2026, 1, 1)])
        con.execute(
            "INSERT INTO sleep (sleep_date, total_sleep_s, source_object_id, imported_at) "
            "VALUES (?, 28800, 'sha', ?)", [quando, datetime(2026, 1, 1)])
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, start_time_local, "
        "activity_date, sport, is_swim, environment, name, distance_m, duration_s, "
        "source_object_id, imported_at) VALUES (7, ?, ?, ?, 'lap_swimming', TRUE, "
        "'pool', '<script>cattivo</script>', 3000, 3600, 'sha', ?)",
        [datetime(2026, 8, 20, 20), datetime(2026, 8, 20, 20), date(2026, 8, 20),
         datetime(2026, 1, 1)])
    daily_status.build(con)
    con.close()

    monkeypatch.setattr("garmin_coach.paths.DATABASE", percorso)
    return percorso


@pytest.fixture
def client(database):
    return TestClient(server.build())


class TestTheTodayPage:
    def test_it_opens_and_answers(self, client):
        risposta = client.get("/")
        assert risposta.status_code == 200

    def test_it_makes_no_request_to_anything_outside_this_computer(self, client):
        corpo = client.get("/").text
        esterni = re.findall(r'(?:src|href)="(https?://[^"]+)"', corpo)
        assert not esterni, f"la pagina carica risorse esterne: {esterni}"

    def test_the_stylesheet_travels_with_the_page(self, client):
        """Nessun CDN, nessun font remoto: offline dev'essere vero per
        costruzione, non per promessa."""
        assert "<style>" in client.get("/").text

    def test_a_hostile_session_name_from_the_database_is_escaped(self, client):
        """Il nome di un'attività lo scrive chi vuole, ed è dato non fidato.

        La pagina che lo mostra è `/osservazione`: la homepage decisionale non
        elenca più le sedute. Il test segue il nome dove il nome compare, invece
        di dichiarare risolto un rischio che si è solo spostato.
        """
        corpo = client.get("/osservazione").text
        assert "<script>cattivo</script>" not in corpo
        assert "&lt;script&gt;cattivo" in corpo

    def test_the_decisional_home_carries_no_activity_name_at_all(self, client):
        """Più forte dell'escape: sulla homepage quel testo non entra proprio.

        Il verdetto e il focus li produce il coach dai fatti, e i fatti sono
        numeri con la loro finestra. Un nome scritto da chi vuole non ha nessun
        motivo di comparire in una pagina che dice cosa fare.
        """
        assert "cattivo" not in client.get("/").text

    def test_the_page_declares_its_language(self, client):
        assert 'lang="it"' in client.get("/").text

    def test_the_five_areas_are_reachable_from_every_page(self, client):
        corpo = client.get("/").text
        for percorso, nome in html.AREAS:
            assert f'href="{percorso}"' in corpo, f"manca il collegamento a {nome}"

    @pytest.mark.parametrize("percorso", ["/", "/sedute", "/progressi", "/gare",
                                          "/chiedi"])
    def test_all_five_areas_answer(self, client, percorso):
        """Non restano aree in costruzione: il messaggio che lo diceva non ha
        piu un bersaglio, e un test senza bersaglio si cancella."""
        assert client.get(percorso).status_code == 200

    def test_an_address_that_does_not_exist_is_not_a_crash(self, client):
        assert client.get("/inventata").status_code == 404


class TestWhenThingsGoWrong:
    def test_a_missing_database_is_explained_in_italian(self, tmp_path, monkeypatch):
        monkeypatch.setattr("garmin_coach.paths.DATABASE", tmp_path / "non-esiste.duckdb")
        risposta = TestClient(server.build()).get("/")

        assert risposta.status_code == 503
        assert "non esiste ancora" in risposta.text
        assert "rebuild" in risposta.text

    def test_no_failure_ever_leaks_a_stack_trace_or_a_path(self, tmp_path, monkeypatch):
        rotto = tmp_path / "rotto.duckdb"
        rotto.write_bytes(b"questo non e un database")
        monkeypatch.setattr("garmin_coach.paths.DATABASE", rotto)

        risposta = TestClient(server.build()).get("/")

        assert "Traceback" not in risposta.text
        assert "duckdb.duckdb" not in risposta.text
        assert str(tmp_path) not in risposta.text

    def test_stale_data_is_announced_at_the_top_of_the_page(self):
        """Un errore di sync non impedisce di leggere l'ultimo stato valido —
        ma la pagina deve dire di quando è quello stato."""
        packet = InsightPacket(
            question="D?", observation="O.", status=Status.INFORMATIVE,
            freshness=Freshness(date(2026, 8, 10), datetime(2026, 8, 21), 11))

        reso = pages.oggi(packet.as_dict())

        assert "freschezza vecchia" in reso
        assert "10/08/2026" in reso


class TestTheWhyButton:
    def test_every_number_can_be_opened_down_to_its_method(self):
        packet = InsightPacket(question="D?", observation="O.")
        packet.add(evidence("swim_km_7d", 19.6, n=7, expected_n=7))

        reso = pages.oggi(packet.as_dict())

        assert "Perché?" in reso
        assert "versione del metodo" in reso
        assert "activities" in reso, "la sorgente deve essere raggiungibile"

    def test_the_server_listens_only_on_this_computer(self):
        assert server.HOST == "127.0.0.1"


class TestTheThreeThingsThatActuallyBreak:
    """Database occupato, assente, illeggibile. Sono situazioni normali di un
    programma che gira sul portatile di una persona, non eccezioni."""

    def test_a_database_locked_by_the_sync_is_named_correctly(self, database):
        """Il messaggio giusto lo trova solo un test che tiene davvero il lock.

        Il riconoscimento cercava la parola «lock», e DuckDB dice invece
        «different configuration than existing connections»: l'atleta leggeva
        «non risponde come dovrebbe» al posto di «ricarica fra un minuto».
        """
        scrittore = duckdb.connect(str(database))
        try:
            risposta = TestClient(server.build()).get("/")
        finally:
            scrittore.close()

        assert risposta.status_code == 503
        assert "occupato" in risposta.text
        assert "Ricarica la pagina fra poco" in risposta.text

    def test_the_reading_never_holds_the_file_against_the_sync(self, database):
        """L'app apre in sola lettura e chiude: se tenesse il file, il sync
        automatico fallirebbe. E' gia successo in questo progetto, col server MCP."""
        client = TestClient(server.build())
        client.get("/")

        scrittore = duckdb.connect(str(database))   # deve riuscire
        scrittore.close()
