#!/usr/bin/env python3
"""Python-specific benchmark: time journal parsing, balance, and register.

Imports muonledger modules directly and returns structured timing data.

Usage:
    python bench_python.py --file bench_1k.ledger --iterations 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def time_operation(func, *args, **kwargs) -> tuple[float, Any]:
    """Time a single operation. Returns (elapsed_seconds, result)."""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start
    return elapsed, result


def bench_parse(journal_path: Path):
    """Parse a journal file and return (elapsed, journal)."""
    from muonledger.journal import Journal
    from muonledger.parser import TextualParser

    journal = Journal()
    parser = TextualParser()

    start = time.perf_counter()
    parser.parse(journal_path, journal)
    elapsed = time.perf_counter() - start

    return elapsed, journal


def bench_balance(journal) -> tuple[float, str]:
    """Run balance command on a parsed journal. Returns (elapsed, output)."""
    from muonledger.commands.balance import balance_command

    start = time.perf_counter()
    output = balance_command(journal, [])
    elapsed = time.perf_counter() - start

    return elapsed, output or ""


def bench_register(journal) -> tuple[float, str]:
    """Run register command on a parsed journal. Returns (elapsed, output)."""
    from muonledger.commands.register import register_command

    start = time.perf_counter()
    output = register_command(journal, [])
    elapsed = time.perf_counter() - start

    return elapsed, output or ""


def run_benchmark(
    journal_path: Path,
    iterations: int = 3,
) -> dict[str, Any]:
    """Run the full benchmark suite on a single journal file.

    Returns a dict with timing data for each operation across all iterations.
    """
    results: dict[str, Any] = {
        "file": str(journal_path),
        "iterations": iterations,
        "parse": [],
        "balance": [],
        "register": [],
        "total": [],
    }

    for i in range(iterations):
        total_start = time.perf_counter()

        # Parse
        parse_time, journal = bench_parse(journal_path)
        results["parse"].append(parse_time)

        # Balance
        bal_time, _ = bench_balance(journal)
        results["balance"].append(bal_time)

        # Register
        reg_time, _ = bench_register(journal)
        results["register"].append(reg_time)

        total_elapsed = time.perf_counter() - total_start
        results["total"].append(total_elapsed)

    # Compute statistics
    for key in ("parse", "balance", "register", "total"):
        times = results[key]
        results[f"{key}_mean"] = sum(times) / len(times)
        results[f"{key}_min"] = min(times)
        sorted_times = sorted(times)
        mid = len(sorted_times) // 2
        if len(sorted_times) % 2 == 0:
            results[f"{key}_median"] = (sorted_times[mid - 1] + sorted_times[mid]) / 2
        else:
            results[f"{key}_median"] = sorted_times[mid]

    return results


def format_results(results: dict[str, Any]) -> str:
    """Format benchmark results as a human-readable string."""
    lines = []
    lines.append(f"File: {results['file']}")
    lines.append(f"Iterations: {results['iterations']}")
    lines.append("")
    lines.append(f"{'Operation':<12} {'Mean':>10} {'Median':>10} {'Min':>10}")
    lines.append("-" * 44)
    for key in ("parse", "balance", "register", "total"):
        mean = results[f"{key}_mean"]
        median = results[f"{key}_median"]
        minimum = results[f"{key}_min"]
        lines.append(f"{key:<12} {mean:>10.4f}s {median:>10.4f}s {minimum:>10.4f}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Python muonledger implementation."
    )
    parser.add_argument(
        "--file", "-f", required=True,
        help="Path to journal file to benchmark",
    )
    parser.add_argument(
        "--iterations", "-n", type=int, default=3,
        help="Number of iterations (default: 3)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args(argv)
    journal_path = Path(args.file)

    if not journal_path.exists():
        print(f"Error: file not found: {journal_path}", file=sys.stderr)
        return 1

    results = run_benchmark(journal_path, iterations=args.iterations)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_results(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
