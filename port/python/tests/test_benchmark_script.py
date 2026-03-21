"""Tests for the cross-implementation benchmark script.

Covers journal generation, timing utilities, statistics, report format,
historical comparison, implementation discovery, CLI parsing, table formatting,
and edge cases.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Add the scripts directory to the path so we can import benchmark
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import benchmark  # noqa: E402


# ===========================================================================
# Statistics computation tests
# ===========================================================================


class TestComputeStats:
    """Tests for compute_stats function."""

    def test_basic_stats(self):
        timings = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = benchmark.compute_stats(timings)
        assert stats["mean"] == 3.0
        assert stats["median"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0

    def test_single_value(self):
        stats = benchmark.compute_stats([0.42])
        assert stats["mean"] == 0.42
        assert stats["median"] == 0.42
        assert stats["min"] == 0.42
        assert stats["max"] == 0.42

    def test_two_values(self):
        stats = benchmark.compute_stats([0.1, 0.3])
        assert stats["mean"] == 0.2
        assert stats["median"] == 0.2
        assert stats["min"] == 0.1
        assert stats["max"] == 0.3

    def test_empty_list(self):
        stats = benchmark.compute_stats([])
        assert stats["mean"] == 0.0
        assert stats["median"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0

    def test_identical_values(self):
        stats = benchmark.compute_stats([0.5, 0.5, 0.5])
        assert stats["mean"] == 0.5
        assert stats["median"] == 0.5
        assert stats["min"] == 0.5
        assert stats["max"] == 0.5

    def test_rounding(self):
        stats = benchmark.compute_stats([0.1234567, 0.2345678])
        # Should be rounded to 6 decimal places
        assert len(str(stats["mean"]).split(".")[-1]) <= 6


# ===========================================================================
# System information tests
# ===========================================================================


class TestSystemInfo:
    """Tests for gather_system_info."""

    def test_returns_dict(self):
        info = benchmark.gather_system_info()
        assert isinstance(info, dict)

    def test_has_required_keys(self):
        info = benchmark.gather_system_info()
        assert "os" in info
        assert "cpu" in info
        assert "python" in info

    def test_python_version(self):
        info = benchmark.gather_system_info()
        assert info["python"] == platform.python_version()


# ===========================================================================
# Implementation discovery tests
# ===========================================================================


class TestDiscoverImplementations:
    """Tests for discover_implementations."""

    def test_returns_dict(self):
        available = benchmark.discover_implementations()
        assert isinstance(available, dict)

    def test_python_available(self):
        available = benchmark.discover_implementations()
        # Python should be available since we're in the project
        assert "python" in available
        assert available["python"] is True

    def test_rust_key_present(self):
        available = benchmark.discover_implementations()
        assert "rust" in available

    def test_cpp_key_present(self):
        available = benchmark.discover_implementations()
        assert "cpp" in available


# ===========================================================================
# Journal generation tests
# ===========================================================================


class TestJournalGeneration:
    """Tests for journal file generation."""

    def test_generate_small_journal(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = benchmark.generate_journal_file(10, tmpdir)
            assert os.path.exists(path)
            with open(path, "r") as f:
                content = f.read()
            assert len(content) > 0
            assert "Synthetic benchmark journal" in content
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_journal_correct_name(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = benchmark.generate_journal_file(50, tmpdir)
            assert path.endswith("bench_50.ledger")
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_journal_deterministic(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path1 = benchmark.generate_journal_file(10, tmpdir)
            with open(path1) as f:
                content1 = f.read()
            # Regenerate with same seed
            path2 = benchmark.generate_journal_file(10, tmpdir)
            with open(path2) as f:
                content2 = f.read()
            assert content1 == content2
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_different_sizes(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path10 = benchmark.generate_journal_file(10, tmpdir)
            path100 = benchmark.generate_journal_file(100, tmpdir)
            size10 = os.path.getsize(path10)
            size100 = os.path.getsize(path100)
            assert size100 > size10
        finally:
            shutil.rmtree(tmpdir)


# ===========================================================================
# Timing measurement tests
# ===========================================================================


class TestTimingMeasurement:
    """Tests for time_external_command."""

    def test_successful_command(self):
        timings = benchmark.time_external_command(
            [sys.executable, "-c", "pass"], iterations=2
        )
        assert len(timings) == 2
        assert all(t > 0 for t in timings)

    def test_failed_command_excluded(self):
        timings = benchmark.time_external_command(
            [sys.executable, "-c", "import sys; sys.exit(1)"], iterations=3
        )
        # Failed commands should not be recorded
        assert len(timings) == 0

    def test_single_iteration(self):
        timings = benchmark.time_external_command(
            [sys.executable, "-c", "pass"], iterations=1
        )
        assert len(timings) == 1

    def test_timing_reasonable(self):
        timings = benchmark.time_external_command(
            [sys.executable, "-c", "import time; time.sleep(0.05)"],
            iterations=1,
        )
        assert len(timings) == 1
        # Should take at least 0.05s
        assert timings[0] >= 0.04


# ===========================================================================
# Report JSON format tests
# ===========================================================================


class TestReportFormat:
    """Tests for report JSON format and saving."""

    def test_save_report_creates_file(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = {
                "timestamp": "2026-03-21T16:30:00",
                "system": {"os": "test", "cpu": "test", "python": "3.12"},
                "results": {},
            }
            path = benchmark.save_report(report, tmpdir)
            assert path.exists()
            assert path.suffix == ".json"
        finally:
            shutil.rmtree(tmpdir)

    def test_save_report_valid_json(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = {
                "timestamp": "2026-03-21T16:30:00",
                "system": {"os": "test", "cpu": "test", "python": "3.12"},
                "results": {
                    "python": {
                        "1000": {
                            "parse": {"mean": 0.05, "median": 0.04, "min": 0.03, "max": 0.07}
                        }
                    }
                },
            }
            path = benchmark.save_report(report, tmpdir)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["timestamp"] == "2026-03-21T16:30:00"
            assert "results" in loaded
            assert "python" in loaded["results"]
        finally:
            shutil.rmtree(tmpdir)

    def test_save_report_filename_format(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = {"timestamp": "2026-03-21T16:30:00", "system": {}, "results": {}}
            path = benchmark.save_report(report, tmpdir)
            assert path.name.startswith("benchmark_")
            assert path.name.endswith(".json")
        finally:
            shutil.rmtree(tmpdir)

    def test_save_report_creates_directory(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            output_dir = tmpdir / "subdir" / "benchmarks"
            report = {"timestamp": "2026-03-21T16:30:00", "system": {}, "results": {}}
            path = benchmark.save_report(report, output_dir)
            assert path.exists()
        finally:
            shutil.rmtree(tmpdir)


# ===========================================================================
# Historical comparison tests
# ===========================================================================


class TestHistoricalComparison:
    """Tests for comparison logic."""

    def test_find_latest_report_empty_dir(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            result = benchmark.find_latest_report(tmpdir)
            assert result is None
        finally:
            shutil.rmtree(tmpdir)

    def test_find_latest_report_nonexistent_dir(self):
        result = benchmark.find_latest_report(Path("/nonexistent/dir"))
        assert result is None

    def test_find_latest_report_with_reports(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            (tmpdir / "benchmark_2026-03-20T100000.json").write_text("{}")
            (tmpdir / "benchmark_2026-03-21T100000.json").write_text("{}")
            result = benchmark.find_latest_report(tmpdir)
            assert result is not None
            assert "2026-03-21" in result.name
        finally:
            shutil.rmtree(tmpdir)

    def test_find_previous_report_excludes_current(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            prev = tmpdir / "benchmark_2026-03-20T100000.json"
            curr = tmpdir / "benchmark_2026-03-21T100000.json"
            prev.write_text("{}")
            curr.write_text("{}")
            result = benchmark.find_previous_report(tmpdir, curr)
            assert result == prev
        finally:
            shutil.rmtree(tmpdir)

    def test_find_previous_report_no_previous(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            curr = tmpdir / "benchmark_2026-03-21T100000.json"
            curr.write_text("{}")
            result = benchmark.find_previous_report(tmpdir, curr)
            assert result is None
        finally:
            shutil.rmtree(tmpdir)

    def test_comparison_delta_improvement(self):
        current = {
            "timestamp": "2026-03-21T17:00:00",
            "results": {
                "python": {
                    "1000": {
                        "parse": {"mean": 0.04, "median": 0.04, "min": 0.03, "max": 0.05},
                    }
                }
            },
        }
        previous = {
            "timestamp": "2026-03-20T17:00:00",
            "results": {
                "python": {
                    "1000": {
                        "parse": {"mean": 0.05, "median": 0.05, "min": 0.04, "max": 0.06},
                    }
                }
            },
        }
        output = benchmark.format_comparison(current, previous)
        assert "python" in output
        assert "parse" in output
        assert "1K" in output
        # Should show negative percentage (improvement)
        assert "-20.0%" in output

    def test_comparison_delta_regression(self):
        current = {
            "timestamp": "2026-03-21T17:00:00",
            "results": {
                "python": {
                    "1000": {
                        "balance": {"mean": 0.10, "median": 0.10, "min": 0.09, "max": 0.11},
                    }
                }
            },
        }
        previous = {
            "timestamp": "2026-03-20T17:00:00",
            "results": {
                "python": {
                    "1000": {
                        "balance": {"mean": 0.05, "median": 0.05, "min": 0.04, "max": 0.06},
                    }
                }
            },
        }
        output = benchmark.format_comparison(current, previous)
        assert "+100.0%" in output

    def test_comparison_with_missing_impl(self):
        current = {
            "timestamp": "2026-03-21T17:00:00",
            "results": {
                "python": {
                    "1000": {"parse": {"mean": 0.04}},
                }
            },
        }
        previous = {
            "timestamp": "2026-03-20T17:00:00",
            "results": {
                "rust": {
                    "1000": {"parse": {"mean": 0.01}},
                }
            },
        }
        # Should not crash
        output = benchmark.format_comparison(current, previous)
        assert "COMPARISON" in output


# ===========================================================================
# Table formatting tests
# ===========================================================================


class TestTableFormatting:
    """Tests for format_table."""

    def test_basic_table(self):
        results = {
            "python": {
                "1000": {
                    "parse": {"mean": 0.05, "median": 0.04, "min": 0.03, "max": 0.07},
                    "balance": {"mean": 0.06, "median": 0.05, "min": 0.04, "max": 0.08},
                    "register": {"mean": 0.07, "median": 0.06, "min": 0.05, "max": 0.09},
                }
            }
        }
        table = benchmark.format_table(results)
        assert "PARSE" in table
        assert "BALANCE" in table
        assert "REGISTER" in table
        assert "python" in table
        assert "1K" in table

    def test_table_multiple_impls(self):
        results = {
            "python": {
                "1000": {
                    "parse": {"mean": 0.05},
                    "balance": {"mean": 0.06},
                    "register": {"mean": 0.07},
                }
            },
            "rust": {
                "1000": {
                    "parse": {"mean": 0.01},
                    "balance": {"mean": 0.02},
                    "register": {"mean": 0.03},
                }
            },
        }
        table = benchmark.format_table(results)
        assert "python" in table
        assert "rust" in table

    def test_table_multiple_sizes(self):
        results = {
            "python": {
                "1000": {"parse": {"mean": 0.05}, "balance": {"mean": 0.06}, "register": {"mean": 0.07}},
                "10000": {"parse": {"mean": 0.5}, "balance": {"mean": 0.6}, "register": {"mean": 0.7}},
            }
        }
        table = benchmark.format_table(results)
        assert "1K" in table
        assert "10K" in table

    def test_table_na_for_missing(self):
        results = {
            "python": {
                "1000": {"parse": {"mean": 0.0}, "balance": {"mean": 0.06}, "register": {"mean": 0.07}},
            }
        }
        table = benchmark.format_table(results)
        assert "N/A" in table


class TestFormatSize:
    """Tests for _format_size helper."""

    def test_thousands(self):
        assert benchmark._format_size("1000") == "1K"
        assert benchmark._format_size("10000") == "10K"
        assert benchmark._format_size("100000") == "100K"

    def test_millions(self):
        assert benchmark._format_size("1000000") == "1M"

    def test_small(self):
        assert benchmark._format_size("100") == "100"
        assert benchmark._format_size("10") == "10"


# ===========================================================================
# CLI argument parsing tests
# ===========================================================================


class TestCLIParsing:
    """Tests for parse_args."""

    def test_default_args(self):
        args = benchmark.parse_args([])
        assert args.iterations == benchmark.DEFAULT_ITERATIONS
        assert args.compare is False
        assert args.json_output is False

    def test_custom_sizes(self):
        args = benchmark.parse_args(["--sizes", "100,500,1000"])
        assert args.sizes == "100,500,1000"

    def test_custom_iterations(self):
        args = benchmark.parse_args(["--iterations", "3"])
        assert args.iterations == 3

    def test_implementations_flag(self):
        args = benchmark.parse_args(["--implementations", "python,rust"])
        assert args.implementations == "python,rust"

    def test_compare_flag(self):
        args = benchmark.parse_args(["--compare"])
        assert args.compare is True

    def test_json_flag(self):
        args = benchmark.parse_args(["--json"])
        assert args.json_output is True

    def test_output_dir(self):
        args = benchmark.parse_args(["--output-dir", "/tmp/bench"])
        assert args.output_dir == "/tmp/bench"


# ===========================================================================
# Color support tests
# ===========================================================================


class TestColorSupport:
    """Tests for color utilities."""

    def test_colorize_no_color_env(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            result = benchmark.colorize("test", "green")
            assert result == "test"
            assert "\033" not in result

    def test_colorize_returns_string(self):
        result = benchmark.colorize("hello", "bold")
        assert isinstance(result, str)
        assert "hello" in result


# ===========================================================================
# Load report tests
# ===========================================================================


class TestLoadReport:
    """Tests for load_report."""

    def test_load_valid_report(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report_data = {
                "timestamp": "2026-03-21T16:30:00",
                "system": {"os": "test"},
                "results": {"python": {}},
            }
            path = tmpdir / "test_report.json"
            path.write_text(json.dumps(report_data))
            loaded = benchmark.load_report(path)
            assert loaded["timestamp"] == "2026-03-21T16:30:00"
        finally:
            shutil.rmtree(tmpdir)


# ===========================================================================
# Integration tests (small scale)
# ===========================================================================


class TestSmallBenchmark:
    """Integration tests with very small journal sizes."""

    def test_run_tiny_benchmark_python(self):
        """Run an actual benchmark with 10 transactions."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = benchmark.run_benchmarks(
                sizes=[10],
                iterations=1,
                implementations=["python"],
                output_dir=tmpdir,
                json_output=True,
            )
            assert "timestamp" in report
            assert "system" in report
            assert "results" in report
            # If python is available, it should have results
            if "python" in report["results"]:
                py_results = report["results"]["python"]
                assert "10" in py_results
                assert "parse" in py_results["10"]
                assert "balance" in py_results["10"]
                assert "register" in py_results["10"]
        finally:
            shutil.rmtree(tmpdir)

    def test_run_benchmark_saves_report(self):
        """Verify the report JSON file is saved."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            benchmark.run_benchmarks(
                sizes=[10],
                iterations=1,
                implementations=["python"],
                output_dir=tmpdir,
                json_output=True,
            )
            reports = list(tmpdir.glob("benchmark_*.json"))
            assert len(reports) >= 1
            # Validate JSON
            with open(reports[0]) as f:
                data = json.load(f)
            assert "timestamp" in data
            assert "results" in data
        finally:
            shutil.rmtree(tmpdir)

    def test_run_benchmark_nonexistent_impl(self):
        """Requesting a non-existent implementation should skip it."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = benchmark.run_benchmarks(
                sizes=[10],
                iterations=1,
                implementations=["nonexistent_impl"],
                output_dir=tmpdir,
                json_output=True,
            )
            assert report["results"] == {}
        finally:
            shutil.rmtree(tmpdir)

    def test_run_benchmark_multiple_sizes(self):
        """Run with multiple small sizes."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = benchmark.run_benchmarks(
                sizes=[10, 50],
                iterations=1,
                implementations=["python"],
                output_dir=tmpdir,
                json_output=True,
            )
            if "python" in report["results"]:
                assert "10" in report["results"]["python"]
                assert "50" in report["results"]["python"]
        finally:
            shutil.rmtree(tmpdir)

    def test_report_stats_have_all_keys(self):
        """Verify stats dicts have mean, median, min, max."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            report = benchmark.run_benchmarks(
                sizes=[10],
                iterations=2,
                implementations=["python"],
                output_dir=tmpdir,
                json_output=True,
            )
            if "python" in report["results"]:
                parse_stats = report["results"]["python"]["10"]["parse"]
                for key in ["mean", "median", "min", "max"]:
                    assert key in parse_stats, f"Missing key: {key}"
        finally:
            shutil.rmtree(tmpdir)


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_single_iteration_stats(self):
        """Single iteration should still produce valid stats."""
        stats = benchmark.compute_stats([0.123])
        assert stats["mean"] == stats["median"] == stats["min"] == stats["max"]

    def test_no_previous_report_for_comparison(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            assert benchmark.find_previous_report(tmpdir, tmpdir / "x.json") is None
        finally:
            shutil.rmtree(tmpdir)

    def test_format_comparison_empty_results(self):
        current = {"timestamp": "2026-03-21T17:00:00", "results": {}}
        previous = {"timestamp": "2026-03-20T17:00:00", "results": {}}
        output = benchmark.format_comparison(current, previous)
        assert "COMPARISON" in output

    def test_format_table_empty_results(self):
        table = benchmark.format_table({})
        # Should not crash, may have headers but no data rows
        assert isinstance(table, str)

    def test_build_rust_failure_handled(self):
        """build_rust should return False if cargo is not found."""
        with patch("benchmark.subprocess.run", side_effect=FileNotFoundError):
            result = benchmark.build_rust()
            assert result is False

    def test_get_rust_binary_not_found(self):
        result = benchmark.get_rust_binary()
        # May or may not exist depending on build state, just check type
        assert result is None or isinstance(result, str)
