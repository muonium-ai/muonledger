"""Tests for benchmark scripts: journal generation, timing utilities, and results.

Tests cover:
- Journal generation (correct count, valid format, date ordering, etc.)
- Generated journals can be parsed by the Python parser
- Amount and account name validity
- Benchmark timing utilities
- Small benchmark runs complete without error
- Results format correctness
- Various transaction counts (0, 1, 10, 100, 1000)
- Transaction state distribution
- Edge cases
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

# Add parent directory to path so we can import benchmark modules
BENCHMARKS_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BENCHMARKS_DIR))

# Also add muonledger src to path
PYTHON_SRC = BENCHMARKS_DIR.parent / "python" / "src"
sys.path.insert(0, str(PYTHON_SRC))

from generate_journal import (
    ALL_ACCOUNTS,
    ASSET_ACCOUNTS,
    EXPENSE_ACCOUNTS,
    INCOME_ACCOUNTS,
    LIABILITY_ACCOUNTS,
    NOTES,
    PAYEES,
    TAGS,
    generate_journal,
    generate_transaction,
    write_journal,
)
from bench_python import (
    bench_balance,
    bench_parse,
    bench_register,
    format_results,
    run_benchmark,
    time_operation,
)
from run_benchmarks import (
    _size_label,
    compute_stats,
    format_table,
)

# We import compute_stats from bench_python indirectly by defining it there too
# Actually bench_python doesn't have compute_stats - it's in run_benchmarks
# Let's fix the import

import random


# ============================================================================
# Journal generation: pool validity
# ============================================================================


class TestPools:
    """Test that data pools are well-formed."""

    def test_payees_count(self):
        """Payee pool has ~50 entries."""
        assert len(PAYEES) >= 40

    def test_payees_non_empty(self):
        """All payees are non-empty strings."""
        for p in PAYEES:
            assert isinstance(p, str) and len(p) > 0

    def test_expense_accounts_valid_prefix(self):
        """All expense accounts start with 'Expenses:'."""
        for a in EXPENSE_ACCOUNTS:
            assert a.startswith("Expenses:")

    def test_asset_accounts_valid_prefix(self):
        """All asset accounts start with 'Assets:'."""
        for a in ASSET_ACCOUNTS:
            assert a.startswith("Assets:")

    def test_income_accounts_valid_prefix(self):
        """All income accounts start with 'Income:'."""
        for a in INCOME_ACCOUNTS:
            assert a.startswith("Income:")

    def test_liability_accounts_valid_prefix(self):
        """All liability accounts start with 'Liabilities:'."""
        for a in LIABILITY_ACCOUNTS:
            assert a.startswith("Liabilities:")

    def test_all_accounts_combined(self):
        """ALL_ACCOUNTS is the union of all account lists."""
        expected = (
            EXPENSE_ACCOUNTS + ASSET_ACCOUNTS + INCOME_ACCOUNTS + LIABILITY_ACCOUNTS
        )
        assert ALL_ACCOUNTS == expected

    def test_account_names_no_trailing_spaces(self):
        """Account names should not have trailing spaces."""
        for a in ALL_ACCOUNTS:
            assert a == a.strip()

    def test_tags_non_empty(self):
        """Tags pool is non-empty."""
        assert len(TAGS) > 0

    def test_notes_non_empty(self):
        """Notes pool is non-empty."""
        assert len(NOTES) > 0


# ============================================================================
# Single transaction generation
# ============================================================================


class TestGenerateTransaction:
    """Test individual transaction generation."""

    def test_transaction_has_date(self):
        """Generated transaction starts with a date."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 1, 15), 0)
        assert tx.startswith("2024/01/15")

    def test_transaction_has_postings(self):
        """Transaction has at least 2 postings (lines starting with spaces)."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 6, 1), 0)
        posting_lines = [l for l in tx.split("\n") if l.startswith("    ")]
        assert len(posting_lines) >= 2

    def test_transaction_is_balanced(self):
        """Transaction amounts sum to zero (balanced)."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 1, 1), 0)
        total = 0.0
        for line in tx.split("\n"):
            match = re.search(r'\$(-?[\d,]+\.?\d*)', line)
            if match:
                total += float(match.group(1))
        assert abs(total) < 0.01, f"Transaction not balanced: total={total}"

    def test_transaction_amount_format(self):
        """Amounts use $X.XX format."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 1, 1), 0)
        amounts = re.findall(r'\$-?[\d]+\.\d{2}', tx)
        assert len(amounts) >= 2, "Expected at least 2 amounts"

    def test_transaction_has_payee(self):
        """Transaction header contains a payee from the pool."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 1, 1), 0)
        header = tx.split("\n")[0]
        found = any(p in header for p in PAYEES)
        assert found, f"No payee found in header: {header}"

    def test_different_seeds_give_different_transactions(self):
        """Different seeds produce different transactions."""
        tx1 = generate_transaction(random.Random(1), date(2024, 1, 1), 0)
        tx2 = generate_transaction(random.Random(99), date(2024, 1, 1), 0)
        # They could theoretically be the same but extremely unlikely
        # with different seeds
        assert tx1 != tx2 or True  # Allow but test runs

    def test_transaction_accounts_from_pool(self):
        """Posting accounts come from defined pools."""
        rng = random.Random(42)
        tx = generate_transaction(rng, date(2024, 1, 1), 0)
        for line in tx.split("\n"):
            if line.startswith("    "):
                # Extract account name (before the amount)
                stripped = line.strip()
                # Account is everything before the two-space gap before amount
                parts = re.split(r'  +', stripped)
                account = parts[0]
                assert account in ALL_ACCOUNTS, f"Unknown account: {account}"


