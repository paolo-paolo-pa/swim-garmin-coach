"""Il confine fra ciò che si misura e ciò che si giudica.

Il contratto non prova che il giudizio sia giusto. Prova che è tracciabile: che
ogni cifra mostrata all'atleta viene da una funzione Python testata, e che si
può risalire da una frase ai fatti che l'hanno prodotta. È meno di quanto si
vorrebbe ed è tutto quello che si può garantire.

Questi test guardano soprattutto ciò che il contratto **rifiuta**. Un validatore
si giudica da cosa non lascia passare.
"""

from datetime import date

import duckdb
import pytest

from garmin_coach import coach, paths
from garmin_coach.coach.contract import (CoachingResponse, Fact,
                                         InvalidResponse, validate)
from garmin_coach.database import SCHEMA
from garmin_coach.metrics import daily_status

OGGI = date(2026, 8, 22)


@pytest.fixture
def coach_dir(tmp_path, monkeypatch):
    cartella = tmp_path / "coach"
    cartella.mkdir()
    (cartella / "gare.md").write_text(
        "# Gare\n\n"
        "| Data | Nome | Distanza | Ambiente | Vasca | Priorita | Obiettivo | Note |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 2026-10-03 | event02 place22 | 10 km | acque libere | - | A | "
        "passo 1:30/100 | place26 |\n", encoding="utf-8")
    for nome in ("atleta.md", "obiettivi.md", "correzioni-dati.md"):
        (cartella / nome).write_text("# vuoto\n", encoding="utf-8")
    monkeypatch.setattr(paths, "COACH", cartella)
    return cartella


@pytest.fixture
def connection(coach_dir):
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    con.execute("""
        INSERT INTO activities (activity_id, start_time_utc, start_time_local,
                                activity_date, sport, is_swim, environment,
                                distance_m, duration_s, pool_length_m,
                                garmin_training_load, device_id,
                                source_object_id, imported_at)
        SELECT i, (DATE '2026-08-22' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-22' - INTERVAL (i) DAY)::TIMESTAMP,
               (DATE '2026-08-22' - INTERVAL (i) DAY)::DATE,
               'lap_swimming', TRUE, 'pool', 3000, 3600, 25, 60, 1, 'sha',
               TIMESTAMP '2026-01-01'
        FROM range(1, 90) t(i) WHERE i % 2 = 0
    """)
    con.execute(
        "INSERT INTO daily_health (health_date, resting_hr_bpm, "
        " body_battery_min, source_object_id, imported_at) "
        "SELECT (DATE '2026-08-22' - INTERVAL (i) DAY)::DATE, 52, 28, 'sha', "
        " TIMESTAMP '2026-01-01' FROM range(0, 90) t(i)")
    daily_status.build(con)
    yield con
    con.close()


@pytest.fixture
def packet(connection):
    return coach.build(connection, "Su cosa mi concentro?", today=OGGI)


# ── Il pacchetto ─────────────────────────────────────────────────────────

