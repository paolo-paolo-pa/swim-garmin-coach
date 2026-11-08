"""I tempi veri: quelli della piastra, non quelli dell'orologio.

## Cosa cambia con questo archivio

`races.py` dichiarava bloccate tre cose — velocità critica, intervalli di passo,
qualunque previsione — perché non esisteva **nessun** tempo prestativo. Ora ce ne
sono 114, cronometrati dalla federazione fra il 2014 e il 2026.

## Cosa questi test difendono

1. **Le staffette non diventano tempi personali.** Otto risultati su 114 sono di
   una squadra di quattro. Attribuirli a una persona sarebbe l'errore più facile
   e il più difficile da vedere dopo, perché il numero sembrerebbe suo.
2. **Una squalifica non è un tempo lento.** Resta senza tempo.
3. **Vasca da 25 e da 50 restano separate.** Su un 400 le virate in più valgono
   secondi: unirle farebbe di un record una media di due cose diverse.
4. **I doppioni della sorgente non contano due volte.** Il file ripete due righe
   identiche — stesso `event_id`, stesso tempo — e sono un artefatto della
   raccolta.
5. **I misti non entrano nella distribuzione di gara.** In un 200 misti le
   quattro frazioni sono quattro stili e la rana è sempre la più lenta: il
   confronto fra le due metà misura l'ordine delle bracciate, non il ritmo. Con
   i misti dentro, il 200 del 15/02/2026 usciva «in calando del 26%».
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import paths
from garmin_coach.analysis import race_history as rh
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import aquatime


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _gara(con, race_id, giorno, etichetta, distanza, stile, vasca, tempo,
          *, staffetta=False, legs=None, stato="valid", timing="A",
          ambiente="piscina", origine_distanza="certified_pool"):
    """Una gara in archivio. Di default in vasca, perché lo erano tutte fino
    alla migrazione 0009: le gare in mare si costruiscono con `_gara_in_mare`."""
    con.execute("""
        INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
            stroke, is_relay, relay_legs, pool_length_m, time_s, status, timing,
            federation, category, meet_id, event_id, source_object_id,
            imported_at, environment, distance_source)
        VALUES (?, ?, 'Meet', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FIN', 'ASSOLUTI',
                '1', '1', 'sha', ?, ?, ?)
    """, [race_id, giorno, etichetta, distanza, stile, staffetta, legs, vasca,
          tempo, stato, timing, datetime(2026, 1, 1), ambiente,
          origine_distanza])


def _passaggio(con, race_id, metri, parziale):
    con.execute("""
        INSERT INTO race_splits (race_id, split_m, cumulative_s, split_s,
            leg_s, source_object_id, imported_at)
        VALUES (?, ?, NULL, ?, NULL, 'sha', ?)
    """, [race_id, metri, parziale, datetime(2026, 1, 1)])


# ── 1. Il lettore della sorgente ─────────────────────────────────────────

class TestReadingTheFederationFile:
    def test_a_time_becomes_seconds(self):
        assert aquatime.parse_time("01'00''21") == pytest.approx(60.21)
        assert aquatime.parse_time("00'25''97") == pytest.approx(25.97)

    def test_a_disqualification_is_not_a_time(self):
        assert aquatime.parse_time("Squalificato") is None

    def test_a_relay_declares_its_leg_and_not_the_total(self):
        gara = aquatime.parse_event("4x100 Stile Libero")

        assert gara.is_relay and gara.relay_legs == 4
        assert gara.distance_m == 100, (
            "la distanza registrata è il totale della staffetta: il confronto "
            "userebbe 400 m come se li avesse nuotati lui")

    def test_an_individual_event_is_read_whole(self):
        gara = aquatime.parse_event("1500 Stile Libero")

        assert not gara.is_relay
        assert (gara.distance_m, gara.stroke) == (1500, "stile")

    def test_split_clocks_in_both_shapes(self):
        assert aquatime.parse_clock("33.77") == pytest.approx(33.77)
        assert aquatime.parse_clock("1:08.46") == pytest.approx(68.46)
        assert aquatime.parse_clock("(34.69)") == pytest.approx(34.69)
        assert aquatime.parse_clock("") is None

    def test_the_same_race_always_gets_the_same_identifier(self):
        """La sorgente ripete due righe identiche: devono restare una gara."""
        primo = aquatime.race_id(date(2015, 11, 8), "221745", "100 Stile Libero")
        secondo = aquatime.race_id(date(2015, 11, 8), "221745", "100 Stile Libero")

        assert primo == secondo

    def test_a_pace_rolls_over_to_the_next_minute(self):
        assert rh._show_pace(59.999) == "1:00.00/100 m"


def _aquatime_file(tmp_path, monkeypatch, rows: list[str]):
    coach_dir = tmp_path / "coach"
    cartella = coach_dir / "aquatime" / "atleta"
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / "atleta_gare_complete.csv"
    intestazione = (
        "data,gara,tipo,tempo,vasca,crono,federazione,categoria,meet_id,event_id\n")
    percorso.write_text(intestazione + "\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", coach_dir)
    return percorso


class TestAquatimeImportEndToEnd:
    def test_rewriting_a_source_replaces_rows_owned_by_the_old_hash(
            self, connection, tmp_path, monkeypatch):
        sorgente = _aquatime_file(tmp_path, monkeypatch, [
            "01/05/2024,Meet,100 Stile Libero,01'00''21,25,A,FIN,ASSOLUTI,1,11",
            "02/05/2024,Meet,200 Stile Libero,02'10''00,25,A,FIN,ASSOLUTI,1,12",
        ])
        aquatime.load(connection)
        assert connection.execute("SELECT count(*) FROM races").fetchone()[0] == 2

        sorgente.write_text(
            "data,gara,tipo,tempo,vasca,crono,federazione,categoria,meet_id,event_id\n"
            "01/05/2024,Meet,100 Stile Libero,01'00''21,25,A,FIN,ASSOLUTI,1,11\n",
            encoding="utf-8")
        esito = aquatime.load(connection)

        assert esito["races"] == 1
        assert connection.execute("SELECT count(*) FROM races").fetchone()[0] == 1

    def test_removing_all_source_files_removes_only_aquatime_owned_rows(
            self, connection, tmp_path, monkeypatch):
        sorgente = _aquatime_file(tmp_path, monkeypatch, [
            "01/05/2024,Meet,100 Stile Libero,01'00''21,25,A,FIN,ASSOLUTI,1,11",
        ])
        aquatime.load(connection)
        _gara(connection, "altra-fonte", date(2024, 6, 1),
              "50 Stile Libero", 50, "stile", 25, 26.0)

        sorgente.unlink()
        aquatime.load(connection)

        rimaste = connection.execute(
            "SELECT race_id FROM races ORDER BY race_id").fetchall()
        assert rimaste == [("altra-fonte",)]

    def test_an_unknown_time_is_not_called_a_disqualification(
            self, connection, tmp_path, monkeypatch):
        _aquatime_file(tmp_path, monkeypatch, [
            "01/05/2024,Meet,100 Stile Libero,tempo rotto,25,A,FIN,ASSOLUTI,1,11",
        ])

        esito = aquatime.load(connection)
        stato = connection.execute("SELECT status FROM races").fetchone()[0]
        quadro = rh.history(connection)

        assert stato == "invalid"
        assert esito["disqualified"] == 0
        assert esito["skipped"]
        assert "0 squalifiche" in quadro.coverage
        assert any("non riconosciuto" in limite for limite in quadro.limitations)


# ── 2. Che cosa è una prestazione personale, e cosa no ───────────────────

class TestWhatCountsAsAPersonalTime:
    def test_an_open_water_race_never_becomes_a_pool_best(self, connection):
        connection.execute("""
            INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
                stroke, is_relay, pool_length_m, time_s, status,
                source_object_id, imported_at, environment, distance_source)
            VALUES ('mare', DATE '2024-05-01', 'Mare', '400 Stile', 400,
                'stile', FALSE, NULL, 200, 'valid', 'sha', ?,
                'acque libere', 'event_field')
        """, [datetime(2026, 1, 1)])

        assert rh.bests(connection) == []

    def test_a_relay_never_becomes_a_personal_best(self, connection):
        _gara(connection, "r1", date(2024, 5, 1), "4x50 Stile Libero", 50,
              "stile", 25, 100.0, staffetta=True, legs=4)
        _gara(connection, "r2", date(2024, 5, 2), "50 Stile Libero", 50,
              "stile", 25, 27.5)

        record = rh.bests(connection)

        assert [uno.time_s for uno in record] == [27.5], (
            "il tempo di quattro persone è diventato il record di una")

    def test_a_disqualification_is_not_a_slow_time(self, connection):
        _gara(connection, "r1", date(2024, 5, 1), "200 Stile Libero", 200,
              "stile", 25, None, stato="disqualified")
        _gara(connection, "r2", date(2024, 5, 2), "200 Stile Libero", 200,
              "stile", 25, 128.0)

        assert [uno.time_s for uno in rh.bests(connection)] == [128.0]

    def test_the_two_pools_stay_separate(self, connection):
        _gara(connection, "r1", date(2024, 5, 1), "400 Stile Libero", 400,
              "stile", 25, 273.0)
        _gara(connection, "r2", date(2024, 5, 2), "400 Stile Libero", 400,
              "stile", 50, 280.0)

        record = rh.bests(connection)

        assert len(record) == 2, "le due vasche sono state confuse in un record solo"
        assert {uno.pool_length_m for uno in record} == {25, 50}

    def test_the_endurance_reference_is_the_longest_freestyle(self, connection):
        _gara(connection, "r1", date(2024, 5, 1), "50 Stile Libero", 50,
              "stile", 25, 26.0)
        _gara(connection, "r2", date(2024, 5, 2), "1500 Stile Libero", 1500,
              "stile", 25, 1139.55)
        _gara(connection, "r3", date(2024, 5, 3), "400 Stile Libero", 400,
              "stile", 25, 273.74)

        riferimento = rh.endurance_reference(connection)

        assert riferimento.distance_m == 1500


# ── 3. La distribuzione della gara ───────────────────────────────────────

class TestHowTheRaceWasDistributed:
    def _quattrocento(self, con, race_id, parziali, stile="stile"):
        _gara(con, race_id, date(2026, 6, 2), "400", 400, stile, 25,
              sum(parziali))
        for numero, parziale in enumerate(parziali, start=1):
            _passaggio(con, race_id, numero * 50, parziale)

    def test_an_evenly_swum_race_is_not_called_a_fade(self, connection):
        """Il 1500 del 15/02/2026 è la prova che ha spostato la soglia.

        Trenta parziali fra 35,99 e 39,62, chiuso accelerando: con la soglia
        all'1% usciva «in calando», e una gara nuotata bene descritta come una
        gara nuotata male insegna a non leggere il verdetto.
        """
        self._quattrocento(connection, "r1",
                           [32.0, 34.0, 34.2, 34.1, 34.3, 34.4, 34.3, 33.8])

        distribuzione = rh.pacing(connection)[0]

        assert distribuzione.verdict == "regolare", distribuzione.drift_pct

    def test_a_race_that_falls_apart_says_so(self, connection):
        self._quattrocento(connection, "r1",
                           [30.0, 33.0, 34.0, 35.0, 37.0, 38.0, 39.0, 40.0])

        distribuzione = rh.pacing(connection)[0]

        assert distribuzione.verdict == "in calando"
        assert distribuzione.drift_pct > 0

    def test_the_dive_and_the_finish_stay_out_of_the_comparison(self, connection):
        """Il primo tratto ha il tuffo e l'ultimo la volata: non sono ritmo."""
        self._quattrocento(connection, "r1",
                           [25.0, 34.0, 34.0, 34.0, 34.0, 34.0, 34.0, 25.0])

        distribuzione = rh.pacing(connection)[0]

        assert distribuzione.verdict == "regolare", (
            "il tuffo e la volata sono finiti dentro il confronto fra le metà")

    def test_a_medley_is_never_read_as_pacing(self, connection):
        """La rana è sempre la più lenta: misurerebbe gli stili, non il ritmo."""
        self._quattrocento(connection, "r1",
                           [32.0, 40.0, 50.0, 36.0, 32.0, 40.0, 50.0, 36.0],
                           stile="misti")

        assert rh.pacing(connection) == []


