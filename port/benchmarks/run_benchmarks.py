#!/usr/bin/env python3
"""Main benchmark runner: test both Python and Rust implementations.

Generates journals of varying sizes, runs each implementation against them,
and produces a comparative timing report.

Usage:
    python run_benchmarks.py
    python run_benchmarks.py --sizes 1000 10000 --iterations 3
    python run_benchmarks.py --python-only
    python run_benchmarks.py --rust-only
    python run_benchmarks.py --json --output results.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from generate_journal import generate_journal, write_journal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SIZES = [1_000, 10_000, 100_000]
DEFAULT_ITERATIONS = 3
SEED = 42

BENCHMARKS_DIR = Path(__file__).parent.resolve()
PYTHON_DIR = BENCHMARKS_DIR.parent / "python"
RUST_DIR = BENCHMARKS_DIR.parent / "rust"


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def compute_stats(times: list[float]) -> dict[str, float]:
    """Compute mean, median, and min from a list of times."""
    if not times:
        return {"mean": 0.0, "median": 0.0, "min": 0.0}
    mean = sum(times) / len(times)
    minimum = min(times)
    sorted_times = sorted(times)
    mid = len(sorted_times) // 2
    if len(sorted_times) % 2 == 0:
        median = (sorted_times[mid - 1] + sorted_times[mid]) / 2
    else:
        median = sorted_times[mid]
    return {"mean": mean, "median": median, "min": minimum}


# ---------------------------------------------------------------------------
# Python benchmarks
# ---------------------------------------------------------------------------

def run_python_benchmark(
    journal_path: Path,
    iterations: int,
) -> dict[str, Any]:
    """Run Python benchmark by importing muonledger directly."""
    # We run bench_python.py as a subprocess to get clean imports each time
    bench_script = BENCHMARKS_DIR / "bench_python.py"
    cmd = [
        sys.executable, str(bench_script),
        "--file", str(journal_path),
        "--iterations", str(iterations),
        "--json",
    ]

    env = os.environ.copy()
    # Ensure muonledger is importable
    python_src = PYTHON_DIR / "src"
    if python_src.exists():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{python_src}:{existing}" if existing else str(python_src)

    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=600,
    )

    if result.returncode != 0:
        return {
            "error": result.stderr.strip() or "Python benchmark failed",
            "returncode": result.returncode,
        }

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON output: {result.stdout[:200]}"}


# ---------------------------------------------------------------------------
# Rust benchmarks
# ---------------------------------------------------------------------------

def build_rust(release: bool = True) -> bool:
    """Build the Rust implementation. Returns True on success."""
    if not RUST_DIR.exists():
        return False

    cargo_toml = RUST_DIR / "Cargo.toml"
    if not cargo_toml.exists():
        return False

    cmd = ["cargo", "build"]
    if release:
        cmd.append("--release")

    result = subprocess.run(
        cmd, cwd=str(RUST_DIR), capture_output=True, text=True, timeout=300,
    )
    return result.returncode == 0


def find_rust_binary() -> Path | None:
    """Find the built Rust binary."""
    for name in ("muonledger", "muonledger.exe"):
        path = RUST_DIR / "target" / "release" / name
        if path.exists():
            return path
    # Try debug build
    for name in ("muonledger", "muonledger.exe"):
        path = RUST_DIR / "target" / "debug" / name
        if path.exists():
            return path
    return None


def run_rust_command(
    binary: Path,
    journal_path: Path,
    command: str,
) -> tuple[float, str, str]:
    """Run a Rust muonledger command and return (elapsed, stdout, stderr)."""
    cmd = [str(binary), "-f", str(journal_path), command]
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.perf_counter() - start
    return elapsed, result.stdout, result.stderr


def run_rust_benchmark(
    journal_path: Path,
    iterations: int,
    binary: Path | None = None,
) -> dict[str, Any]:
    """Run Rust benchmark using the compiled binary."""
    if binary is None:
        binary = find_rust_binary()
    if binary is None:
        return {"error": "Rust binary not found. Run 'cargo build --release' first."}

    results: dict[str, Any] = {
        "file": str(journal_path),
        "iterations": iterations,
        "parse": [],
        "balance": [],
        "register": [],
        "total": [],
    }

    for _ in range(iterations):
        total_start = time.perf_counter()

        # Parse + balance
        bal_elapsed, _, stderr = run_rust_command(binary, journal_path, "balance")
        results["balance"].append(bal_elapsed)

        # Parse + register
        reg_elapsed, _, stderr = run_rust_command(binary, journal_path, "register")
        results["register"].append(reg_elapsed)

        # For Rust, parse time is embedded in command time; approximate
        # by running balance (which includes parse) as the "total" proxy
        # Parse-only isn't directly measurable via CLI, so we record 0
        results["parse"].append(0.0)

        total_elapsed = time.perf_counter() - total_start
        results["total"].append(total_elapsed)

    # Compute stats
    for key in ("parse", "balance", "register", "total"):
        stats = compute_stats(results[key])
        results[f"{key}_mean"] = stats["mean"]
        results[f"{key}_median"] = stats["median"]
        results[f"{key}_min"] = stats["min"]

    return results


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_table(all_results: dict[str, dict]) -> str:
    """Format all results as an aligned table."""
    lines = []
    lines.append("=" * 78)
    lines.append("MUONLEDGER BENCHMARK RESULTS")
    lines.append("=" * 78)
    lines.append("")

    for label, results in all_results.items():
        lines.append(f"--- {label} ---")
        if "error" in results:
            lines.append(f"  ERROR: {results['error']}")
            lines.append("")
            continue

        lines.append(f"  File: {results.get('file', 'N/A')}")
        lines.append(f"  Iterations: {results.get('iterations', 'N/A')}")
        lines.append("")
        lines.append(f"  {'Operation':<12} {'Mean':>10} {'Median':>10} {'Min':>10}")
        lines.append(f"  {'-' * 44}")

        for key in ("parse", "balance", "register", "total"):
            mean = results.get(f"{key}_mean", 0.0)
            median = results.get(f"{key}_median", 0.0)
            minimum = results.get(f"{key}_min", 0.0)
            lines.append(
                f"  {key:<12} {mean:>10.4f}s {median:>10.4f}s {minimum:>10.4f}s"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_benchmarks(
    sizes: list[int],
    iterations: int,
    run_python: bool = True,
    run_rust: bool = True,
    journal_dir: Path | None = None,
    seed: int = SEED,
) -> dict[str, dict]:
    """Run benchmarks for all sizes and implementations.

    Returns a dict keyed by label (e.g. "Python 1K", "Rust 10K").
    """
    if journal_dir is None:
        journal_dir = Path(tempfile.mkdtemp(prefix="muonbench_"))
        cleanup = True
    else:
        journal_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False

    all_results: dict[str, dict] = {}
    rust_binary = None

    if run_rust:
        print("Building Rust implementation...")
        if build_rust(release=True):
            rust_binary = find_rust_binary()
            if rust_binary:
                print(f"  Rust binary: {rust_binary}")
            else:
                print("  WARNING: Build succeeded but binary not found")
        else:
            print("  WARNING: Rust build failed, skipping Rust benchmarks")
            run_rust = False

    for size in sizes:
        label = _size_label(size)
        journal_path = journal_dir / f"bench_{label}.ledger"

        if not journal_path.exists():
            print(f"Generating {label} journal ({size:,} transactions)...")
            write_journal(size, journal_path, seed=seed)

        if run_python:
            print(f"Running Python benchmark: {label}...")
            result = run_python_benchmark(journal_path, iterations)
            all_results[f"Python {label}"] = result

        if run_rust and rust_binary:
            print(f"Running Rust benchmark: {label}...")
            result = run_rust_benchmark(journal_path, iterations, rust_binary)
            all_results[f"Rust {label}"] = result

    if cleanup:
        shutil.rmtree(journal_dir, ignore_errors=True)

    return all_results


def _size_label(count: int) -> str:
    """Convert a count to a human-readable label (e.g. 1000 -> '1k')."""
    if count >= 1_000_000:
        return f"{count // 1_000_000}m"
    elif count >= 1_000:
        return f"{count // 1_000}k"
    else:
        return str(count)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run muonledger benchmarks for Python and Rust implementations."
    )
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=DEFAULT_SIZES,
        help=f"Transaction counts to benchmark (default: {DEFAULT_SIZES})",
    )
    parser.add_argument(
        "--iterations", "-n", type=int, default=DEFAULT_ITERATIONS,
        help=f"Iterations per benchmark (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--python-only", action="store_true",
        help="Only benchmark Python implementation",
    )
    parser.add_argument(
        "--rust-only", action="store_true",
        help="Only benchmark Rust implementation",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write results to file instead of stdout",
    )
    parser.add_argument(
        "--journal-dir", type=str, default=None,
        help="Directory to store/reuse generated journals",
    )
    parser.add_argument(
        "--seed", type=int, default=SEED,
        help=f"Random seed (default: {SEED})",
    )

    args = parser.parse_args(argv)

    run_python = not args.rust_only
    run_rust = not args.python_only

    journal_dir = Path(args.journal_dir) if args.journal_dir else None

    all_results = run_all_benchmarks(
        sizes=args.sizes,
        iterations=args.iterations,
        run_python=run_python,
        run_rust=run_rust,
        journal_dir=journal_dir,
        seed=args.seed,
    )

    if args.json:
        output = json.dumps(all_results, indent=2)
    else:
        output = format_table(all_results)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