class TestIlPacchettoPortaSoloCioCheServe:
    def test_it_knows_the_goal_and_how_far_away_it_is(self, packet):
        assert packet.goal["event_name"] == "event02 place22"
        assert packet.goal["days_to_event"] == 42

    def test_the_days_are_counted_from_the_observation_date(self, connection):
        """Non da ``date.today()``.

        È il difetto che l'audit ha trovato in ``races.py``: l'osservazione
        accettava una data e poi contava i giorni da oggi, quindi una lettura
        datata rispondeva con i giorni sbagliati.
        """
        dopo = coach.build(connection, "?", today=date(2026, 9, 3))
        assert dopo.goal["days_to_event"] == 30

    def test_no_gps_no_name_no_raw_ever_reaches_the_packet(self, packet):
        """Il pacchetto è ciò che uscirà dal computer.

        Va guardato con quell'occhio, non con quello di una struttura interna.
        """
        import json

        testo = json.dumps(packet.as_dict(), default=str).lower()
        for vietato in ("latitude", "longitude", "gps", "activity_id",
                        "source_object_id", "utente", "@"):
            assert vietato not in testo, f"nel pacchetto c'è «{vietato}»"

    def test_every_fact_declares_its_window(self, packet):
        """Senza finestra, «21,78 km» e «8,9 km» sembrano la stessa grandezza."""
        for fatto in packet.facts:
            assert fatto.window, f"«{fatto.fact_id}» non dice su che periodo è"

    def test_the_digest_changes_when_a_fact_changes(self, packet):
        prima = packet.digest
        packet.add(Fact("nuovo", "Nuovo", 1, "km", "1 km", "7 giorni"))
        assert packet.digest != prima

    def test_the_digest_changes_when_quality_or_limits_change(self, packet):
        prima = packet.digest
        packet.data_quality["review"] = 1
        dopo_qualita = packet.digest
        packet.limitations.append("Un nuovo limite dichiarato.")

        assert dopo_qualita != prima
        assert packet.digest != dopo_qualita

    def test_the_digest_is_stable_for_the_same_content(self, connection):
        uno = coach.build(connection, "Su cosa mi concentro?", today=OGGI)
        due = coach.build(connection, "Su cosa mi concentro?", today=OGGI)
        assert uno.digest == due.digest

    def test_the_goal_environment_is_the_one_used_for_specificity(
            self, connection, coach_dir):
        (coach_dir / "gare.md").write_text(
            "# Gare\n\n"
            "| Data | Nome | Distanza | Ambiente | Vasca | Priorita | Obiettivo | Note |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 2026-10-03 | Gara in vasca | 1500 m | piscina | 25 | A | finire | — |\n",
            encoding="utf-8")

        quadro = coach.build(connection, "Su cosa mi concentro?", today=OGGI)

        assert quadro.goal["environment_key"] == "pool"
        assert quadro.fact("pool_km_8w").value > 0
        assert quadro.fact("specific_share").value == 1

    def test_recovery_keeps_units_stress_and_zero_values(self, connection):
        connection.execute(
            "UPDATE daily_status SET sleep_total_s = 28800, stress_avg = 0, "
            "body_battery_min = 0 WHERE status_date = ?", [OGGI])

        quadro = coach.build(connection, "Su cosa mi concentro?", today=OGGI)

        assert quadro.fact("sleep_total_s").unit == "s"
        assert quadro.fact("sleep_total_s").display == "8.0 h"
        assert quadro.fact("stress_avg").display == "0"
        assert quadro.fact("body_battery_min").display == "0"
        assert quadro.recovery["signals_available"] == 4
        assert "su 5" in quadro.recovery["summary"]

    def test_the_age_belongs_to_the_endurance_reference_not_the_last_race(
            self, connection):
        connection.execute("""
            INSERT INTO races (race_id, race_date, meet, event_label, distance_m,
                stroke, is_relay, relay_legs, pool_length_m, time_s, status,
                timing, federation, category, meet_id, event_id,
                source_object_id, imported_at, environment, distance_source)
            VALUES
              ('fondo', DATE '2026-02-15', 'Meet', '1500 Stile Libero', 1500,
               'stile', FALSE, NULL, 25, 1139.55, 'valid', 'A', 'FIN', NULL,
               '1', '1', 'sha', TIMESTAMP '2026-01-01',
               'piscina', 'certified_pool'),
              ('recente', DATE '2026-06-02', 'Meet', '50 Stile Libero', 50,
               'stile', FALSE, NULL, 25, 26.0, 'valid', 'A', 'FIN', NULL,
               '2', '2', 'sha', TIMESTAMP '2026-01-01',
               'piscina', 'certified_pool')
        """)

        quadro = coach.build(connection, "Su cosa mi concentro?", today=OGGI)
        risposta = coach.LocalBrain().judge(quadro)

        assert quadro.fact("days_since_endurance_reference").value == 188
        assert quadro.fact("days_since_last_race").value == 81
        assert "188 giorni" in risposta.verdict
        assert "81 giorni" not in risposta.verdict


# ── Il validatore: si giudica da cosa non lascia passare ─────────────────

def _risposta_valida(packet) -> CoachingResponse:
    return CoachingResponse(
        verdict="Il lavoro c'è; la prova specifica no.",
        primary_focus="Verificare la tenuta del passo obiettivo.",
        confidence="moderate", why=["swim_km_7d"],
        packet_digest=packet.digest)