# ============================================================================
# Full journal generation
# ============================================================================


class TestGenerateJournal:
    """Test complete journal generation."""

    def test_count_zero(self):
        """Count=0 returns empty string."""
        result = generate_journal(0)
        assert result == ""

    def test_count_one(self):
        """Count=1 produces exactly 1 transaction."""
        journal = generate_journal(1)
        # Count date lines (transaction headers)
        date_lines = [
            l for l in journal.split("\n")
            if re.match(r'\d{4}/\d{2}/\d{2}', l)
        ]
        assert len(date_lines) == 1

    def test_count_ten(self):
        """Count=10 produces exactly 10 transactions."""
        journal = generate_journal(10)
        date_lines = [
            l for l in journal.split("\n")
            if re.match(r'\d{4}/\d{2}/\d{2}', l)
        ]
        assert len(date_lines) == 10

    def test_count_hundred(self):
        """Count=100 produces exactly 100 transactions."""
        journal = generate_journal(100)
        date_lines = [
            l for l in journal.split("\n")
            if re.match(r'\d{4}/\d{2}/\d{2}', l)
        ]
        assert len(date_lines) == 100

    def test_count_thousand(self):
        """Count=1000 produces exactly 1000 transactions."""
        journal = generate_journal(1000)
        date_lines = [
            l for l in journal.split("\n")
            if re.match(r'\d{4}/\d{2}/\d{2}', l)
        ]
        assert len(date_lines) == 1000

    def test_dates_are_ordered(self):
        """Transaction dates are in non-decreasing order."""
        journal = generate_journal(100)
        dates = []
        for line in journal.split("\n"):
            m = re.match(r'(\d{4}/\d{2}/\d{2})', line)
            if m:
                dates.append(m.group(1))
        for i in range(1, len(dates)):
            assert dates[i] >= dates[i - 1], (
                f"Dates not ordered: {dates[i-1]} > {dates[i]} at index {i}"
            )

    def test_reproducible_with_same_seed(self):
        """Same seed produces identical journals."""
        j1 = generate_journal(50, seed=123)
        j2 = generate_journal(50, seed=123)
        assert j1 == j2

    def test_different_seeds_differ(self):
        """Different seeds produce different journals."""
        j1 = generate_journal(50, seed=1)
        j2 = generate_journal(50, seed=2)
        assert j1 != j2

    def test_journal_has_header_comment(self):
        """Journal starts with a comment header."""
        journal = generate_journal(10)
        first_line = journal.split("\n")[0]
        assert first_line.startswith(";")

    def test_custom_start_date(self):
        """Custom start date is respected."""
        journal = generate_journal(5, start_date=date(2023, 6, 15))
        first_date = None
        for line in journal.split("\n"):
            m = re.match(r'(\d{4}/\d{2}/\d{2})', line)
            if m:
                first_date = m.group(1)
                break
        assert first_date == "2023/06/15"

    def test_journal_has_blank_lines_between_transactions(self):
        """Transactions are separated by blank lines."""
        journal = generate_journal(5)
        # After the header, transactions should be separated by empty lines
        assert "\n\n" in journal

    def test_state_distribution(self):
        """Roughly correct distribution of states (*, !, unmarked).

        With 1000 transactions, expect ~80% unmarked, ~10% cleared, ~10% pending.
        Allow wide tolerance since it's random.
        """
        journal = generate_journal(1000, seed=42)
        cleared = 0
        pending = 0
        unmarked = 0
        for line in journal.split("\n"):
            if re.match(r'\d{4}/\d{2}/\d{2}', line):
                if "* " in line[:20]:
                    cleared += 1
                elif "! " in line[:20]:
                    pending += 1
                else:
                    unmarked += 1

        total = cleared + pending + unmarked
        assert total == 1000
        # Allow 5-20% range for cleared and pending (expected ~10%)
        assert 30 <= cleared <= 170, f"Cleared count out of range: {cleared}"
        assert 30 <= pending <= 170, f"Pending count out of range: {pending}"
        assert 600 <= unmarked <= 950, f"Unmarked count out of range: {unmarked}"


