"""Serie leggibili su più anni senza trasformare assenze in valori."""
from datetime import date, timedelta

import pytest

from garmin_coach.analysis import chart_series, periods


def daily(start, count, **values):
    return [dict(date=start+timedelta(days=i), **values) for i in range(count)]


@pytest.mark.parametrize("days,resolution", [(90, "day"), (91, "week"), (365, "week"), (730, "week"), (731, "month"), (6000, "month")])
def test_auto_resolution_keeps_year_and_alltime_readable(days, resolution):
    start = date(2010, 1, 1)
    result = chart_series.build([], start, start+timedelta(days=days-1), {"hrv": "mean"})
    assert result["resolution"] == resolution
    assert result["rows"][0]["date"] == str(start)
    assert result["rows"][-1]["period_end"] == str(start+timedelta(days=days-1))
    assert sum(row["hrv_expected_n"] for row in result["rows"]) == days


def test_null_is_missing_but_zero_is_an_observation_for_mean_and_sum():
    start = date(2026, 10, 26)
    rows = [{"date": start, "battery": 0, "distance": 0}, {"date": start+timedelta(days=1)}]
    result = chart_series.build(rows, start, start+timedelta(days=1), {"battery": "mean", "distance": "sum"})["rows"]
    assert result[0]["battery"] == result[0]["distance"] == 0
    assert result[0]["battery_n"] == result[0]["distance_n"] == 1
    assert result[1]["battery"] is result[1]["distance"] is None
    assert result[1]["battery_n"] == result[1]["distance_n"] == 0


def test_partial_weeks_start_on_requested_day_then_monday_with_exact_coverage():
    start, end = date(2026, 10, 28), date(2026, 11, 3)
    rows = [{"date": start, "hrv": 40, "distance": 100},
            {"date": start+timedelta(days=1), "hrv": 60, "distance": 200},
            {"date": end, "hrv": 0, "distance": 0}]
    result = chart_series.build(rows, start, end, {"hrv": "mean", "distance": "sum"}, "week")["rows"]
    assert [(r["date"], r["period_end"], r["hrv_expected_n"]) for r in result] == [
        ("2026-10-28", "2026-11-01", 5), ("2026-11-02", "2026-11-03", 2)]
    assert result[0]["hrv"] == 50 and result[0]["distance"] == 300
    assert result[0]["hrv_n"] == 2 and result[0]["hrv_coverage_pct"] == 40
    assert result[1]["hrv"] == 0 and result[1]["distance_n"] == 1


def test_partial_month_and_leap_year_bucket_boundaries():
    rows = chart_series.build([], "2024-01-30", "2024-03-02", {"steps": "sum"}, "month")["rows"]
    assert [(r["date"], r["period_end"], r["steps_expected_n"]) for r in rows] == [
        ("2024-01-30", "2024-01-31", 2), ("2024-02-01", "2024-02-29", 29), ("2024-03-01", "2024-03-02", 2)]
    assert all(row["steps"] is None and row["steps_trend"] is None for row in rows)


def test_mean_trend_is_trailing_median_with_fourteen_day_minimum():
    start = date(2026, 1, 1)
    rows = daily(start, 13, hrv=40)+[{"date": start+timedelta(days=13), "hrv": 1000}]
    result = chart_series.build(rows, start, start+timedelta(days=13), {"hrv": "mean"})["rows"]
    assert result[-2]["hrv_trend"] is None
    assert result[-1]["hrv_trend"] == 40
    assert result[-1]["hrv_trend_n"] == 14 and result[-1]["hrv_trend_expected_n"] == 28


def test_trend_excludes_future_rows_and_drops_observations_outside_trailing_window():
    start = date(2026, 1, 1)
    rows = daily(start, 28, hrv=40)+daily(start+timedelta(days=28), 28, hrv=80)
    rows.append({"date": start+timedelta(days=56), "hrv": 99999})
    result = chart_series.build(rows, start+timedelta(days=27), start+timedelta(days=55), {"hrv": "mean"})["rows"]
    assert result[0]["hrv_trend"] == 40
    assert result[-1]["hrv_trend"] == 80
    assert result[-1]["hrv_trend_n"] == 28


def test_empty_current_bucket_gets_no_trend_even_when_recent_history_is_dense():
    start = date(2026, 1, 5)
    rows = daily(start, 21, hrv=50, distance=100)
    result = chart_series.build(rows, start, start+timedelta(days=27), {"hrv": "mean", "distance": "sum"}, "week")["rows"]
    assert result[-2]["hrv_trend"] == 50
    assert result[-1]["hrv_trend_n"] == 21
    assert result[-1]["hrv"] is result[-1]["hrv_trend"] is None
    assert result[-1]["distance_trend_n"] == 3
    assert result[-1]["distance"] is result[-1]["distance_trend"] is None


