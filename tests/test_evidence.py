"""Il contratto delle metriche (D7).

Un numero da solo non è un'informazione sufficiente per decidere. Questi test
verificano che ciò che lo accompagna sia onesto: che «non lo so» resti «non lo
so» invece di diventare zero, che un dato completo su tre casi non venga
spacciato per solido, e che un concetto inapplicabile non finisca fra le lacune.
"""

from datetime import date

import pytest

from garmin_coach.metrics import catalog
from garmin_coach.metrics.evidence import (
    Availability, Evidence, MetricValue, grade, missing, not_applicable)


def test_a_value_carries_unit_class_and_availability():
    value = MetricValue(38.0, "millisecondi", "garmin_proprietary",
                        method_id="hrv_notturna")
    answer = value.as_dict()

    assert answer["value"] == 38.0
    assert answer["unit"] == "millisecondi"
    assert answer["data_class"] == "garmin_proprietary"
    assert answer["availability"] == "available"


def test_a_missing_value_says_why_and_is_never_zero():
    """Regola Aurea n.5. Uno zero al posto di un vuoto si media con gli altri
    numeri e sposta ogni conclusione che lo attraversa."""
    value = missing(Availability.MISSING, unit="bpm")
    answer = value.as_dict()

    assert answer["value"] is None
    assert answer["value"] != 0
    assert answer["why"] == "la sorgente non lo contiene"


def test_not_applicable_is_not_the_same_as_missing():
    """Le vasche in mare non sono un dato mancante: non c'è niente da
    recuperare e nessun difetto da correggere."""
    vasche = not_applicable("in acque libere le vasche non esistono")
    answer = vasche.as_dict()

    assert answer["availability"] == "not_applicable"
    assert answer["availability"] != Availability.MISSING
    assert "non esistono" in answer["notes"][0]


def test_insufficient_data_is_distinct_from_absent_data():
    """«Ci sono ma non bastano» è una risposta diversa da «non ci sono», e
    porta a una decisione diversa: aspettare invece che cercare altrove."""
    value = missing(Availability.INSUFFICIENT_DATA, n=2, expected_n=14)
    answer = value.as_dict()

    assert answer["why"] == "i dati non bastano per calcolarlo"
    assert answer["n"] == 2
    assert answer["expected_n"] == 14


def test_a_stale_value_is_flagged_even_though_it_exists():
    value = missing(Availability.STALE, data_through=date(2026, 6, 1))
    assert value.as_dict()["why"].startswith("esiste ma è troppo vecchio")


# ── Grado di evidenza ──────────────────────────────────────────────────────

def test_two_cases_are_never_enough():
    assert grade(2) == Evidence.NONE
    assert grade(1, 1) == Evidence.NONE, "copertura piena su un caso resta un caso"


def test_many_cases_with_full_coverage_are_solid():
    assert grade(40, 45) == Evidence.STRONG


def test_many_cases_with_poor_coverage_are_not_solid():
    """Quaranta casi su duecento non descrivono l'atleta: descrivono i quaranta
    per cui il dato c'era, che potrebbero non essere un campione qualunque."""
    assert grade(40, 200) == Evidence.WEAK


def test_a_handful_of_cases_is_moderate_at_best():
    assert grade(10, 12) == Evidence.MODERATE


def test_evidence_is_none_when_the_value_is_not_available():
    value = missing(Availability.MISSING, n=50, expected_n=50)
    assert value.evidence_grade == Evidence.NONE, (
        "un valore assente non può avere evidenza solida, per quanti casi ci siano")


def test_coverage_is_computed_not_declared():
    value = MetricValue(1.0, n=30, expected_n=40)
    assert value.coverage == pytest.approx(0.75)
    assert value.as_dict()["coverage"] == 0.75


def test_a_single_measurement_has_no_sample_to_speak_of():
    """Una misura singola non è né solida né debole: non è una media."""
    assert MetricValue(52.0, "bpm").evidence_grade == Evidence.MODERATE


# ── Catalogo ───────────────────────────────────────────────────────────────

def test_every_metric_declares_a_unit():
    """Un numero senza unità è un numero su cui si può sbagliare in silenzio."""
    senza = [m.column for m in catalog.CATALOG if not m.unit]
    assert senza == [], f"metriche senza unità: {senza}"


def test_the_unit_is_read_from_the_column_name():
    assert catalog.unit_from_name("swim_distance_m") == "metri"
    assert catalog.unit_from_name("avg_hr_bpm") == "bpm"
    assert catalog.unit_from_name("hrv_ms") == "millisecondi"


def test_dimensionless_metrics_say_so_instead_of_staying_empty():
    """«Nessun suffisso» non deve significare due cose diverse: adimensionale
    e unità dimenticata."""
    assert catalog.unit_from_name("acwr") == "rapporto"
    assert catalog.unit_from_name("has_hrv") == "vero/falso"


def test_garmin_numbers_are_never_renamed_as_our_own():
    """Criterio: nessun numero Garmin proprietario rinominato come metrica
    propria. Body Battery resta di Garmin anche dentro le nostre tabelle."""
    proprietarie = [m for m in catalog.CATALOG if m.origin == "garmin"]
    assert proprietarie
    for metric in proprietarie:
        assert metric.data_class == "garmin_proprietary"


def test_every_metric_declares_a_method_version():
    """Un valore calcolato con la formula di sei mesi fa non è confrontabile con
    uno di oggi, e senza versione nessuno se ne accorge."""
    for metric in catalog.CATALOG:
        assert metric.method_version