# ── 4. Il quadro completo, e cosa dichiara ───────────────────────────────

class TestTheWholePicture:
    def test_it_says_how_many_results_are_not_personal(self, connection):
        _gara(connection, "r1", date(2024, 5, 1), "4x50 Stile Libero", 50,
              "stile", 25, 100.0, staffetta=True, legs=4)
        _gara(connection, "r2", date(2024, 5, 2), "200 Stile Libero", 200,
              "stile", 25, None, stato="disqualified")
        _gara(connection, "r3", date(2024, 5, 3), "50 Stile Libero", 50,
              "stile", 25, 26.0)

        quadro = rh.history(connection, today=date(2024, 6, 1))

        assert "1 sono staffette" in quadro.coverage
        assert "1 squalifiche" in quadro.coverage

    def test_manual_timing_is_declared_and_not_dropped(self, connection):
        _gara(connection, "r1", date(2024, 5, 3), "50 Stile Libero", 50,
              "stile", 25, 26.0, timing="M")

        quadro = rh.history(connection, today=date(2024, 6, 1))

        assert any("manuale" in riga for riga in quadro.limitations)
        assert quadro.bests, "un tempo a cronometraggio manuale è stato buttato"

    def test_a_time_is_written_the_way_a_swimmer_reads_it(self):
        assert rh._show_time(68.46) == "1'08\"46"
        assert rh._show_time(25.97) == '25"97'
        assert rh._show_time(1139.55) == "18'59\"55"

    def test_without_the_archive_it_says_so_instead_of_showing_nothing(self):
        vuoto = duckdb.connect(":memory:")
        try:
            quadro = rh.history(vuoto)
            assert not quadro.bests
            assert any("importato" in riga for riga in quadro.limitations)
        finally:
            vuoto.close()
