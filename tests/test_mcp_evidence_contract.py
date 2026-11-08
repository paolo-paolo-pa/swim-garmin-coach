"""Il contratto D7 sui sette strumenti: nessun numero mostrabile viaggia solo.

Questi test falliscono se qualcuno, un giorno, aggiunge un numero alla risposta
di uno strumento senza dire in che unità è, se c'è davvero, e con quale versione
del metodo è stato prodotto. È l'unica difesa automatica contro il ritorno del
numero nudo.

Il rilievo A4 del secondo audit ha corretto la richiesta originale: il contratto
si applica ai **numeri**, non alle risposte. `athlete_context` restituisce
markdown scritto dall'atleta e `log_write` un esito: per quei due l'elenco delle
evidenze è vuoto, e porta scritto il perché.
"""

from datetime import date, datetime, timedelta

import duckdb
import pytest

from garmin_coach.analysis.insight import NO_NUMBERS
from garmin_coach.database import SCHEMA
from garmin_coach.mcp import planning, queries
from garmin_coach.metrics import daily_status
from garmin_coach.metrics.evidence import Availability

# Senza questi campi un numero non è mostrabile.
OBBLIGATORI = {"field", "value", "unit", "display", "availability",
               "data_class", "evidence_grade", "method_version"}


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
                                activity_date, sport, is_swim, environment,
                                distance_m, duration_s, pool_length_m, avg_hr_bpm,
                                device_id, source_object_id, imported_at)
        SELECT i, (DATE '2026-08-20' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-20' - INTERVAL (i) DAY)::DATE,
               'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 140, 1, 'sha',
               TIMESTAMP '2026-01-01'
        FROM range(1, 200) t(i)
    """)
    con.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, source_object_id, "
        "imported_at) SELECT (DATE '2026-08-20' - INTERVAL (i) DAY)::DATE, 55, "
        "'sha', TIMESTAMP '2026-01-01' FROM range(1, 200) t(i)")
    daily_status.build(con)
    yield con
    con.close()


def controlla(voci: list[dict], dove: str) -> None:
    assert voci, f"{dove}: nessuna evidenza"
    for voce in voci:
        mancanti = OBBLIGATORI - set(voce)
        assert not mancanti, f"{dove} · {voce.get('field')}: manca {sorted(mancanti)}"
        assert voce["availability"] in vars(Availability).values(), (
            f"{dove}: stato di disponibilità sconosciuto")
        if voce["availability"] != Availability.AVAILABLE:
            assert voce.get("why") or voce.get("notes"), (
                f"{dove} · {voce['field']}: assente senza motivo")


class TestTheFiveToolsThatProduceNumbers:
    def test_briefing_covers_every_number_it_shows(self, connection):
        risposta = queries.briefing(connection)
        controlla(risposta["evidence"], "briefing")
        campi = {voce["field"] for voce in risposta["evidence"]}
        assert set(queries.BRIEFING_COLUMNS) <= campi, (
            "una colonna mostrata senza la propria evidenza")

    def test_swim_history_covers_the_totals(self, connection):
        risposta = queries.swim_history(connection, date(2026, 6, 1),
                                        date(2026, 8, 20))
        controlla(risposta["evidence"], "swim_history")

    def test_session_covers_its_derived_numbers(self, connection):
        risposta = queries.session(connection, 5)
        controlla(risposta["evidence"], "session")

    def test_compare_covers_the_comparisons_it_allows(self, connection):
        risposta = queries.compare(connection,
                                   (date(2026, 5, 1), date(2026, 6, 15)),
                                   (date(2026, 6, 16), date(2026, 8, 1)))
        controlla(risposta["evidence"], "compare")

    def test_race_readiness_covers_the_state_it_reports(self, connection):
        controlla(planning._evidence_of({"swim_km_7d": 20.0, "acwr": 1.2}),
                  "race_readiness")


class TestTheTwoToolsThatDoNot:
    @pytest.mark.parametrize("tool", ["athlete_context", "log_write"])
    def test_an_empty_list_always_carries_its_reason(self, tool):
        risposta = queries.no_numbers(tool)
        assert risposta["evidence"] == []
        assert risposta["evidence_note"] == NO_NUMBERS[tool]

    def test_the_reason_is_readable_by_a_person(self):
        for tool, motivo in NO_NUMBERS.items():
            assert len(motivo) > 40 and motivo.endswith("."), tool


class TestWhatTheContractRefusesToHide:
    def test_a_number_that_is_absent_never_becomes_a_zero(self, connection):
        """Regola Aurea n.5. È l'errore che rende una media falsa senza che
        niente sembri rotto."""
        risposta = queries.briefing(connection)
        assenti = [v for v in risposta["evidence"]
                   if v["availability"] != Availability.AVAILABLE]

        assert assenti, "il database di prova ha per forza dei buchi"
        for voce in assenti:
            assert voce["value"] is None
            assert voce["display"] == "—"

    def test_an_average_on_half_the_sessions_is_not_shown_as_the_average(self, connection):
        """La frequenza cardiaca non esiste prima del 2021: una media sul
        sottoinsieme che ce l'ha descrive quel sottoinsieme, non il periodo."""
        connection.execute(
            "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
            "sport, is_swim, environment, distance_m, duration_s, pool_length_m, "
            "device_id, source_object_id, imported_at) VALUES (9001, ?, ?, "
            "'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 1, 'sha', ?)",
            [datetime(2026, 8, 19, 20), date(2026, 8, 19), datetime(2026, 1, 1)])

        risposta = queries.swim_history(connection, date(2026, 8, 1),
                                        date(2026, 8, 20))
        fc = [v for v in risposta["evidence"] if v["field"] == "avg_hr_bpm"][0]

        assert fc["availability"] == Availability.INSUFFICIENT_DATA
        assert fc["value"] is None

    def test_provenance_and_evidence_answer_two_different_questions(self, connection):
        """`provenance` dice cos'è la metrica e non cambia mai; `evidence` dice
        quanto vale adesso e se ci si può contare."""
        risposta = queries.briefing(connection)

        definizione = risposta["provenance"][0]
        misura = risposta["evidence"][0]

        assert "formula" in definizione and "value" not in definizione
        assert "value" in misura and "availability" in misura

    def test_the_seven_tools_keep_their_names(self):
        from garmin_coach.mcp import server
        for nome in ("briefing", "swim_history", "session", "compare",
                     "race_readiness", "athlete_context", "log_write"):
            assert hasattr(server, nome), f"lo strumento {nome} è sparito"


class TestThereIsOnlyOneDefinitionOfVolume:
    """Regola Aurea n.8: una sola verita, piu modi per leggerla.

    Non e un test teorico. Prima dell'unificazione le due definizioni davano
    gia risposte diverse per la stessa settimana - 1,33 km contro 1,32 - perche
    una arrotondava in SQL e l'altra in Python. Dieci metri, due verita.
    """

    def test_the_period_volume_agrees_between_mcp_and_the_analysis_layer(self, connection):
        from garmin_coach.analysis import volume

        dallo_strumento = queries._period_stats(
            connection, date(2026, 5, 1), date(2026, 8, 20), None, None)
        dal_servizio = volume.of_period(
            connection, date(2026, 5, 1), date(2026, 8, 20))

        assert dallo_strumento["distance_km"] == dal_servizio.distance_km
        assert dallo_strumento["km_per_week"] == dal_servizio.km_per_week
        assert dallo_strumento["sessions"] == dal_servizio.sessions

    def test_the_weekly_volume_agrees_too(self, connection):
        from garmin_coach.analysis import volume

        dallo_strumento = planning.weekly_volume(connection, date(2026, 8, 20),
                                                 weeks=8)
        dal_servizio = volume.weeks_until(connection, date(2026, 8, 20), weeks=8)

        assert [s["km"] for s in dallo_strumento] == [s.km for s in dal_servizio]

    def test_neither_module_still_aggregates_volume_over_the_activities_table(self):
        """Il divieto è mirato: sommare i metri **delle attività di un periodo**.

        Sommare i metri per stile dentro una seduta è un'altra domanda, si fa su
        `activity_laps`, e resta lecita dove serve.
        """
        import pathlib
        import re

        for modulo in (queries, planning):
            percorso = pathlib.Path(modulo.__file__)
            testo = percorso.read_text(encoding="utf-8")
            aggregazioni = re.findall(
                r"SELECT[^;]*?sum\(distance_m\)[^;]*?FROM\s+activities",
                testo, re.S | re.I)
            assert not aggregazioni, (
                f"{percorso.name} somma di nuovo il volume di un periodo: "
                "è la seconda verità che torna")
