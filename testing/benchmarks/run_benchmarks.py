#!/usr/bin/env python3
"""Benchmark harness for muonledger CLI commands.

Runs ledger commands against a journal file, collecting wall-clock timing
and optional peak-memory statistics over multiple iterations.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

COMMANDS = ("balance", "register", "print")


@dataclass(slots=True)
class BenchmarkResult:
    """Collected timing and memory data for a single command."""

    command: str
    times: list[float] = field(default_factory=list)
    peak_memory_kb: int | None = None

    @property
    def min(self) -> float:
        return min(self.times)

    @property
    def max(self) -> float:
        return max(self.times)

    @property
    def mean(self) -> float:
        return statistics.mean(self.times)

    @property
    def median(self) -> float:
        return statistics.median(self.times)

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "runs": len(self.times),
            "min_s": round(self.min, 6),
            "max_s": round(self.max, 6),
            "mean_s": round(self.mean, 6),
            "median_s": round(self.median, 6),
            "peak_memory_kb": self.peak_memory_kb,
        }


def _run_once(
    binary: Path,
    journal: Path,
    command: str,
    *,
    measure_memory: bool = False,
) -> tuple[float, int | None]:
    """Execute *command* once and return (elapsed_seconds, peak_rss_kb | None)."""

    args = [str(binary), "-f", str(journal), command]

    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN) if measure_memory else None

    start = time.perf_counter()
    proc = subprocess.run(args, capture_output=True, check=False)
    elapsed = time.perf_counter() - start

    if proc.returncode != 0:
        print(
            f"WARNING: '{' '.join(args)}' exited with code {proc.returncode}",
            file=sys.stderr,
        )

    peak_kb: int | None = None
    if measure_memory and usage_before is not None:
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        # ru_maxrss is in bytes on macOS, kilobytes on Linux.
        peak_kb = usage_after.ru_maxrss
        if sys.platform == "darwin":
            peak_kb //= 1024  # normalise to KB

    return elapsed, peak_kb


def run_benchmark(
    binary: Path,
    journal: Path,
    command: str,
    *,
    runs: int = 5,
    warmup: int = 1,
    measure_memory: bool = False,
) -> BenchmarkResult:
    """Benchmark a single *command* with warmup and measured iterations."""

    result = BenchmarkResult(command=command)

    # Warmup iterations (discarded).
    for _ in range(warmup):
        _run_once(binary, journal, command)

    # Timed iterations.
    for _ in range(runs):
        elapsed, peak_kb = _run_once(
            binary, journal, command, measure_memory=measure_memory
        )
        result.times.append(elapsed)
        if peak_kb is not None:
            # Keep the maximum observed peak across all runs.
            if result.peak_memory_kb is None or peak_kb > result.peak_memory_kb:
                result.peak_memory_kb = peak_kb

    return result


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _print_table(results: list[BenchmarkResult], out: TextIO = sys.stdout) -> None:
    """Pretty-print results as a fixed-width table."""

    header = f"{'Command':<12} {'Min (s)':>10} {'Max (s)':>10} {'Mean (s)':>10} {'Median (s)':>10} {'Peak Mem (KB)':>14}"
    sep = "-" * len(header)

    print(sep, file=out)
    print(header, file=out)
    print(sep, file=out)
    for r in results:
        mem = str(r.peak_memory_kb) if r.peak_memory_kb is not None else "n/a"
        print(
            f"{r.command:<12} {r.min:>10.6f} {r.max:>10.6f} "
            f"{r.mean:>10.6f} {r.median:>10.6f} {mem:>14}",
            file=out,
        )
    print(sep, file=out)


def _write_json(results: list[BenchmarkResult], path: Path) -> None:
    payload = [r.as_dict() for r in results]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"JSON results written to {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run wall-clock benchmarks for muonledger commands.",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        required=True,
        help="Path to the ledger binary to benchmark.",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        required=True,
        help="Path to the journal file to use.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of timed iterations per command (default: 5).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup iterations per command (default: 1).",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        default=False,
        help="Measure peak RSS via the resource module.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write results as JSON to the given file.",
    )
    parser.add_argument(
        "--commands",
        nargs="+",
        default=list(COMMANDS),
        help=f"Commands to benchmark (default: {' '.join(COMMANDS)}).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.binary.exists():
        parser.error(f"binary not found: {args.binary}")
    if not args.journal.exists():
        parser.error(f"journal not found: {args.journal}")

    print(
        f"Benchmarking {args.binary} with {args.journal} "
        f"({args.runs} runs, {args.warmup} warmup)\n",
        file=sys.stderr,
    )

    results: list[BenchmarkResult] = []
    for cmd in args.commands:
        print(f"  Running: {cmd} ...", file=sys.stderr, flush=True)
        result = run_benchmark(
            args.binary,
            args.journal,
            cmd,
            runs=args.runs,
            warmup=args.warmup,
            measure_memory=args.memory,
        )
        results.append(result)

    print(file=sys.stderr)
    _print_table(results)

    if args.output_json is not None:
        _write_json(results, args.output_json)


if __name__ == "__main__":
    main()
