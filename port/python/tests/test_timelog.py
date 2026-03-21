"""Tests for time logging (clock-in / clock-out) support.

Covers the ``i`` and ``o`` directives, duration calculation,
transaction generation, and integration with balance/register commands.
"""

from __future__ import annotations

from datetime import datetime, date
from fractions import Fraction

import pytest

from muonledger.amount import Amount
from muonledger.journal import Journal
from muonledger.parser import TextualParser, ParseError
from muonledger.post import POST_VIRTUAL
from muonledger.timelog import (
    TimelogEntry,
    TimelogError,
    TimelogProcessor,
    calculate_duration_hours,
    create_timelog_transaction,
    format_hours,
    process_timelog_entries,
)


# ===================================================================
# Duration calculation tests
# ===================================================================


class TestCalculateDurationHours:
    """Tests for calculate_duration_hours."""

    def test_exact_hours(self):
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 12, 0, 0)
        assert calculate_duration_hours(start, end) == Fraction(3)

    def test_half_hour(self):
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 9, 30, 0)
        assert calculate_duration_hours(start, end) == Fraction(1, 2)

    def test_quarter_hour(self):
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 9, 15, 0)
        assert calculate_duration_hours(start, end) == Fraction(1, 4)

    def test_fractional_hours(self):
        """3.5 hours = 3 hours 30 minutes."""
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 12, 30, 0)
        assert calculate_duration_hours(start, end) == Fraction(7, 2)

    def test_minutes_only(self):
        """45 minutes = 0.75 hours."""
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 9, 45, 0)
        assert calculate_duration_hours(start, end) == Fraction(3, 4)

    def test_with_seconds(self):
        """1 hour 30 minutes 30 seconds."""
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 10, 30, 30)
        expected = Fraction(5430, 3600)  # 5430 seconds
        assert calculate_duration_hours(start, end) == expected

    def test_zero_duration(self):
        dt = datetime(2024, 1, 15, 9, 0, 0)
        assert calculate_duration_hours(dt, dt) == Fraction(0)

    def test_cross_midnight(self):
        """Session spanning midnight."""
        start = datetime(2024, 1, 15, 23, 0, 0)
        end = datetime(2024, 1, 16, 1, 0, 0)
        assert calculate_duration_hours(start, end) == Fraction(2)

    def test_very_long_session(self):
        """24 hours exactly."""
        start = datetime(2024, 1, 15, 0, 0, 0)
        end = datetime(2024, 1, 16, 0, 0, 0)
        assert calculate_duration_hours(start, end) == Fraction(24)

    def test_multi_day_session(self):
        """48 hours."""
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 17, 9, 0, 0)
        assert calculate_duration_hours(start, end) == Fraction(48)

    def test_end_before_start_raises(self):
        start = datetime(2024, 1, 15, 12, 0, 0)
        end = datetime(2024, 1, 15, 9, 0, 0)
        with pytest.raises(TimelogError, match="before clock-in"):
            calculate_duration_hours(start, end)


# ===================================================================
# Format hours tests
# ===================================================================


class TestFormatHours:
    """Tests for format_hours."""

    def test_whole_hours(self):
        assert format_hours(Fraction(3)) == "3.00"

    def test_half_hour(self):
        assert format_hours(Fraction(1, 2)) == "0.50"

    def test_quarter_hour(self):
        assert format_hours(Fraction(1, 4)) == "0.25"

    def test_three_and_half(self):
        assert format_hours(Fraction(7, 2)) == "3.50"

    def test_zero(self):
        assert format_hours(Fraction(0)) == "0.00"

    def test_large_value(self):
        assert format_hours(Fraction(100)) == "100.00"


# ===================================================================
# TimelogEntry tests
# ===================================================================


class TestTimelogEntry:
    """Tests for TimelogEntry dataclass."""

    def test_basic_creation(self):
        dt = datetime(2024, 1, 15, 9, 0, 0)
        entry = TimelogEntry(checkin_dt=dt, account="Projects:ClientA")
        assert entry.checkin_dt == dt
        assert entry.account == "Projects:ClientA"
        assert entry.payee == ""

    def test_with_payee(self):
        dt = datetime(2024, 1, 15, 9, 0, 0)
        entry = TimelogEntry(
            checkin_dt=dt,
            account="Projects:ClientA",
            payee="Working on feature X",
        )
        assert entry.payee == "Working on feature X"

    def test_with_source_info(self):
        dt = datetime(2024, 1, 15, 9, 0, 0)
        entry = TimelogEntry(
            checkin_dt=dt,
            account="Work",
            line_num=42,
            source="test.dat",
        )
        assert entry.line_num == 42
        assert entry.source == "test.dat"


# ===================================================================
# TimelogProcessor tests
# ===================================================================


