"""Tests for muonledger.times date/time utilities."""

from datetime import date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta

from muonledger.times import (
    DateInterval,
    format_date,
    format_datetime,
    now,
    parse_date,
    parse_datetime,
    parse_period,
    today,
)


# ── Date parsing ──────────────────────────────────────────────────────────

class TestParseDate:
    def test_yyyy_slash_mm_dd(self):
        assert parse_date("2024/01/15") == date(2024, 1, 15)

    def test_yyyy_dash_mm_dd(self):
        assert parse_date("2024-03-07") == date(2024, 3, 7)

    def test_yyyy_dot_mm_dd(self):
        assert parse_date("2024.12.25") == date(2024, 12, 25)

    def test_single_digit_month_day(self):
        assert parse_date("2024/1/5") == date(2024, 1, 5)

    def test_mm_dd_current_year(self):
        result = parse_date("03/15")
        assert result == date(today().year, 3, 15)

    def test_m_d_current_year(self):
        result = parse_date("1/5")
        assert result == date(today().year, 1, 5)

    def test_whitespace_stripped(self):
        assert parse_date("  2024/06/01  ") == date(2024, 6, 1)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date("not-a-date")

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            parse_date("")


# ── Datetime parsing ──────────────────────────────────────────────────────

class TestParseDatetime:
    def test_full_datetime_slash(self):
        assert parse_datetime("2024/01/15 14:30:00") == datetime(2024, 1, 15, 14, 30, 0)

    def test_full_datetime_dash(self):
        assert parse_datetime("2024-03-07 08:15:45") == datetime(2024, 3, 7, 8, 15, 45)

    def test_no_seconds(self):
        assert parse_datetime("2024/06/01 12:00") == datetime(2024, 6, 1, 12, 0, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse datetime"):
            parse_datetime("nope")


# ── Formatting ────────────────────────────────────────────────────────────

class TestFormatDate:
    def test_default_format(self):
        assert format_date(date(2024, 1, 15)) == "2024/01/15"

    def test_custom_format(self):
        assert format_date(date(2024, 1, 15), "%Y-%m-%d") == "2024-01-15"


class TestFormatDatetime:
    def test_default_format(self):
        assert format_datetime(datetime(2024, 1, 15, 9, 30, 0)) == "2024/01/15 09:30:00"

    def test_custom_format(self):
        result = format_datetime(datetime(2024, 1, 15, 9, 30, 0), "%Y-%m-%d %H:%M")
        assert result == "2024-01-15 09:30"


# ── Helpers ───────────────────────────────────────────────────────────────

class TestHelpers:
    def test_today_returns_date(self):
        t = today()
        assert isinstance(t, date)

    def test_now_returns_datetime(self):
        n = now()
        assert isinstance(n, datetime)


# ── DateInterval ──────────────────────────────────────────────────────────

class TestDateInterval:
    def test_monthly_iteration(self):
        iv = DateInterval("months", 1, date(2024, 1, 1), date(2024, 4, 1))
        dates = list(iv)
        assert dates == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]

    def test_weekly_iteration(self):
        iv = DateInterval("weeks", 1, date(2024, 1, 1), date(2024, 1, 22))
        dates = list(iv)
        assert dates == [
            date(2024, 1, 1),
            date(2024, 1, 8),
            date(2024, 1, 15),
        ]

    def test_daily_iteration(self):
        iv = DateInterval("days", 1, date(2024, 1, 1), date(2024, 1, 4))
        dates = list(iv)
        assert dates == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]

    def test_quarterly_iteration(self):
        iv = DateInterval("quarters", 1, date(2024, 1, 1), date(2025, 1, 1))
        dates = list(iv)
        assert dates == [
            date(2024, 1, 1),
            date(2024, 4, 1),
            date(2024, 7, 1),
            date(2024, 10, 1),
        ]

    def test_yearly_iteration(self):
        iv = DateInterval("years", 1, date(2020, 1, 1), date(2024, 1, 1))
        dates = list(iv)
        assert dates == [
            date(2020, 1, 1),
            date(2021, 1, 1),
            date(2022, 1, 1),
            date(2023, 1, 1),
        ]

    def test_biweekly_iteration(self):
        iv = DateInterval("weeks", 2, date(2024, 1, 1), date(2024, 2, 1))
        dates = list(iv)
        assert dates == [date(2024, 1, 1), date(2024, 1, 15), date(2024, 1, 29)]

    def test_no_start_raises(self):
        iv = DateInterval("months", 1)
        with pytest.raises(ValueError, match="start date"):
            list(iv)

    def test_duration_days(self):
        iv = DateInterval("days", 3)
        assert iv.duration == timedelta(days=3)

    def test_duration_weeks(self):
        iv = DateInterval("weeks", 2)
        assert iv.duration == timedelta(weeks=2)

    def test_duration_months(self):
        iv = DateInterval("months", 1)
        assert iv.duration == relativedelta(months=1)

    def test_duration_quarters(self):
        iv = DateInterval("quarters", 1)
        assert iv.duration == relativedelta(months=3)

    def test_duration_years(self):
        iv = DateInterval("years", 1)
        assert iv.duration == relativedelta(years=1)

    def test_invalid_quantum(self):
        with pytest.raises(ValueError, match="Invalid quantum"):
            DateInterval("fortnights", 1)

    def test_repr(self):
        iv = DateInterval("months", 1, date(2024, 1, 1), date(2024, 12, 31))
        r = repr(iv)
        assert "months" in r
        assert "2024" in r

    def test_equality(self):
        a = DateInterval("months", 1, date(2024, 1, 1))
        b = DateInterval("months", 1, date(2024, 1, 1))
        assert a == b

    def test_inequality(self):
        a = DateInterval("months", 1)
        b = DateInterval("weeks", 1)
        assert a != b


