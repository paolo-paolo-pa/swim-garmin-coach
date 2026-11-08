"""I quattro formati di timestamp che Garmin usa nello stesso export.

Il progetto precedente si è fermato qui: 15 file di carico non importati perché
``calendarDate`` conteneva un epoch al posto di una data ISO.
"""

from datetime import date, datetime, timezone

import pytest

from garmin_coach import timestamps


def test_epoch_in_milliseconds():
    # MetricsAcuteTrainingLoad.calendarDate — il caso che ha bloccato il vecchio import
    assert timestamps.to_date(1782086400000) == date(2026, 6, 22)


def test_epoch_in_seconds():
    assert timestamps.to_date(1782086400) == date(2026, 6, 22)


def test_iso_date_only():
    assert timestamps.to_date("2026-03-27") == date(2026, 3, 27)


def test_iso_with_single_decimal():
    # sleepData scrive i decimali con una cifra sola
    moment = timestamps.to_utc("2026-03-29T10:16:06.0")
    assert moment == datetime(2026, 3, 29, 10, 16, 6, tzinfo=timezone.utc)


def test_iso_with_zulu_suffix():
    assert timestamps.to_utc("2026-03-29T10:16:06Z").hour == 10


def test_missing_values_stay_missing():
    # Regola Aurea n.5: un valore assente non diventa una data di comodo
    assert timestamps.to_utc(None) is None
    assert timestamps.to_utc("") is None
    assert timestamps.to_date(None) is None


def test_implausible_year_is_rejected():
    # Il vecchio progetto aveva trovato un 1989 nei FIT di monitoring.
    # Un dato sbagliato non deve entrare travestito da dato buono.
    with pytest.raises(timestamps.TimestampOutOfRange):
        timestamps.to_utc(datetime(1989, 12, 31))


def test_naive_datetime_is_treated_as_utc():
    moment = timestamps.to_utc(datetime(2026, 1, 1, 12, 0))
    assert moment.tzinfo is timezone.utc
    assert moment.hour == 12
