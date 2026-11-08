"""La fetta verticale (D8).

Il rapporto vero si legge sui dati reali. Qui si verifica che regga i casi per
cui è stato costruito: gli strati vuoti, i dati mancanti, e il fatto che i
controlli automatici trovino davvero un difetto quando c'è.
"""

from datetime import datetime

import duckdb
import pytest

from garmin_coach import vertical_slice
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _swim(con, activity_id, day, sport="lap_swimming", distance=3000.0,
          duration=3600.0, pool=25.0, device=1):
    con.execute(
        "INSERT INTO activities (activity_id, start_time_utc, activity_date, "
        "sport, is_swim, environment, distance_m, duration_s, pool_length_m, "
        "device_id, source_object_id, imported_at) "
        "VALUES (?, ?, ?, ?, TRUE, ?, ?, ?, ?, ?, 'sha', ?)",
        [activity_id, datetime.combine(day, datetime.min.time()), day, sport,
         "pool" if sport == "lap_swimming" else "open_water", distance, duration,
         pool, device, datetime(2026, 8, 21)])


def _source(con, source_object_id="sorgente-1"):
    """Una sorgente nel catalogo. Serve perché i lap ne citano una, e citarne
    una inesistente è proprio il difetto che il rapporto deve trovare."""
    con.execute(
        "INSERT OR IGNORE INTO source_objects (source_object_id, kind, locator, "
        "sha256, observed_at) VALUES (?, 'fit', 'prova.fit', ?, ?)",
        [source_object_id, "a" * 64, datetime(2026, 8, 21)])


def _lap(con, activity_id, lap_index, **columns):
    fields = {"activity_id": activity_id, "lap_index": lap_index,
              "is_rest": False, "distance_m": 100.0, "duration_s": 86.0,
              "stroke": "freestyle", "environment": "pool",
              "source_object_id": "sorgente-1", "imported_at": datetime(2026, 8, 21)}
    fields.update(columns)
    if fields["source_object_id"] == "sorgente-1":
        _source(con)
    con.execute(f"INSERT INTO activity_laps ({', '.join(fields)}) VALUES "
                f"({', '.join('?' * len(fields))})", list(fields.values()))


def _verdict(con, activity_id, verdict, reason="motivo"):
    con.execute(
        "INSERT INTO activity_source_matches (activity_id, source_object_id, "
        "verdict, method, reason, decided_at) VALUES (?, 'x', ?, 'timestamp', ?, ?)",
        [activity_id, verdict, reason, datetime(2026, 8, 21)])


def test_an_empty_stratum_says_so_instead_of_being_skipped(connection):
    """Uno strato senza casi è un'informazione: vuol dire che quella cosa non
    è mai stata provata. Tacere lo farebbe sembrare superato."""
    cases = vertical_slice.run(connection)

    assert all(case.empty for case in cases)
    text = vertical_slice.render(cases)
    assert "NESSUN CASO in archivio" in text
    assert "0 strati su 11" in text


def test_a_session_without_distance_does_not_break_the_report(connection):
    """Il campione va a cercare apposta i dati mancanti: il rapporto non può
    rompersi proprio sul caso che esiste per esaminarli."""
    _swim(connection, 1, datetime(2026, 6, 1).date(), distance=None, duration=None)
    _verdict(connection, 1, "ambiguous")

    text = vertical_slice.render(vertical_slice.run(connection))
    assert "distanza mancante" in text
    assert "durata mancante" in text


def test_a_session_with_detail_shows_its_laps(connection):
    _swim(connection, 1, datetime(2026, 6, 1).date())
    _lap(connection, 1, 0)
    _lap(connection, 1, 1, is_rest=True, distance_m=0.0, stroke=None)

    cases = {case.stratum: case for case in vertical_slice.run(connection)}
    trovato = cases["con recuperi registrati"]
    assert not trovato.empty
    assert any("1 lap nuotati, 1 recuperi" in f for f in trovato.findings)
    assert trovato.problems == []


def test_a_rest_carrying_a_stroke_is_caught(connection):
    """Il controllo deve trovare il difetto quando c'è, altrimenti è decorazione."""
    _swim(connection, 1, datetime(2026, 6, 1).date())
    _lap(connection, 1, 0, is_rest=True, distance_m=0.0, stroke="freestyle")

    cases = {case.stratum: case for case in vertical_slice.run(connection)}
    assert "un recupero porta uno stile" in cases["vasca 25 m"].problems


def test_lengths_in_open_water_are_caught(connection):
    """In mare le vasche non esistono: se ne comparissero, sarebbero inventate."""
    _swim(connection, 1, datetime(2026, 6, 1).date(),
          sport="open_water_swimming", pool=None)
    _lap(connection, 1, 0, environment="open_water", active_lengths_count=4)

    cases = {case.stratum: case for case in vertical_slice.run(connection)}
    assert any("vasche in acque libere" in p
               for p in cases["acque libere"].problems)


def test_a_lap_without_a_source_cannot_even_be_written(connection):
    """Criterio 6, garantito dallo schema invece che da un controllo: una riga
    granulare senza provenienza non entra proprio nel database."""
    _swim(connection, 1, datetime(2026, 6, 1).date())
    with pytest.raises(duckdb.ConstraintException, match="source_object_id"):
        _lap(connection, 1, 0, source_object_id=None)


def test_a_source_that_does_not_exist_is_caught(connection):
    """Quello che lo schema non può impedire: un riferimento a una sorgente
    assente dal catalogo. È peggio di una provenienza mancante, perché sembra
    esserci."""
    _swim(connection, 1, datetime(2026, 6, 1).date())
    _lap(connection, 1, 0, source_object_id="sorgente-mai-registrata")

    cases = {case.stratum: case for case in vertical_slice.run(connection)}
    assert any("non esiste" in p for p in cases["vasca 25 m"].problems)


def test_a_session_without_detail_must_explain_why(connection):
    _swim(connection, 1, datetime(2026, 6, 1).date())
    _verdict(connection, 1, "unmatched", "nessun FIT entro 60 s")

    cases = {case.stratum: case for case in vertical_slice.run(connection)}
    caso = cases["senza file FIT"]
    assert caso.problems == []
    assert any("motivo:" in f for f in caso.findings)


def test_the_rendered_report_counts_covered_strata(connection):
    _swim(connection, 1, datetime(2026, 6, 1).date())
    text = vertical_slice.render(vertical_slice.run(connection))
    assert "strati su 11" in text
    assert "Nessun problema rilevato" in text