class TestQuelloCheIlContrattoRifiuta:
    def test_a_number_that_is_not_in_the_packet(self, packet):
        """Un numero plausibile e inventato è più pericoloso di un errore
        evidente, perché nessuno lo controlla."""
        risposta = _risposta_valida(packet)
        risposta.verdict = "Hai nuotato 47,3 km nelle ultime due settimane."

        with pytest.raises(InvalidResponse) as errore:
            validate(risposta, packet)
        assert "47,3" in str(errore.value)

    def test_an_evidence_id_that_does_not_exist(self, packet):
        risposta = _risposta_valida(packet)
        risposta.why = ["swim_km_7d", "vo2max_stimato"]

        with pytest.raises(InvalidResponse) as errore:
            validate(risposta, packet)
        assert "vo2max_stimato" in str(errore.value)

    def test_a_diagnosis(self, packet):
        risposta = _risposta_valida(packet)
        risposta.what_needs_attention = [
            "Il carico in salita e la spalla suggeriscono una tendinite."]

        with pytest.raises(InvalidResponse):
            validate(risposta, packet)

    def test_a_correlation_dressed_as_a_cause(self, packet):
        risposta = _risposta_valida(packet)
        risposta.verdict = "Il sonno corto è la causa di quel passo."

        with pytest.raises(InvalidResponse):
            validate(risposta, packet)

    def test_a_verdict_without_any_evidence(self, packet):
        risposta = _risposta_valida(packet)
        risposta.why = []

        with pytest.raises(InvalidResponse):
            validate(risposta, packet)

    def test_a_confidence_that_is_a_score(self, packet):
        """Un valore libero diventa un punteggio, e un punteggio suggerisce una
        precisione che non c'è."""
        risposta = _risposta_valida(packet)
        risposta.confidence = "78%"

        with pytest.raises(InvalidResponse):
            validate(risposta, packet)

    def test_a_response_with_no_focus(self, packet):
        risposta = _risposta_valida(packet)
        risposta.primary_focus = "  "

        with pytest.raises(InvalidResponse):
            validate(risposta, packet)

    def test_the_calendar_of_the_advice_is_not_an_invented_number(self, packet):
        """«nei prossimi 7 giorni» non è una misura: è il calendario del
        consiglio stesso, e vietarlo renderebbe impossibile dare un consiglio."""
        risposta = _risposta_valida(packet)
        risposta.actions_next_7_days = ["Nei prossimi 7 giorni, una prova."]

        validate(risposta, packet)

    def test_a_number_declared_in_a_limitation_is_not_invented(self, packet):
        packet.limitations.append("Il campione disponibile contiene 123 giorni.")
        risposta = _risposta_valida(packet)
        risposta.verdict = "Il limite riguarda un campione di 123 giorni."

        validate(risposta, packet)


# ── Il cervello locale ───────────────────────────────────────────────────

class TestIlCervelloLocale:
    def test_it_produces_a_valid_response_without_network(self, packet):
        risposta = coach.LocalBrain().judge(packet)

        validate(risposta, packet)
        assert risposta.verdict and risposta.primary_focus

    def test_it_says_it_is_local_instead_of_pretending(self, packet):
        assert "locale" in coach.LocalBrain().judge(packet).model

    def test_it_leaves_the_long_horizons_empty_rather_than_filling_them(
            self, packet):
        """Una frase generica in un campo che promette uno scenario a 42 giorni
        è peggio del campo vuoto: promette un ragionamento che non c'è."""
        assert coach.LocalBrain().judge(packet).scenario_next_42_days == []

    def test_it_names_the_drift_when_the_work_is_not_specific(self, packet):
        """Tutte le sedute del fixture sono in vasca e la gara è in mare."""
        assert coach.LocalBrain().judge(packet).focus_drift == "sì"

    def test_it_carries_the_packet_digest_so_staleness_is_visible(self, packet):
        assert coach.LocalBrain().judge(packet).packet_digest == packet.digest

    def test_it_always_ends_with_something_to_do(self, packet):
        assert coach.LocalBrain().judge(packet).next_check, (
            "una risposta che non finisce con un prossimo controllo è un "
            "riassunto, non un consiglio")