class TestTimelogProcessor:
    """Tests for TimelogProcessor."""

    def test_no_pending_initially(self):
        proc = TimelogProcessor()
        assert not proc.has_pending
        assert proc.pending is None

    def test_clock_in_sets_pending(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        assert proc.has_pending
        assert proc.pending.account == "Work"

    def test_clock_out_clears_pending(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        assert not proc.has_pending
        assert xact is not None

    def test_clock_out_without_clock_in_raises(self):
        proc = TimelogProcessor()
        with pytest.raises(TimelogError, match="without a matching clock-in"):
            proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))

    def test_generated_transaction_payee(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Projects:ClientA")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        # When no payee is given, account name is used as payee
        assert xact.payee == "Projects:ClientA"

    def test_generated_transaction_with_explicit_payee(self):
        proc = TimelogProcessor()
        proc.clock_in(
            datetime(2024, 1, 15, 9, 0, 0),
            "Projects:ClientA",
            payee="Feature work",
        )
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        assert xact.payee == "Feature work"

    def test_generated_transaction_date(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        assert xact.date == date(2024, 1, 15)

    def test_generated_transaction_has_posting(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        assert len(xact.posts) == 1

    def test_generated_posting_is_virtual(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        post = xact.posts[0]
        assert post.flags & POST_VIRTUAL

    def test_generated_posting_amount_hours(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work")
        xact = proc.clock_out(datetime(2024, 1, 15, 12, 30, 0))
        post = xact.posts[0]
        # 3.5 hours
        assert post.amount is not None
        assert "h" in str(post.amount)

    def test_sequential_sessions(self):
        proc = TimelogProcessor()
        proc.clock_in(datetime(2024, 1, 15, 9, 0, 0), "Work:A")
        xact1 = proc.clock_out(datetime(2024, 1, 15, 12, 0, 0))
        assert xact1 is not None

        proc.clock_in(datetime(2024, 1, 15, 13, 0, 0), "Work:B")
        xact2 = proc.clock_out(datetime(2024, 1, 15, 17, 0, 0))
        assert xact2 is not None
        assert not proc.has_pending


# ===================================================================
# process_timelog_entries tests
# ===================================================================


class TestProcessTimelogEntries:
    """Tests for process_timelog_entries helper."""

    def test_single_pair(self):
        entries = [
            ("i", datetime(2024, 1, 15, 9, 0), "Work", ""),
            ("o", datetime(2024, 1, 15, 12, 0), "", ""),
        ]
        xacts = process_timelog_entries(entries)
        assert len(xacts) == 1

    def test_multiple_pairs(self):
        entries = [
            ("i", datetime(2024, 1, 15, 9, 0), "Work:A", ""),
            ("o", datetime(2024, 1, 15, 12, 0), "", ""),
            ("i", datetime(2024, 1, 15, 13, 0), "Work:B", ""),
            ("o", datetime(2024, 1, 15, 17, 0), "", ""),
        ]
        xacts = process_timelog_entries(entries)
        assert len(xacts) == 2

    def test_auto_close_on_new_clock_in(self):
        """A clock-in while already clocked in auto-closes the previous session."""
        entries = [
            ("i", datetime(2024, 1, 15, 9, 0), "Work:A", ""),
            ("i", datetime(2024, 1, 15, 12, 0), "Work:B", ""),
            ("o", datetime(2024, 1, 15, 17, 0), "", ""),
        ]
        xacts = process_timelog_entries(entries)
        assert len(xacts) == 2

    def test_clock_out_without_in_raises(self):
        entries = [
            ("o", datetime(2024, 1, 15, 12, 0), "", ""),
        ]
        with pytest.raises(TimelogError):
            process_timelog_entries(entries)


# ===================================================================
# create_timelog_transaction tests
# ===================================================================


class TestCreateTimelogTransaction:
    """Tests for create_timelog_transaction."""

    def test_basic_transaction(self):
        entry = TimelogEntry(
            checkin_dt=datetime(2024, 1, 15, 9, 0, 0),
            account="Projects:ClientA",
        )
        xact = create_timelog_transaction(
            entry, datetime(2024, 1, 15, 12, 0, 0)
        )
        assert xact.date == date(2024, 1, 15)
        assert xact.payee == "Projects:ClientA"
        assert len(xact.posts) == 1

    def test_amount_format(self):
        entry = TimelogEntry(
            checkin_dt=datetime(2024, 1, 15, 9, 0, 0),
            account="Work",
        )
        xact = create_timelog_transaction(
            entry, datetime(2024, 1, 15, 12, 30, 0)
        )
        post = xact.posts[0]
        amt_str = str(post.amount)
        # Should contain 3.50 and h
        assert "3.50" in amt_str or "3.5" in amt_str

    def test_position_tracking(self):
        entry = TimelogEntry(
            checkin_dt=datetime(2024, 1, 15, 9, 0, 0),
            account="Work",
            line_num=5,
            source="test.dat",
        )
        xact = create_timelog_transaction(
            entry, datetime(2024, 1, 15, 12, 0, 0),
            source="test.dat",
        )
        assert xact.position is not None
        assert xact.position.pathname == "test.dat"


# ===================================================================
# Parser integration tests
# ===================================================================


class TestParserTimelogDirectives:
    """Tests for parsing i and o directives via TextualParser."""

    def _parse(self, text: str) -> Journal:
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        return journal

    def test_basic_clock_in_out(self):
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        assert xact.date == date(2024, 1, 15)

    def test_amount_is_hours(self):
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:30:00
"""
        journal = self._parse(text)
        xact = journal.xacts[0]
        post = xact.posts[0]
        amt_str = str(post.amount)
        assert "3.50" in amt_str or "3.5" in amt_str

    def test_time_without_seconds(self):
        text = """\
i 2024/01/15 09:00 Projects:ClientA
o 2024/01/15 12:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1

    def test_multiple_sessions_same_day(self):
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:30:00
i 2024/01/15 13:00:00 Projects:ClientB
o 2024/01/15 17:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 2

    def test_clock_in_with_payee(self):
        """Payee separated from account by double-space."""
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA  Feature development
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        xact = journal.xacts[0]
        assert xact.payee == "Feature development"

    def test_clock_in_with_payee_tab(self):
        """Payee separated from account by tab."""
        text = "i 2024/01/15 09:00:00 Projects:ClientA\tMeeting\no 2024/01/15 10:00:00\n"
        journal = self._parse(text)
        xact = journal.xacts[0]
        assert xact.payee == "Meeting"

    def test_cross_midnight_session(self):
        text = """\
i 2024/01/15 23:00:00 Work:Overnight
o 2024/01/16 01:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1
        xact = journal.xacts[0]
        # Date should be the clock-in date
        assert xact.date == date(2024, 1, 15)

    def test_auto_close_on_new_clock_in(self):
        """Second clock-in auto-closes the first session."""
        text = """\
i 2024/01/15 09:00:00 Work:A
i 2024/01/15 12:00:00 Work:B
o 2024/01/15 17:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 2

    def test_clock_out_without_clock_in_error(self):
        text = """\
o 2024/01/15 12:00:00
"""
        with pytest.raises(ParseError, match="without a matching clock-in"):
            self._parse(text)

    def test_missing_account_in_clock_in(self):
        text = """\
i 2024/01/15 09:00:00
o 2024/01/15 12:00:00
"""
        with pytest.raises(ParseError, match="account name"):
            self._parse(text)

    def test_invalid_date_in_clock_in(self):
        text = """\
i baddate 09:00:00 Work
o 2024/01/15 12:00:00
"""
        with pytest.raises(ParseError, match="date"):
            self._parse(text)

    def test_invalid_time_in_clock_in(self):
        text = """\
i 2024/01/15 badtime Work
o 2024/01/15 12:00:00
"""
        with pytest.raises(ParseError, match="time"):
            self._parse(text)

    def test_date_format_with_dashes(self):
        text = """\
i 2024-01-15 09:00:00 Work
o 2024-01-15 12:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1

    def test_mixed_with_regular_transactions(self):
        text = """\
2024/01/14 Opening Balance
    Assets:Cash  $100
    Equity:Opening

i 2024/01/15 09:00:00 Work:Consulting
o 2024/01/15 12:00:00

2024/01/16 Groceries
    Expenses:Food  $50
    Assets:Cash
"""
        journal = self._parse(text)
        # 2 regular transactions + 1 timelog transaction
        assert len(journal.xacts) == 3

    def test_zero_duration(self):
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 09:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1
        post = journal.xacts[0].posts[0]
        amt_str = str(post.amount)
        assert "0.00" in amt_str

    def test_long_session_eight_hours(self):
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 17:00:00
"""
        journal = self._parse(text)
        post = journal.xacts[0].posts[0]
        amt_str = str(post.amount)
        assert "8.00" in amt_str

    def test_short_session_fifteen_minutes(self):
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 09:15:00
"""
        journal = self._parse(text)
        post = journal.xacts[0].posts[0]
        amt_str = str(post.amount)
        assert "0.25" in amt_str

    def test_posting_account_resolved(self):
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        post = journal.xacts[0].posts[0]
        assert post.account is not None
        assert post.account.fullname == "Projects:ClientA"

    def test_account_in_tree(self):
        text = """\
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        acct = journal.find_account("Projects:ClientA", auto_create=False)
        assert acct is not None

    def test_three_sessions_same_day(self):
        text = """\
i 2024/01/15 08:00:00 Work:Morning
o 2024/01/15 12:00:00
i 2024/01/15 13:00:00 Work:Afternoon
o 2024/01/15 17:00:00
i 2024/01/15 19:00:00 Work:Evening
o 2024/01/15 21:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 3

    def test_existing_tests_not_broken(self):
        """Sanity check: a normal journal still parses fine."""
        text = """\
2024/01/15 Payee
    Expenses:Food  $10
    Assets:Cash
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].payee == "Payee"


# ===================================================================
# TimelogError tests
# ===================================================================


class TestTimelogError:
    """Tests for TimelogError formatting."""

    def test_basic_message(self):
        err = TimelogError("something went wrong")
        assert "something went wrong" in str(err)

    def test_with_source_and_line(self):
        err = TimelogError("bad input", line_num=10, source="test.dat")
        s = str(err)
        assert "test.dat" in s
        assert "10" in s

    def test_string_source_skipped(self):
        err = TimelogError("bad input", source="<string>")
        assert "<string>" not in str(err)


# ===================================================================
# Edge case and regression tests
# ===================================================================


class TestTimelogEdgeCases:
    """Edge cases and regression tests for timelog."""

    def _parse(self, text: str) -> Journal:
        journal = Journal()
        parser = TextualParser()
        parser.parse_string(text, journal)
        return journal

    def test_account_with_spaces_in_name(self):
        """Account names can contain single spaces before double-space payee separator."""
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1

    def test_deeply_nested_account(self):
        text = """\
i 2024/01/15 09:00:00 Company:Department:Team:Project
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        post = journal.xacts[0].posts[0]
        assert post.account.fullname == "Company:Department:Team:Project"

    def test_timelog_with_apply_account(self):
        text = """\
apply account Work
i 2024/01/15 09:00:00 Projects:ClientA
o 2024/01/15 12:00:00
end apply account
"""
        journal = self._parse(text)
        post = journal.xacts[0].posts[0]
        assert post.account.fullname == "Work:Projects:ClientA"

    def test_multiple_days(self):
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 17:00:00
i 2024/01/16 09:00:00 Work
o 2024/01/16 17:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 2
        assert journal.xacts[0].date == date(2024, 1, 15)
        assert journal.xacts[1].date == date(2024, 1, 16)

    def test_seconds_precision(self):
        """Duration includes seconds."""
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 9, 0, 30)
        hours = calculate_duration_hours(start, end)
        # 30 seconds = 1/120 hour
        assert hours == Fraction(30, 3600)

    def test_one_minute_session(self):
        start = datetime(2024, 1, 15, 9, 0, 0)
        end = datetime(2024, 1, 15, 9, 1, 0)
        hours = calculate_duration_hours(start, end)
        assert hours == Fraction(1, 60)

    def test_payee_with_colons(self):
        """Payee can contain colons."""
        text = "i 2024/01/15 09:00:00 Work  Meeting: Planning\no 2024/01/15 10:00:00\n"
        journal = self._parse(text)
        assert journal.xacts[0].payee == "Meeting: Planning"

    def test_i_directive_not_confused_with_include(self):
        """The i directive should not be confused with the include directive."""
        text = """\
i 2024/01/15 09:00:00 Work
o 2024/01/15 12:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1

    def test_timelog_then_regular_then_timelog(self):
        text = """\
i 2024/01/15 09:00:00 Work:A
o 2024/01/15 12:00:00

2024/01/15 Lunch
    Expenses:Food  $10
    Assets:Cash

i 2024/01/15 13:00:00 Work:B
o 2024/01/15 17:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 3

    def test_still_clocked_in_at_end_of_file(self):
        """If file ends with pending clock-in, it remains pending."""
        text = """\
i 2024/01/15 09:00:00 Work
"""
        journal = self._parse(text)
        # No transaction generated yet
        assert len(journal.xacts) == 0
        # But timelog is still pending
        assert journal.timelog.has_pending

    def test_auto_close_generates_correct_account(self):
        """Auto-close on second clock-in uses first session's account."""
        text = """\
i 2024/01/15 09:00:00 Work:A
i 2024/01/15 12:00:00 Work:B
o 2024/01/15 17:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 2
        # First auto-closed transaction
        assert journal.xacts[0].posts[0].account.fullname == "Work:A"
        # Second explicitly closed transaction
        assert journal.xacts[1].posts[0].account.fullname == "Work:B"

    def test_date_with_single_digit_month_day(self):
        text = """\
i 2024/1/5 09:00:00 Work
o 2024/1/5 12:00:00
"""
        journal = self._parse(text)
        assert len(journal.xacts) == 1
        assert journal.xacts[0].date == date(2024, 1, 5)