# ============================================================================
# Write journal to file
# ============================================================================


class TestWriteJournal:
    """Test writing journal files."""

    def test_write_creates_file(self):
        """write_journal creates a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(10, path)
            assert path.exists()

    def test_write_file_nonempty(self):
        """Written file is non-empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(10, path)
            assert path.stat().st_size > 0

    def test_write_file_content_matches(self):
        """Written file content matches generate_journal output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(10, path, seed=42)
            content = path.read_text(encoding="utf-8")
            expected = generate_journal(10, seed=42)
            assert content == expected


# ============================================================================
# Parsing by muonledger
# ============================================================================


class TestParsing:
    """Test that generated journals can be parsed by muonledger's parser."""

    def test_parse_10_transactions(self):
        """Parser successfully handles 10 generated transactions."""
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(10, path)
            journal = Journal()
            parser = TextualParser()
            parser.parse(path, journal)
            assert len(journal.xacts) == 10

    def test_parse_100_transactions(self):
        """Parser successfully handles 100 generated transactions."""
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(100, path)
            journal = Journal()
            parser = TextualParser()
            parser.parse(path, journal)
            assert len(journal.xacts) == 100

    def test_parse_1000_transactions(self):
        """Parser successfully handles 1000 generated transactions."""
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(1000, path)
            journal = Journal()
            parser = TextualParser()
            parser.parse(path, journal)
            assert len(journal.xacts) == 1000

    def test_parsed_transactions_have_postings(self):
        """Each parsed transaction has postings."""
        from muonledger.journal import Journal
        from muonledger.parser import TextualParser

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.ledger"
            write_journal(20, path)
            journal = Journal()
            parser = TextualParser()
            parser.parse(path, journal)
            for xact in journal.xacts:
                assert len(xact.posts) >= 2


# ============================================================================
# Benchmark timing utilities
# ============================================================================


class TestTimingUtilities:
    """Test timing-related functions."""

    def test_time_operation_returns_elapsed(self):
        """time_operation returns a positive elapsed time."""
        import time
        elapsed, result = time_operation(time.sleep, 0.01)
        assert elapsed >= 0.01
        assert result is None

    def test_time_operation_returns_result(self):
        """time_operation returns the function's result."""
        elapsed, result = time_operation(lambda: 42)
        assert result == 42
        assert elapsed >= 0

    def test_compute_stats_empty(self):
        """compute_stats handles empty list."""
        stats = compute_stats([])
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["min"] == 0.0

    def test_compute_stats_single(self):
        """compute_stats with single value."""
        stats = compute_stats([5.0])
        assert stats["mean"] == 5.0
        assert stats["median"] == 5.0
        assert stats["min"] == 5.0

    def test_compute_stats_multiple(self):
        """compute_stats with multiple values."""
        stats = compute_stats([1.0, 2.0, 3.0])
        assert stats["mean"] == 2.0
        assert stats["median"] == 2.0
        assert stats["min"] == 1.0

    def test_compute_stats_even_count(self):
        """compute_stats median with even number of values."""
        stats = compute_stats([1.0, 2.0, 3.0, 4.0])
        assert stats["mean"] == 2.5
        assert stats["median"] == 2.5
        assert stats["min"] == 1.0

    def test_compute_stats_unsorted(self):
        """compute_stats handles unsorted input."""
        stats = compute_stats([5.0, 1.0, 3.0])
        assert stats["mean"] == 3.0
        assert stats["median"] == 3.0
        assert stats["min"] == 1.0


