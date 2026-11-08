"""Previsto contro eseguito: la metà che all'archivio mancava.

## Perché A6 era PARTIAL

Il ciclo previsto → eseguito → risposta era fermo a due terzi. L'eseguito lo
registra l'orologio, la risposta la misurano i tre assi di `adaptation.py`, e il
previsto non esisteva: **nessun dato al mondo contiene l'intenzione di chi
scrive l'allenamento.** Non era un limite tecnico, ed è per questo che non si
poteva risolvere scrivendo codice.

Adesso c'è un posto dove l'atleta la scrive, e questi test difendono i confini
di ciò che se ne può ricavare.

## Cosa difendono

1. **Senza programma, la risposta è «non lo so» con il motivo giusto**, che non
   è «dati insufficienti».
2. **L'accoppiamento è per giorno**, mai per somiglianza di volume: decidere
   che la seduta di mercoledì «era» quella prevista martedì è una decisione che
   dentro un programma diventa invisibile.
3. **Una riga scritta male viene saltata, non fa cadere le altre.**
4. **Un intento non riconosciuto diventa «non dichiarato»**, che è una risposta
   onesta, e non l'etichetta ammessa più somigliante.
5. **Il confronto non tocca l'intensità.** Dire se la soglia era soglia
   richiederebbe zone cardiache affidabili, e non lo sono.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import athlete_files
from garmin_coach.analysis import planned_vs_done as pvd
from garmin_coach.database import SCHEMA

OGGI = date(2026, 8, 23)


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(athlete_files.paths, "COACH", tmp_path)
    return tmp_path


def _programma(coach_dir, righe: list[str]) -> None:
    intestazione = ("| Data | Cosa | Intento | Serie | Note |\n"
                    "|---|---|---|---|---|\n")
    (coach_dir / "programma-settimanale.md").write_text(
        "# Programma\n\n" + intestazione + "\n".join(righe) + "\n",
        encoding="utf-8")


def _nuotata(con, activity_id, giorno, metri):
    con.execute("""
        INSERT INTO activities (activity_id, activity_date, start_time_utc,
            sport, is_swim, duration_s, distance_m, source_object_id,
            imported_at)
        VALUES (?, ?, ?, 'lap_swimming', true, 3600, ?, 'sha', ?)
    """, [activity_id, giorno,
          datetime(giorno.year, giorno.month, giorno.day, 7), metri,
          datetime(2026, 1, 1)])


class TestWithoutAProgramme:
    def test_it_says_why_and_where(self, connection, coach_dir):
        quadro = pvd.summary(connection, today=OGGI)

        assert quadro["available"] is False
        assert "programma-settimanale.md" in quadro["why"]
        assert "non per un limite dei dati" in quadro["why"], (
            "il previsto manca perché nessuno l'ha scritto, non perché "
            "l'archivio sia incompleto: sono due messaggi diversi")


class TestReadingTheProgramme:
    def test_kilometres_and_metres_both_read(self, connection, coach_dir):
        _programma(coach_dir, [
            "| 2026-08-20 | 3 km | aerobico | | |",
            "| 2026-08-21 | 3500 m | soglia | | |",
        ])

        previste = athlete_files.planned_sessions(today=OGGI)

        assert [una.distance_m for una in previste] == [3000, 3500]

    def test_an_unknown_purpose_becomes_not_declared(self, connection, coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | fartlek marino | | |"])

        assert athlete_files.planned_sessions(today=OGGI)[0].purpose \
            == "non dichiarato", (
            "un elenco chiuso di intenti serve a non far scegliere "
            "l'etichetta più vicina invece di quella giusta")

    def test_a_broken_row_does_not_sink_the_others(self, connection, coach_dir):
        _programma(coach_dir, [
            "| non una data | 3000 m | aerobico | | |",
            "| 2026-08-21 | 3500 m | soglia | | |",
        ])

        assert len(athlete_files.planned_sessions(today=OGGI)) == 1

    def test_the_example_row_is_ignored(self, connection, coach_dir):
        _programma(coach_dir, [
            "| 2026-08-20 | 3000 m (esempio) | aerobico | | da cancellare |",
        ])

        assert athlete_files.planned_sessions(today=OGGI) == []


class TestComparing:
    def test_a_session_swum_as_planned(self, connection, coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | aerobico | | |"])
        _nuotata(connection, 1, date(2026, 8, 20), 3100)

        confronto = pvd.compare(connection, today=OGGI)[0]

        assert confronto.status == "come prevista"
        assert confronto.delta_m == 100

    def test_a_session_not_swum(self, connection, coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | soglia | | |"])

        confronto = pvd.compare(connection, today=OGGI)[0]

        assert confronto.status == "non svolta"
        assert confronto.done_m is None

    def test_a_much_shorter_session_is_not_a_shorter_session(self, connection,
                                                             coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 4000 m | aerobico | | |"])
        _nuotata(connection, 1, date(2026, 8, 20), 1200)

        assert pvd.compare(connection, today=OGGI)[0].status == "molto ridotta", (
            "un terzo del previsto non è la stessa seduta più corta")

    def test_the_pairing_is_by_day_and_not_by_resemblance(self, connection,
                                                          coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | aerobico | | |"])
        _nuotata(connection, 1, date(2026, 8, 21), 3000)

        assert pvd.compare(connection, today=OGGI)[0].status == "non svolta", (
            "la seduta del 21 non «era» quella prevista per il 20: decidere di "
            "sì dentro un programma è una scelta che nessuno vede più")

    def test_the_longest_swim_of_the_day_is_the_one_that_counts(self, connection,
                                                                coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | aerobico | | |"])
        _nuotata(connection, 1, date(2026, 8, 20), 800)
        _nuotata(connection, 2, date(2026, 8, 20), 3000)

        assert pvd.compare(connection, today=OGGI)[0].status == "come prevista"

    def test_todays_session_is_not_yet_a_missed_session(self, connection,
                                                       coach_dir):
        _programma(coach_dir, [f"| {OGGI.isoformat()} | 3000 m | soglia | | |"])

        confronto = pvd.compare(connection, today=OGGI)[0]

        assert confronto.status == "ancora da fare", (
            "l'atleta si allena la sera: alle 15 la seduta di stasera non è "
            "saltata, e dirgli che lo è è una dichiarazione che i dati non "
            "sostengono")
        assert "giorno non è finito" in confronto.display

    def test_todays_session_once_swum_is_compared_normally(self, connection,
                                                           coach_dir):
        _programma(coach_dir, [f"| {OGGI.isoformat()} | 3000 m | soglia | | |"])
        _nuotata(connection, 1, OGGI, 3050)

        assert pvd.compare(connection, today=OGGI)[0].status == "come prevista", (
            "il giorno in corso sospende il verdetto solo finché manca la "
            "nuotata: appena c'è, si confronta come tutte le altre")

    def test_todays_session_does_not_count_as_missed_in_the_summary(
            self, connection, coach_dir):
        _programma(coach_dir, [
            "| 2026-08-20 | 3000 m | aerobico | | |",
            f"| {OGGI.isoformat()} | 3000 m | soglia | | |",
        ])
        _nuotata(connection, 1, date(2026, 8, 20), 3000)

        quadro = pvd.summary(connection, today=OGGI)

        assert "1 sedute su 1 previste" in quadro["headline"], (
            "«1 su 2» leggerebbe come una seduta mancata da chi non ha ancora "
            "mancato niente")
        assert len(quadro["sessions"]) == 2, (
            "fuori dal conteggio, non fuori dalla pagina: la seduta di stasera "
            "all'atleta serve vederla")

    def test_todays_session_once_swum_counts_in_the_summary(self, connection,
                                                            coach_dir):
        _programma(coach_dir, [
            "| 2026-08-20 | 3000 m | aerobico | | |",
            f"| {OGGI.isoformat()} | 3000 m | soglia | | |",
        ])
        _nuotata(connection, 1, date(2026, 8, 20), 3000)
        _nuotata(connection, 2, OGGI, 3100)

        quadro = pvd.summary(connection, today=OGGI)

        assert "2 sedute su 2 previste" in quadro["headline"], (
            "il giorno in corso esce dal conteggio solo finché la nuotata "
            "manca: quando il sync la porta la sera stessa, i suoi metri "
            "devono tornare nel totale della settimana")
        assert "6.100 m" in quadro["headline"]

    def test_a_future_session_is_not_compared(self, connection, coach_dir):
        _programma(coach_dir, ["| 2026-08-30 | 3000 m | aerobico | | |"])

        assert pvd.compare(connection, today=OGGI) == [], (
            "una seduta prevista per la settimana prossima non è «non svolta»")


class TestGivingTheSessionItsPurpose:
    def test_a_real_session_inherits_the_declared_purpose(self, connection,
                                                          coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | soglia | | |"])
        _nuotata(connection, 42, date(2026, 8, 20), 3000)

        assert pvd.purpose_of(connection, 42) == "soglia", (
            "«com'è andata martedì» diventa «com'è andata la soglia di "
            "martedì», e non serve nessuna inferenza")

    def test_without_a_declared_purpose_there_is_none(self, connection,
                                                      coach_dir):
        _nuotata(connection, 42, date(2026, 8, 20), 3000)

        assert pvd.purpose_of(connection, 42) is None


class TestWhatItRefusesToSay:
    def test_the_caveat_about_intensity_is_always_there(self, connection,
                                                        coach_dir):
        _programma(coach_dir, ["| 2026-08-20 | 3000 m | soglia | | |"])
        _nuotata(connection, 1, date(2026, 8, 20), 3000)

        quadro = pvd.summary(connection, today=OGGI)

        assert "Non** riguarda l'intensità" in quadro["caveat"], (
            "dire se la soglia era soglia richiederebbe zone cardiache "
            "affidabili, e non lo sono")