def test_sum_trend_averages_previous_four_weekly_totals_in_same_units():
    start = date(2026, 1, 5)
    rows = daily(start, 28, distance=100)+daily(start+timedelta(days=28), 7, distance=200)
    report = chart_series.build(rows, start+timedelta(days=28), start+timedelta(days=34), {"distance": "sum"}, "week")
    current = report["rows"][0]
    assert current["distance"] == 1400 and current["distance_trend"] == 700
    assert current["distance_trend_n"] == current["distance_trend_expected_n"] == 4
    assert current["distance_trend_observed_days_n"] == current["distance_trend_expected_days_n"] == 28
    assert "4 settimane" in report["trend_methods"]["distance"]
    assert report["trend_count_units"]["distance"] == "periodi"
    assert report["trend_min_n_by_field"]["distance"] == 3


def test_sum_trend_requires_three_observed_previous_buckets_without_zero_filling():
    start = date(2026, 1, 5)
    rows = daily(start, 14, distance=100)+daily(start+timedelta(days=21), 7, distance=0)+daily(start+timedelta(days=28), 14, distance=200)
    report = chart_series.build(rows, start+timedelta(days=21), start+timedelta(days=41), {"distance": "sum"}, "week")["rows"]
    assert report[0]["distance_trend_n"] == 2 and report[0]["distance_trend"] is None
    assert report[1]["distance_trend_n"] == 3 and report[1]["distance_trend"] == pytest.approx(1400/3)
    assert report[2]["distance_trend_n"] == 3 and report[2]["distance_trend"] == 700


def test_sum_trend_is_null_for_partial_week_even_with_four_full_prior_weeks():
    start = date(2026, 1, 5)
    rows = daily(start, 40, distance=100)
    report = chart_series.build(rows, start+timedelta(days=30), start+timedelta(days=39), {"distance": "sum"}, "week")["rows"]
    assert report[0]["distance_expected_n"] == 5 and report[0]["distance_trend"] is None
    assert report[-1]["distance_expected_n"] == 5 and report[-1]["distance_trend"] is None


def test_monthly_sum_trend_uses_recorded_month_totals_and_no_future_current_values():
    rows = [{"date": f"2026-{month:02d}-01", "distance": month*100} for month in range(1, 7)]
    report = chart_series.build(rows, "2026-05-01", "2026-05-31", {"distance": "sum"}, "month")
    result = report["rows"][0]
    assert result["distance"] == 500 and result["distance_trend"] == 250
    assert result["distance_trend_n"] == result["distance_trend_expected_n"] == 4
    assert result["distance_trend_observed_days_n"] == 4
    assert result["distance_trend_expected_days_n"] == 120
    assert "4 mesi" in report["trend_methods"]["distance"]


def test_daily_sum_trend_is_trailing_daily_mean_with_fourteen_observations():
    start = date(2026, 1, 1)
    rows = daily(start, 13, steps=1000)+[{"date": start+timedelta(days=13), "steps": 2000}]
    result = chart_series.build(rows, start, start+timedelta(days=13), {"steps": "sum"})["rows"]
    assert result[-2]["steps_trend"] is None
    assert result[-1]["steps_trend"] == pytest.approx(15000/14)
    assert result[-1]["steps_trend_n"] == 14


def test_coverage_counts_observed_days_separately_for_each_metric():
    start = date(2026, 1, 5)
    rows = daily(start, 14, hrv=50)
    rows[0]["distance"] = 0
    result = chart_series.build(rows, start, start+timedelta(days=13), {"hrv": "mean", "distance": "sum"}, "week")["rows"][-1]
    assert result["hrv_trend"] == 50 and result["hrv_trend_n"] == 14
    assert result["distance_trend"] is None and result["distance_trend_n"] == 1
    assert result["distance"] is None


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "42"])
def test_invalid_values_are_not_counted_as_observed(value):
    report = chart_series.build([{"date": "2026-01-01", "hrv": value}], "2026-01-01", "2026-01-01", {"hrv": "mean"})
    assert report["rows"][0]["hrv"] is None and report["rows"][0]["hrv_n"] == 0


def test_duplicate_daily_rows_are_rejected_to_keep_coverage_meaningful():
    with pytest.raises(ValueError, match="una sola riga"):
        chart_series.build(daily(date(2026, 1, 1), 1, hrv=30)*2, "2026-01-01", "2026-01-01", {"hrv": "mean"})


def test_series_does_not_mutate_original_daily_rows():
    rows = [{"date": "2026-01-01", "hrv": 40}]
    chart_series.build(rows, "2026-01-01", "2026-01-01", {"hrv": "mean"})
    assert rows == [{"date": "2026-01-01", "hrv": 40}]


def test_explicit_alltime_start_accepts_history_since_2010():
    assert periods.parse({"days": "0", "start": "2010-01-01", "end": "2026-10-27"}) == (date(2010, 1, 1), date(2026, 10, 27))
    with pytest.raises(ValueError):
        periods.parse({"days": "0", "end": "2026-10-27"})