# ── Period parsing ────────────────────────────────────────────────────────

class TestParsePeriod:
    def test_monthly(self):
        iv = parse_period("monthly")
        assert iv.quantum == "months"
        assert iv.length == 1

    def test_weekly(self):
        iv = parse_period("weekly")
        assert iv.quantum == "weeks"
        assert iv.length == 1

    def test_daily(self):
        iv = parse_period("daily")
        assert iv.quantum == "days"
        assert iv.length == 1

    def test_quarterly(self):
        iv = parse_period("quarterly")
        assert iv.quantum == "quarters"
        assert iv.length == 1

    def test_yearly(self):
        iv = parse_period("yearly")
        assert iv.quantum == "years"
        assert iv.length == 1

    def test_biweekly(self):
        iv = parse_period("biweekly")
        assert iv.quantum == "weeks"
        assert iv.length == 2

    def test_bimonthly(self):
        iv = parse_period("bimonthly")
        assert iv.quantum == "months"
        assert iv.length == 2

    def test_every_2_weeks(self):
        iv = parse_period("every 2 weeks")
        assert iv.quantum == "weeks"
        assert iv.length == 2

    def test_every_3_months(self):
        iv = parse_period("every 3 months")
        assert iv.quantum == "months"
        assert iv.length == 3

    def test_every_1_day(self):
        iv = parse_period("every 1 day")
        assert iv.quantum == "days"
        assert iv.length == 1

    def test_every_7_days(self):
        iv = parse_period("every 7 days")
        assert iv.quantum == "days"
        assert iv.length == 7

    def test_monthly_with_bounds(self):
        iv = parse_period("monthly from 2024/01/01 to 2024/12/31")
        assert iv.quantum == "months"
        assert iv.length == 1
        assert iv.start == date(2024, 1, 1)
        assert iv.end == date(2024, 12, 31)

    def test_weekly_from(self):
        iv = parse_period("weekly from 2024/03/01")
        assert iv.quantum == "weeks"
        assert iv.start == date(2024, 3, 1)
        assert iv.end is None

    def test_weekly_to(self):
        iv = parse_period("weekly to 2024/06/30")
        assert iv.quantum == "weeks"
        assert iv.start is None
        assert iv.end == date(2024, 6, 30)

    def test_this_month(self):
        iv = parse_period("this month")
        t = today()
        assert iv.start == t.replace(day=1)
        assert iv.quantum == "months"

    def test_last_month(self):
        iv = parse_period("last month")
        t = today()
        expected_end = t.replace(day=1)
        assert iv.end == expected_end
        assert iv.quantum == "months"

    def test_this_year(self):
        iv = parse_period("this year")
        t = today()
        assert iv.start == date(t.year, 1, 1)
        assert iv.end == date(t.year + 1, 1, 1)

    def test_last_year(self):
        iv = parse_period("last year")
        t = today()
        assert iv.start == date(t.year - 1, 1, 1)
        assert iv.end == date(t.year, 1, 1)

    def test_invalid_period(self):
        with pytest.raises(ValueError, match="Cannot parse period"):
            parse_period("gibberish")

    def test_case_insensitive(self):
        iv = parse_period("Monthly")
        assert iv.quantum == "months"

    def test_bounded_iteration(self):
        iv = parse_period("monthly from 2024/01/01 to 2024/04/01")
        dates = list(iv)
        assert dates == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
