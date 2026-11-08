"""La fotografia dello stato (D0).

Il punto di questi test non è che i numeri siano giusti — quelli vengono da
`count(*)` — ma che le tre cose che il progetto ha già confuso una volta
restino separate: baseline immutabile, stato crescente e le tre coperture
diverse del dettaglio FIT.
"""

from datetime import date, datetime

import duckdb
import pytest

from garmin_coach import state_report
from garmin_coach.database import SCHEMA


@pytest.fixture
def connection():
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA)
    yield con
    con.close()


def _swim(con, activity_id, day, sport="lap_swimming", **columns):
    fields = {"activity_id": activity_id,
              "start_time_utc": datetime.combine(day, datetime.min.time()),
              "activity_date": day, "sport": sport, "is_swim": True,
              "environment": "pool" if sport == "lap_swimming" else "open_water",
              "source_object_id": "sha", "imported_at": datetime(2026, 8, 21)}
    fields.update(columns)
    names = ", ".join(fields)
    con.execute(f"INSERT INTO activities ({names}) VALUES "
                f"({', '.join('?' * len(fields))})", list(fields.values()))


def test_the_export_baseline_ignores_what_the_sync_added(connection):
    _swim(connection, 1, date(2026, 6, 1))            # dentro la baseline
    _swim(connection, 2, date(2026, 8, 1))            # aggiunta dal sync

    report = state_report.take(connection)

    assert report.baseline["sedute di nuoto"] == 1
    assert report.current["sedute di nuoto totali"] == 2
    assert report.current["aggiunte dopo il 2026-07-04"] == 1


def test_coverage_is_measured_only_on_the_closed_period(connection):
    """Una seduta recente con la frequenza cardiaca non deve far sembrare
    migliore la copertura storica: sono due domande diverse."""
    _swim(connection, 1, date(2019, 3, 1))                       # senza FC, come nel 2019
    _swim(connection, 2, date(2026, 8, 1), avg_hr_bpm=140.0)     # dopo l'export

    report = state_report.take(connection)
    hr = next(row for row in report.coverage if row[0] == "frequenza cardiaca")
    _label, present, total, share, _caveat = hr
    assert (present, total, share) == (0, 1, 0.0)


def test_the_three_fit_coverages_stay_separate(connection):
    """Criterio 10: FIT agganciato, lap disponibili e vasche disponibili sono
    tre numeri diversi. Fonderli nasconde esattamente il caso interessante —
    una seduta con i lap ma senza nessuna vasca utilizzabile."""
    _swim(connection, 1, date(2026, 6, 1))
    _swim(connection, 2, date(2026, 6, 2))
    _swim(connection, 3, date(2026, 6, 3))
    # la 1 ha lap e vasche, la 2 ha lap ma nessuna vasca attiva, la 3 niente
    connection.execute(
        "INSERT INTO activity_laps (activity_id, lap_index, source_object_id, imported_at) "
        "VALUES (1, 0, 'fit', ?), (2, 0, 'fit', ?)", [datetime(2026, 8, 21)] * 2)
    connection.execute(
        "INSERT INTO pool_lengths (activity_id, length_index, is_active) "
        "VALUES (1, 0, TRUE), (2, 0, FALSE)")

    detail = state_report.take(connection).detail
    assert detail["sedute in vasca"] == 3
    assert detail["  in vasca, con FIT"] == 2
    assert detail["  in vasca, con vasche"] == 1


def test_open_water_is_counted_apart_not_as_missing(connection):
    """In mare le vasche non esistono: contarle fra i dati mancanti
    trasformerebbe un concetto inapplicabile in un difetto."""
    _swim(connection, 1, date(2026, 6, 1), sport="open_water_swimming")

    detail = state_report.take(connection).detail
    assert detail["sedute in acque libere"] == 1
    assert detail["sedute in vasca"] == 0
    assert "non applicabile" in detail["  in mare, vasche"], (
        "in mare le vasche non sono un dato mancante: non si applicano")


def test_the_report_can_be_read_by_a_person(connection):
    _swim(connection, 1, date(2026, 6, 1))
    text = state_report.take(connection).text()

    assert "BASELINE IMMUTABILE" in text
    assert "STATO CORRENTE" in text
    assert "COPERTURA" in text