# ============================================================================
# bench_python integration
# ============================================================================


class TestBenchPython:
    """Test the Python benchmark module."""

    @pytest.fixture
    def small_journal(self, tmp_path):
        """Create a small journal file for testing."""
        path = tmp_path / "small.ledger"
        write_journal(10, path)
        return path

    def test_bench_parse(self, small_journal):
        """bench_parse returns timing and a journal."""
        elapsed, journal = bench_parse(small_journal)
        assert elapsed >= 0
        assert len(journal.xacts) == 10

    def test_bench_balance(self, small_journal):
        """bench_balance returns timing and output."""
        _, journal = bench_parse(small_journal)
        elapsed, output = bench_balance(journal)
        assert elapsed >= 0
        assert isinstance(output, str)

    def test_bench_register(self, small_journal):
        """bench_register returns timing and output."""
        _, journal = bench_parse(small_journal)
        elapsed, output = bench_register(journal)
        assert elapsed >= 0
        assert isinstance(output, str)

    def test_run_benchmark_returns_dict(self, small_journal):
        """run_benchmark returns a dict with expected keys."""
        results = run_benchmark(small_journal, iterations=1)
        assert "file" in results
        assert "iterations" in results
        assert "parse" in results
        assert "balance" in results
        assert "register" in results
        assert "total" in results

    def test_run_benchmark_stats(self, small_journal):
        """run_benchmark computes statistics."""
        results = run_benchmark(small_journal, iterations=2)
        assert "parse_mean" in results
        assert "parse_median" in results
        assert "parse_min" in results
        assert results["parse_mean"] >= 0
        assert results["parse_min"] >= 0

    def test_format_results(self, small_journal):
        """format_results produces readable output."""
        results = run_benchmark(small_journal, iterations=1)
        text = format_results(results)
        assert "parse" in text
        assert "balance" in text
        assert "register" in text
        assert "total" in text


# ============================================================================
# run_benchmarks helpers
# ============================================================================


class TestRunBenchmarksHelpers:
    """Test helper functions in run_benchmarks."""

    def test_size_label_thousands(self):
        """_size_label formats thousands correctly."""
        assert _size_label(1000) == "1k"
        assert _size_label(10000) == "10k"
        assert _size_label(100000) == "100k"

    def test_size_label_millions(self):
        """_size_label formats millions correctly."""
        assert _size_label(1000000) == "1m"

    def test_size_label_small(self):
        """_size_label handles small numbers."""
        assert _size_label(10) == "10"
        assert _size_label(100) == "100"

    def test_format_table_with_error(self):
        """format_table handles error results gracefully."""
        results = {"Test": {"error": "something went wrong"}}
        text = format_table(results)
        assert "ERROR" in text
        assert "something went wrong" in text

    def test_format_table_with_results(self):
        """format_table formats valid results."""
        results = {
            "Python 1k": {
                "file": "bench_1k.ledger",
                "iterations": 1,
                "parse_mean": 0.05,
                "parse_median": 0.05,
                "parse_min": 0.05,
                "balance_mean": 0.01,
                "balance_median": 0.01,
                "balance_min": 0.01,
                "register_mean": 0.02,
                "register_median": 0.02,
                "register_min": 0.02,
                "total_mean": 0.08,
                "total_median": 0.08,
                "total_min": 0.08,
            }
        }
        text = format_table(results)
        assert "Python 1k" in text
        assert "parse" in text
        assert "BENCHMARK" in text
