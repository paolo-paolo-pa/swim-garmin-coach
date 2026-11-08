"""Le gare in mare: il tempo è misurato, la distanza è dichiarata.

## Cosa questi test difendono

1. **I tre formati di tempo di Icron finiscono tutti in secondi.** Nello stesso
   file convivono `00:25:35,005`, `00:19:57` e `00.38.39`, perché li hanno
   scritti cronometristi diversi. Una gara che non si legge è una gara persa.
2. **Una categoria non diventa una distanza.** `MASTER` e `AGONISTI` non sono
   metri, e leggerli come tali produrrebbe passi inventati su gare vere.
3. **Il miglio senza aggettivo resta senza distanza.** Fra 1.609 e 1.852 ci sono
   243 metri, Icron non dice quale sia, e sceglierne uno è inventare.
4. **Una nuotata sola classificata in due graduatorie resta una nuotata.**
5. **Le gare in mare non entrano nei record di vasca.** Un «record sui 3.000»
   costruito su due percorsi diversi chiamati entrambi 3.000 non è un record.
6. **Una distanza che non regge non produce un passo.** È la stessa scelta del
   criterio C12 sulle velocità impossibili dell'orologio, con un metro in più:
   il confronto non è con una costante universale ma con i tempi in vasca di
   questa persona.
7. **Il ciclo di vita della sorgente.** Riscrivere il CSV con meno righe toglie
   le gare sparite; cancellarlo toglie tutte le proprie e **nessuna** di quelle
   della federazione.

I casi 2 e 7, e il fatto che due gare diverse con lo stesso tempo non vanno
fuse, vengono da una revisione indipendente di questo importatore: hanno
trovato due difetti veri — un anno di categoria letto come distanza, e due
prove distinte fuse perché avevano lo stesso tempo — e stanno qui perché i
test di un modulo stanno in un file solo.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import race_history as rh
from garmin_coach import verification
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import icron


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


INTESTAZIONE = ("indice;stato;data;gara;localita;tempo_originale;"
                "posizione_generale;posizione_categoria;categoria;prova;"
                "info_scheda")


def _sorgente(tmp_path, monkeypatch, righe: list[str]):
    """Un file Icron finto in una cartella `coach/` finta.

    Riscrivere lo stesso percorso è il modo in cui si prova il ciclo di vita
    della sorgente: l'atleta riscarica il CSV e l'archivio deve seguirlo, non
    accumulare.
    """
    cartella = tmp_path / "icron" / "atleta"
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / "atleta_icron_gare.csv"
    percorso.write_text("\n".join([INTESTAZIONE, *righe]) + "\n",
                        encoding="utf-8")
    monkeypatch.setattr(icron.paths, "COACH", tmp_path)
    return percorso


def _in_vasca(con, race_id, giorno, distanza, tempo, vasca=25):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, relay_legs, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source)
        VALUES (?, ?, 'Meet', 'stile libero', ?, 'stile', false, NULL, ?, ?,
                'valid', 'A', 'sha', ?, 'piscina', 'certified_pool')
    """, [race_id, giorno, distanza, vasca, tempo, datetime(2026, 1, 1)])


