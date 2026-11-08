"""Le gare che nessun archivio cronometra, dichiarate dall'atleta.

## L'errore da cui nasce

Il 23/08/2026 il coach ha scritto **«il tuo unico 10 km»**. L'atleta ne aveva
nuotati almeno tre — place23, place05 e place21 — e Icron ne espone uno
solo, perché le gare fuori dal proprio circuito non le cronometra.

Il conto era giusto e la frase era falsa: il coach aveva scambiato **quello che
l'archivio contiene** per **quello che l'atleta ha fatto**. È l'errore più
pericoloso di tutti, perché il numero regge e la conclusione no.

## Cosa difendono

1. Una gara dichiarata entra in archivio come le altre e conta nei conteggi.
2. **Non entra nei record di vasca**: `pool_races` vuole `certified_pool`, e
   una dichiarazione non lo è.
3. **Il tempo si scrive a mano, sempre.** Il collegamento alla seduta Garmin
   serve a confrontare le distanze, mai a riempire un tempo mancante: su
   place05 2019 l'orologio dice 6.975 m in 2h13' e il cronometro 10 km in
   3h00'46".
4. **Una gara senza tempo non è una gara non valida.** Tre stati e non due:
   `valid`, `time_unknown` quando il risultato ufficiale non si trova, `invalid`
   quando nella casella c'è scritto qualcosa di illeggibile.
5. Le nuotate lunghe in mare che non risultano gare vengono **segnalate**, mai
   promosse: una nuotata di dieci chilometri può essere una gara o una domenica.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach.analysis import race_history as rh
from garmin_coach.database import SCHEMA
from garmin_coach.ingest import declared_races as dr

INTESTAZIONE = (
    "| Data | Gara | Localita | Distanza | Tempo | Ambiente | Posizione | "
    "Seduta Garmin | Note |\n"
    "|---|---|---|---|---|---|---|---|---|\n")


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dr.paths, "COACH", tmp_path)
    return tmp_path


def _file(coach_dir, righe: list[str]) -> None:
    (coach_dir / "gare-dichiarate.md").write_text(
        "# Gare dichiarate\n\n" + INTESTAZIONE + "\n".join(righe) + "\n",
        encoding="utf-8")


def _nuotata(con, activity_id, giorno, metri, durata, nome=None):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, pool_length_m, name,
            source_object_id, imported_at)
        VALUES (?, ?, ?, 'open_water_swimming', true, ?, ?, NULL, ?, 'sha', ?)
    """, [activity_id, giorno,
          datetime(giorno.year, giorno.month, giorno.day, 8), durata, metri,
          nome, datetime(2026, 1, 1)])


class TestReadingTheFile:
    @pytest.mark.parametrize("testo, atteso", [
        ("3:00:46", 10846.0),
        ("2:31:00", 9060.0),
        ("44:25", 2665.0),
        ("22:51", 1371.0),
    ])
    def test_both_clock_formats_are_read(self, testo, atteso):
        assert dr.parse_time(testo) == pytest.approx(atteso)

    def test_a_short_race_written_without_hours_is_not_hours(self):
        # «22:51» sono ventidue minuti. Pretendere sempre le ore farebbe
        # scrivere quel numero a chi ha in mente 22'51", e diventerebbero
        # ventidue ore.
        assert dr.parse_time("22:51") == pytest.approx(1371.0)

    @pytest.mark.parametrize("testo, metri", [
        ("10 km", 10000), ("5000 m", 5000), ("1,5 km", 1500), ("2500", 2500),
    ])
    def test_distances_are_read(self, testo, metri):
        assert dr.parse_distance(testo) == metri

    def test_the_example_row_is_ignored(self, coach_dir):
        _file(coach_dir, [
            "| 2020-01-01 | Nome (esempio) | Citta | 10 km | 3:00:00 | "
            "acque libere | | | cancellala |"])

        assert dr.declared() == []

    def test_a_broken_row_does_not_sink_the_others(self, coach_dir):
        _file(coach_dir, [
            "| non una data | Rotta | place10 | 10 km | 3:00:00 | | | | |",
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | 40 | | |"])

        gare = dr.declared()

        assert len(gare) == 1 and gare[0].meet == "event02 place21"

    def test_the_environment_defaults_to_open_water(self, coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "| | | |"])

        assert dr.declared()[0].environment == "acque libere"


class TestWhatReachesTheArchive:
    def test_a_declared_race_becomes_a_race(self, connection, coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | 40 | | |"])

        esito = dr.load(connection)

        assert esito["races"] == 1
        riga = connection.execute(
            "SELECT meet, distance_m, time_s, environment, distance_source, "
            "       venue, overall_place FROM races").fetchone()
        assert riga == ("event02 place21", 10000, 9060.0, "acque libere",
                        "athlete_declared", "place21", 40)

    def test_it_never_enters_the_pool_records(self, connection, coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | Gara in vasca dichiarata | place10 | 400 m | 4:35 | "
            "vasca | | | |"])
        dr.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM pool_races").fetchone()[0] == 0, (
            "una dichiarazione non e' una vasca certificata: i record non la "
            "possono usare")

    def test_it_does_enter_the_open_water_reading(self, connection, coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | | | |"])
        dr.load(connection)

        gare = rh.open_water(connection)

        assert len(gare) == 1 and gare[0].distance_m == 10000

    def test_a_race_with_no_time_at_all_is_not_invalid(self, connection,
                                                       coach_dir):
        # Il caso vero: event02 place23 2017, trovata dall'orologio, tempo
        # ufficiale non ancora recuperato. La gara e' successa.
        _file(coach_dir, [
            "| 2017-10-15 | event02 place23 | place23 | 10 km |  | "
            "acque libere | | 10000000004 | |"])

        esito = dr.load(connection)

        assert esito["without_time"] == 1
        assert connection.execute(
            "SELECT status FROM races").fetchone()[0] == "time_unknown", (
            "«non conosco il tempo» e «il tempo e' sbagliato» sono due cose "
            "diverse, e comprimerle farebbe sparire una gara vera")

    def test_an_unreadable_time_is_invalid_and_counted_apart(self, connection,
                                                             coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | non lo "
            "ricordo | acque libere | | | |"])

        esito = dr.load(connection)

        assert esito["unreadable_time"] == 1 and esito["without_time"] == 0
        assert connection.execute(
            "SELECT status FROM races").fetchone()[0] == "invalid", (
            "qualcosa di illeggibile nella casella e' un errore da correggere, "
            "non un silenzio")

    def test_a_race_without_a_time_still_counts_as_a_race(self, connection,
                                                          coach_dir):
        _file(coach_dir, [
            "| 2017-10-15 | event02 place23 | place23 | 10 km |  | "
            "acque libere | | | |"])
        dr.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM races").fetchone()[0] == 1
        assert rh.open_water(connection) == [], (
            "senza tempo non c'e' un passo da leggere: la gara esiste in "
            "archivio e resta fuori dalle letture di prestazione")

    def test_importing_twice_changes_nothing(self, connection, coach_dir):
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | | | |"])

        dr.load(connection)
        dr.load(connection)

        assert connection.execute(
            "SELECT count(*) FROM races").fetchone()[0] == 1

    def test_the_watch_time_never_fills_a_missing_one(self, connection,
                                                      coach_dir):
        # Il caso vero: place23 2017, l'orologio ha misurato 10.003 m in
        # 2h39'47" e il collegamento c'e'. Il tempo resta comunque assente,
        # perche' l'orologio parte quando si preme — su place05 2019 dice
        # 6.975 m in 2h13' contro un cronometro che dice 3h00'46".
        _nuotata(connection, 10000000004, date(2017, 10, 15), 10003, 9587)
        _file(coach_dir, [
            "| 2017-10-15 | event02 place23 | place23 | 10 km |  | "
            "acque libere | | 10000000004 | |"])
        dr.load(connection)

        assert connection.execute("SELECT time_s FROM races").fetchone()[0] is None


