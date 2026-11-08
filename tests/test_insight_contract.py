"""Il contratto di evidenza: nessun numero mostrabile viaggia da solo (D7).

Sono i test che devono fallire se qualcuno, un giorno, aggiunge un numero a una
risposta senza dire in che unità è, su quanti casi è calcolato e con quale
versione del metodo. È l'unica difesa automatica contro il ritorno del numero
nudo, che è il difetto che tutta la Macro-proposta 3 esisteva per togliere.
"""

from datetime import date, datetime

import pytest

from garmin_coach.analysis.insight import (NO_NUMBERS, Freshness, InsightPacket,
                                           Status, evidence, format_measure,
                                           missing_evidence)
from garmin_coach.metrics.evidence import Availability, Evidence

# I campi senza i quali un numero non è mostrabile.
REQUIRED = {"field", "label", "value", "unit", "display", "data_class",
            "availability", "evidence_grade", "source", "formula",
            "method_version"}


def test_a_known_metric_carries_its_whole_definition():
    entry = evidence("swim_km_7d", 19.6, n=7, expected_n=7)

    missing = REQUIRED - set(entry)
    assert not missing, f"campi mancanti nel contratto: {sorted(missing)}"
    assert entry["unit"] == "km"
    assert entry["display"] == "19.6 km"
    assert entry["origin"] == "computed"
    assert entry["coverage"] == 1.0


def test_a_metric_invented_for_one_question_says_so_instead_of_pretending():
    """Un valore calcolato al volo non ha una definizione nel catalogo.

    Va dichiarato, non nascosto: chi legge deve sapere che quella riga non ha
    una scheda a cui risalire.
    """
    entry = evidence("rapporto_inventato_qui", 1.74)

    assert entry["source"] == "calcolo di questa domanda"
    assert entry["label"] == "rapporto_inventato_qui"
    assert entry["method_version"] == "1"


@pytest.mark.parametrize("reason", [
    Availability.MISSING,
    Availability.NOT_APPLICABLE,
    Availability.INSUFFICIENT_DATA,
    Availability.INVALID,
    Availability.STALE,
])
def test_a_missing_number_is_never_a_zero_and_always_says_why(reason):
    entry = missing_evidence("hrv_ms", reason, "nota di contesto")

    assert entry["value"] is None, "un valore mancante non diventa mai zero"
    assert entry["availability"] == reason
    assert entry["why"], "l'assenza deve portare la propria spiegazione"
    assert entry["display"] == "—"
    assert entry["evidence_grade"] == Evidence.NONE


def test_the_five_reasons_for_absence_are_not_synonyms():
    """`missing` e `not_applicable` non descrivono la stessa cosa.

    Le vasche in acque libere non sono un dato mancante da recuperare: è il
    concetto che non si applica. Comprimerli produrrebbe una lista di difetti
    da correggere che non esistono.
    """
    reasons = {r: missing_evidence("hrv_ms", r)["why"]
               for r in (Availability.MISSING, Availability.NOT_APPLICABLE,
                         Availability.INSUFFICIENT_DATA, Availability.INVALID,
                         Availability.STALE)}
    assert len(set(reasons.values())) == 5, "due assenze diverse con la stessa frase"


class TestFormatMeasure:
    """La formattazione vive in Python perché nei template è vietata."""

    def test_seconds_become_hours_and_minutes(self):
        assert format_measure(29880.0, "secondi") == "8h 18m"

    def test_short_durations_stay_in_minutes(self):
        assert format_measure(95, "secondi") == "1:35"

    def test_a_garmin_scale_shows_the_number_alone(self):
        # «21 stress Garmin 0-100» non è una frase che qualcuno leggerebbe.
        assert format_measure(21, "stress Garmin 0-100") == "21"

    def test_a_real_unit_stays_attached(self):
        assert format_measure(19.6, "km") == "19.6 km"

    def test_absence_is_a_dash_not_a_zero(self):
        assert format_measure(None, "km") == "—"

    def test_booleans_are_words_not_numbers(self):
        assert format_measure(True, "vero/falso") == "sì"


class TestFreshness:
    def test_data_up_to_today_says_so_plainly(self):
        state = Freshness(date(2026, 8, 21), datetime(2026, 8, 21, 17, 0), 0)
        assert state.as_dict()["display"] == "aggiornato a oggi"
        assert not state.is_stale

    def test_old_data_says_the_real_date_not_the_word_today(self):
        state = Freshness(date(2026, 8, 15), datetime(2026, 8, 21, 17, 0), 6)
        rendered = state.as_dict()["display"]
        assert "15/08/2026" in rendered and "6 giorni fa" in rendered
        assert state.is_stale

    def test_an_empty_database_does_not_invent_a_date(self):
        state = Freshness(None, datetime(2026, 8, 21, 17, 0), None)
        assert state.as_dict()["data_through"] is None
        assert state.as_dict()["display"] == "nessun dato"


class TestInsightPacket:
    def test_interpretation_is_absent_and_not_empty_when_nobody_asked(self):
        """Un campo vuoto sembra un dato mancante; un campo assente è una cosa
        che non è stata fatta. L'app funziona offline, quindi è la normalità."""
        packet = InsightPacket(question="Come sto?", observation="Nella norma.")
        assert "interpretation" not in packet.as_dict()

    def test_counter_evidence_lives_in_its_own_place(self):
        packet = InsightPacket(question="Come sto?", observation="Nella norma.")
        packet.add(evidence("swim_km_7d", 19.6))
        packet.against(evidence("resting_hr_bpm", 55))

        rendered = packet.as_dict()
        assert len(rendered["evidence"]) == 1
        assert len(rendered["counter_evidence"]) == 1

    def test_the_status_is_readable_by_the_athlete_too(self):
        packet = InsightPacket(question="Come sto?", observation="…",
                               status=Status.INSUFFICIENT_DATA)
        assert packet.as_dict()["status_it"] == "dati insufficienti"

    def test_there_are_exactly_three_states(self):
        # Ogni stato in più è una sfumatura che l'atleta deve imparare.
        assert len(Status.ITALIANO) == 3


def test_the_two_tools_without_numbers_declare_why_they_have_no_evidence():
    """Rilievo A4 del secondo audit: applicare il contratto a `log_write` e a
    `athlete_context` produrrebbe campi vuoti che sembrano dati mancanti."""
    assert set(NO_NUMBERS) == {"athlete_context", "log_write"}
    for tool, reason in NO_NUMBERS.items():
        assert len(reason) > 40, f"{tool}: la spiegazione deve essere leggibile"