def _in_mare(con, race_id, giorno, tempo, distanza, origine="event_field",
             meet="Gara", posto=None):
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, relay_legs, pool_length_m, time_s, status, timing,
            source_object_id, imported_at, environment, distance_source,
            venue, overall_place)
        VALUES (?, ?, ?, 'prova', ?, NULL, false, NULL, NULL, ?, 'valid', NULL,
                'sha', ?, 'acque libere', ?, 'place04', ?)
    """, [race_id, giorno, meet, distanza, tempo, datetime(2026, 1, 1),
          origine, posto])


# ── 1. Leggere quello che Icron scrive ───────────────────────────────────

class TestReadingTheIcronFile:
    @pytest.mark.parametrize("testo, atteso", [
        ("00:25:35,005", 1535.005),
        ("00:19:57", 1197.0),
        ("00.38.39", 2319.0),
        ("03.00.46", 10846.0),
        ("00:13:54,965", 834.965),
    ])
    def test_every_clock_format_becomes_seconds(self, testo, atteso):
        assert icron.parse_time(testo) == pytest.approx(atteso)

    def test_a_short_race_is_not_three_hours(self):
        # «00.22.51» sono 22'51", non 22 ore e 51 minuti. Leggerlo come ore
        # trasformerebbe una gara di ventidue minuti nel record di tutti i tempi.
        assert icron.parse_time("00.22.51") == pytest.approx(1371.0)

    def test_an_unreadable_time_is_not_guessed(self):
        assert icron.parse_time("boh") is None
        assert icron.parse_time("") is None

    def test_a_place_is_a_number_even_with_the_degree_sign(self):
        assert icron.parse_place("9°") == 9
        assert icron.parse_place("") is None


# ── 2. La distanza, e chi la dichiara ────────────────────────────────────

class TestWhereTheDistanceComesFrom:
    @pytest.mark.parametrize("prova, metri", [
        ("2500M", 2500),
        ("2000M", 2000),
        ("2600MT_AGONISTI", 2600),
        ("5000_AGONISTI", 5000),
        ("1800_A", 1800),
        ("1500", 1500),
        ("5K", 5000),
        ("3K", 3000),
        ("MEZZOFONDO 2.7K AGO", 2700),
        ("event02 10 KM", 10000),
    ])
    def test_the_event_field_wins_when_it_has_a_number(self, prova, metri):
        distanza = icron.parse_distance(prova, "Una gara qualunque")

        assert distanza.metres == metri
        assert distanza.source == icron.FROM_EVENT_FIELD

    def test_one_underscore_five_kilometres_is_not_fifteen(self):
        # `1_5KM` è 1,5 km. Il trattino basso qui è una virgola decimale, e
        # altrove è uno spazio: fra due cifre vuol dire una cosa sola.
        distanza = icron.parse_distance("1_5KM", "Trofeo")

        assert distanza.metres == 1500

    @pytest.mark.parametrize("categoria", [
        "MASTER", "AGONISTI", "AGONISTA", "AGONISTI_REGIONE", "AGONISTI_M",
    ])
    def test_a_category_is_not_a_distance(self, categoria):
        distanza = icron.parse_distance(categoria, "event04 place06")

        assert distanza.metres is None, (
            f"«{categoria}» è una categoria: leggerla come metri darebbe un "
            "passo inventato su una gara vera")
        assert distanza.source == icron.UNKNOWN_DISTANCE

    def test_a_category_year_is_not_a_distance(self):
        # Trovato da una revisione indipendente: la regola sul numero nudo
        # leggeva «AGONISTI 2001» come 2.001 metri.
        assert icron.parse_distance("AGONISTI 2001", "Trofeo").metres is None

    def test_a_mile_without_an_adjective_stays_without_a_distance(self):
        distanza = icron.parse_distance("MIGLIO", "II TROFEO CITTA' DI place10")

        assert distanza.metres is None, (
            "fra il miglio terrestre e quello marino ci sono 243 metri e Icron "
            "non dice quale sia: sceglierne uno è inventare")

    def test_a_nautical_mile_is_1852_and_says_where_it_read_it(self):
        distanza = icron.parse_distance("AGONISTI",
                                        "SWIM RACE place31 - MIGLIO MARINO")

        assert distanza.metres == icron.NAUTICAL_MILE_M
        assert distanza.source == icron.FROM_MEET_NAME

    def test_the_meet_name_gives_kilometres_and_nothing_else(self):
        dal_nome = icron.parse_distance("AGONISTI_M",
                                        "event08 - 3KM FIN")
        assert dal_nome.metres == 3000
        assert dal_nome.source == icron.FROM_MEET_NAME

    @pytest.mark.parametrize("nome", [
        "3* event01",
        "1° TROFEO CITTA' DI place10",
        "event03 OPEN WATER place32 2",
        "place12 - MEZZO FONDO CAMPIONATO NAZIONALE federation02",
    ])
    def test_a_number_in_the_meet_name_is_not_a_distance(self, nome):
        # L'edizione di un trofeo, la seconda tappa, la K di «Leukalè». Leggere
        # queste cifre come metri darebbe gare di tre metri.
        assert icron.parse_distance("MASTER", nome).metres is None


# ── 3. Cosa finisce in archivio ──────────────────────────────────────────

class TestWhatReachesTheArchive:
    def test_one_swim_in_two_rankings_stays_one_swim(self, connection,
                                                     tmp_path, monkeypatch):
        cartella = tmp_path / "icron" / "paolo"
        cartella.mkdir(parents=True)
        (cartella / "x_icron_gare.csv").write_text(
            "indice;stato;data;gara;localita;tempo_originale;"
            "posizione_generale;posizione_categoria;categoria;prova;info_scheda\n"
            "1;CONFERMATO;12/09/2020;event03;place16;00.44.25;"
            "10°;5°;C;AGONISTI_REGIONE;-\n"
            "2;CONFERMATO;12/09/2020;event03;place16;00.44.25;"
            "13°;7°;C;AGONISTI;-\n", encoding="utf-8")
        monkeypatch.setattr(icron.paths, "COACH", tmp_path)

        esito = icron.load(connection)

        assert esito["races"] == 1
        assert esito["duplicates"] == 1, (
            "stesso giorno, stessa manifestazione, stesso tempo: è una nuotata "
            "sola classificata in due graduatorie")

    def test_two_distances_with_the_same_time_are_two_races(
            self, connection, tmp_path, monkeypatch):
        # Trovato da una revisione indipendente: la chiave di raggruppamento
        # non conteneva la distanza, e due gare diverse chiuse con lo stesso
        # tempo diventavano una. Due gare nello stesso giorno e nella stessa
        # manifestazione ci sono davvero: il 18/05/2019 un 2.700 e un 5.000.
        _sorgente(tmp_path, monkeypatch, [
            "1;CONFERMATO;01/05/2024;TROFEO;place10;00:25:00;1°;1°;MXX;1500M;-",
            "2;CONFERMATO;01/05/2024;TROFEO;place10;00:25:00;1°;1°;MXX;3000M;-",
        ])

        assert icron.load(connection)["races"] == 2
        assert verification._open_water_in_files() == 2, (
            "C14 deve contare le gare con la stessa chiave dell'importatore: "
            "la distanza distingue due risultati con lo stesso tempo")

    def test_a_shrunken_source_loses_the_races_that_left_it(
            self, connection, tmp_path, monkeypatch):
        percorso = _sorgente(tmp_path, monkeypatch, [
            "1;CONFERMATO;01/05/2024;TROFEO;place10;00:25:00;1°;1°;MXX;1500M;-",
            "2;CONFERMATO;02/05/2024;TROFEO;place10;00:50:00;1°;1°;MXX;3000M;-",
        ])
        icron.load(connection)

        _sorgente(tmp_path, monkeypatch, [
            "1;CONFERMATO;01/05/2024;TROFEO;place10;00:25:00;1°;1°;MXX;1500M;-",
        ])
        icron.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM races").fetchone()[0] == 1, (
            "una gara tolta dalla sorgente deve sparire anche dall'archivio: "
            "l'importatore riscrive, non accumula")
        assert percorso.exists()

    def test_deleting_icron_leaves_the_pool_untouched(
            self, connection, tmp_path, monkeypatch):
        _in_vasca(connection, "vasca", date(2024, 6, 1), 400, 280.0)
        percorso = _sorgente(tmp_path, monkeypatch, [
            "1;CONFERMATO;01/05/2024;TROFEO;place10;00:25:00;1°;1°;MXX;1500M;-",
        ])
        icron.load(connection)

        percorso.unlink()
        icron.load(connection)

        assert connection.execute(
            "SELECT race_id FROM races").fetchall() == [("vasca",)], (
            "sparita la sorgente del mare, le gare della federazione restano")

    def test_importing_twice_changes_nothing(self, connection, tmp_path,
                                             monkeypatch):
        cartella = tmp_path / "icron"
        cartella.mkdir()
        (cartella / "x_icron_gare.csv").write_text(
            "indice;stato;data;gara;localita;tempo_originale;"
            "posizione_generale;posizione_categoria;categoria;prova;info_scheda\n"
            "1;CONFERMATO;23/08/2026;event01;place04;00:25:35,005;"
            "9°;3°;MXXM;2500M;-\n", encoding="utf-8")
        monkeypatch.setattr(icron.paths, "COACH", tmp_path)

        icron.load(connection)
        icron.load(connection)

        assert connection.execute("SELECT count(*) FROM races").fetchone()[0] == 1

    def test_the_sea_does_not_erase_the_pool(self, connection, tmp_path,
                                             monkeypatch):
        # Le due sorgenti di gare convivono. Un importatore che cancellasse
        # «tutte le gare» prima di riscrivere le proprie farebbe sparire quelle
        # dell'altro a ogni `ingest`.
        _in_vasca(connection, "vasca-1", date(2026, 5, 24), 400, 275.34)
        cartella = tmp_path / "icron"
        cartella.mkdir()
        (cartella / "x_icron_gare.csv").write_text(
            "indice;stato;data;gara;localita;tempo_originale;"
            "posizione_generale;posizione_categoria;categoria;prova;info_scheda\n"
            "1;CONFERMATO;23/08/2026;event01;place04;00:25:35,005;"
            "9°;3°;MXXM;2500M;-\n", encoding="utf-8")
        monkeypatch.setattr(icron.paths, "COACH", tmp_path)

        icron.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM pool_races").fetchone()[0] == 1


# ── 4. I due mondi restano separati ──────────────────────────────────────

class TestTheTwoEnvironmentsStayApart:
    def test_a_sea_race_is_not_a_pool_record(self, connection):
        _in_vasca(connection, "vasca", date(2026, 2, 15), 1500, 1139.55)
        _in_mare(connection, "mare", date(2026, 8, 23), 1535.0, 2500)

        etichette = [uno.label for uno in rh.bests(connection)]

        assert any("1500" in una for una in etichette)
        assert not any("2500" in una for una in etichette), (
            "un record sui 2.500 costruito su una distanza dichiarata "
            "dall'organizzazione non è un record")

    def test_the_last_race_can_be_at_sea_without_breaking_the_sentence(
            self, connection):
        _in_mare(connection, "mare", date(2026, 8, 23), 1535.0, 2500,
                 meet="event01")

        ultima = rh.last_race(connection, today=date(2026, 8, 24))

        assert ultima["days_ago"] == 1
        assert "vasca da None" not in ultima["display"]
        assert "event01" in ultima["display"]

    def test_a_sea_race_without_a_distance_still_exists(self, connection):
        _in_mare(connection, "mare", date(2026, 6, 20), 1643.0, None,
                 origine="unknown", meet="event04")

        gare = rh.open_water(connection)

        assert len(gare) == 1
        assert gare[0].pace_100_s is None
        assert gare[0].time_s == pytest.approx(1643.0), (
            "il tempo è cronometrato e resta, anche quando la distanza manca")


# ── 5. La distanza che non regge ─────────────────────────────────────────

class TestWhenTheDeclaredDistanceDoesNotHold:
    def test_a_pace_faster_than_your_own_hundred_is_not_a_pace(self, connection):
        # Il caso vero: event05 2025, «2000 m» in 14'15", cioè
        # 42"75/100 m. Il miglior 100 in vasca di questa persona è 55"32.
        _in_vasca(connection, "cento", date(2018, 3, 11), 100, 55.32)
        _in_vasca(connection, "millecinque", date(2026, 2, 15), 1500, 1139.55)
        _in_mare(connection, "event05", date(2025, 6, 21), 855.0, 2000)

        gara = rh.open_water(connection)[0]

        assert gara.credibility == rh.IMPOSSIBLE
        assert gara.pace_100_s is None, (
            "una velocità impossibile non è una velocità: il passo non viene "
            "calcolato più prudente, non viene calcolato")
        assert "distanza dichiarata a non reggere" in gara.credibility_reason

        pagina = rh.as_page_dict(rh.history(connection, today=date(2025, 6, 22)))
        assert "0:42.75/100 m" not in pagina["last"], (
            "anche il riepilogo dell'ultima gara deve omettere un passo che "
            "l'analisi ha giudicato impossibile")

    def test_a_suspect_latest_pace_is_labelled_in_the_summary(self, connection):
        # Il caso vero della event01: più veloce del miglior 1500 in vasca,
        # ma non oltre il miglior 100. Il numero può restare visibile soltanto
        # se la cautela compare nello stesso riepilogo.
        _in_vasca(connection, "cento", date(2018, 3, 11), 100, 55.32)
        _in_vasca(connection, "millecinque", date(2026, 2, 15), 1500, 1139.55)
        _in_mare(connection, "event01", date(2026, 8, 23), 1535.01, 2500,
                 meet="event01")

        pagina = rh.as_page_dict(rh.history(connection, today=date(2026, 8, 24)))

        assert "1:01.40/100 m" in pagina["last"]
        assert "dato sospetto" in pagina["last"]

    def test_a_plausible_sea_race_keeps_its_pace(self, connection):
        _in_vasca(connection, "cento", date(2018, 3, 11), 100, 55.32)
        _in_vasca(connection, "millecinque", date(2026, 2, 15), 1500, 1139.55)
        _in_mare(connection, "mediterraneo", date(2025, 9, 14), 2819.0, 3000)

        gara = rh.open_water(connection)[0]

        assert gara.credibility == rh.CREDIBLE
        assert gara.pace_100_s == pytest.approx(93.97, abs=0.01)

    def test_without_a_pool_reference_no_judgement_is_given(self, connection):
        _in_mare(connection, "mare", date(2025, 6, 21), 855.0, 2000)

        gara = rh.open_water(connection)[0]

        assert gara.credibility == rh.UNVERIFIABLE, (
            "senza un metro non si giudica, e un metro assente non diventa "
            "un metro generico")