class TestTheDetector:
    def test_a_long_sea_swim_without_a_race_is_flagged(self, connection):
        _nuotata(connection, 1, date(2024, 5, 26), 10152, 9060)

        segnalate = rh.long_swims_not_recorded_as_races(connection)

        assert len(segnalate) == 1
        assert "10.152 m" in segnalate[0]["display"]

    def test_a_swim_on_a_race_day_is_not_flagged(self, connection, coach_dir):
        _nuotata(connection, 1, date(2024, 5, 26), 10152, 9060)
        _file(coach_dir, [
            "| 2024-05-26 | event02 place21 | place21 | 10 km | 2:31:00 | "
            "acque libere | | 1 | |"])
        dr.load(connection)

        assert rh.long_swims_not_recorded_as_races(connection) == []

    def test_a_short_swim_is_never_flagged(self, connection):
        _nuotata(connection, 1, date(2024, 5, 26), 3000, 2700)

        assert rh.long_swims_not_recorded_as_races(connection) == [], (
            "chiedere «era una gara?» a ogni uscita da tre chilometri e' rumore")

    def test_it_promotes_nothing_by_itself(self, connection):
        _nuotata(connection, 1, date(2024, 5, 26), 10152, 9060)

        rh.long_swims_not_recorded_as_races(connection)

        assert connection.execute(
            "SELECT count(*) FROM races").fetchone()[0] == 0, (
            "una nuotata di dieci chilometri in mare puo' essere una gara o "
            "una domenica: la macchina segnala, la persona decide")

    def test_a_known_training_location_is_never_flagged(self, connection):
        # place01 aveva prodotto un falso candidato l'8.761 m del
        # 02/06/2018: l'atleta ha dichiarato il 23/08/2026 che li' si allena,
        # non gareggia, e la dichiarazione vale a prescindere dalla distanza.
        _nuotata(connection, 1, date(2018, 6, 2), 8761, 9865,
                 nome="place01 Nuoto in acque libere")

        assert rh.long_swims_not_recorded_as_races(connection) == []

    def test_the_match_on_location_is_case_insensitive(self, connection):
        _nuotata(connection, 1, date(2023, 8, 26), 6000, 5160,
                 nome="place02 Open Water Swimming")

        assert rh.long_swims_not_recorded_as_races(connection) == []

    def test_a_swim_elsewhere_is_still_flagged(self, connection):
        _nuotata(connection, 1, date(2018, 6, 29), 30598, 37024,
                 nome="place19 Nuoto in acque libere")

        assert len(rh.long_swims_not_recorded_as_races(connection)) == 1, (
            "l'esclusione riguarda due luoghi dichiarati, non ogni nuotata "
            "con un nome di localita'")

    def test_place03_is_a_training_location_not_flagged(self, connection):
        # Il rilevatore aveva prodotto quattro candidati a place03 (26/08/2023,
        # 28/07/2024, 03/08/2024, 04/08/2024, tutti 5-6 km). L'atleta ha
        # confermato il 24/08/2026 che e' zona di allenamento, come Torre
        # Canne e place02, e non gara.
        _nuotata(connection, 1, date(2023, 8, 26), 6000, 5160,
                 nome="place03 Open Water Swimming")

        assert rh.long_swims_not_recorded_as_races(connection) == []
