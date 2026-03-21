#!/usr/bin/env python3
"""Cross-implementation benchmark script with timestamped reports.

Measures performance across all available muonledger implementations
(Python, Rust, C++ ledger) and produces comparison tables and JSON reports.

Usage:
    python port/scripts/benchmark.py
    python port/scripts/benchmark.py --sizes 1000,10000 --iterations 3
    python port/scripts/benchmark.py --compare
    python port/scripts/benchmark.py --implementations python,rust
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve project root and import journal generator
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # port/
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"

# Add benchmarks dir to path so we can import generate_journal
sys.path.insert(0, str(BENCHMARKS_DIR))
from generate_journal import generate_journal  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SIZES = [1_000, 10_000, 100_000]
DEFAULT_ITERATIONS = 5
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "benchmarks"
OPERATIONS = ["parse", "balance", "register"]


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def compute_stats(timings: list[float]) -> dict[str, float]:
    """Compute mean, median, min, max from a list of timings."""
    if not timings:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.mean(timings), 6),
        "median": round(statistics.median(timings), 6),
        "min": round(min(timings), 6),
        "max": round(max(timings), 6),
    }


# ---------------------------------------------------------------------------
# System information
# ---------------------------------------------------------------------------


def gather_system_info() -> dict[str, str]:
    """Collect system information for the report."""
    info: dict[str, str] = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
    }
    return info


# ---------------------------------------------------------------------------
# Implementation discovery
# ---------------------------------------------------------------------------


def discover_implementations() -> dict[str, bool]:
    """Detect which implementations are available."""
    available: dict[str, bool] = {}

    # Python -- always available since we're running in Python
    python_cli = PROJECT_ROOT / "python" / "src" / "muonledger" / "cli.py"
    available["python"] = python_cli.exists()

    # Rust -- check if Cargo.toml exists
    rust_cargo = PROJECT_ROOT / "rust" / "Cargo.toml"
    available["rust"] = rust_cargo.exists()

    # C++ ledger -- system command
    available["cpp"] = shutil.which("ledger") is not None

    return available


def build_rust() -> bool:
    """Build the Rust implementation in release mode. Returns True on success."""
    rust_dir = PROJECT_ROOT / "rust"
    try:
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(rust_dir),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_rust_binary() -> str | None:
    """Return path to Rust release binary, or None."""
    rust_bin = PROJECT_ROOT / "rust" / "target" / "release" / "muonledger"
    if rust_bin.exists():
        return str(rust_bin)
    return None


# ---------------------------------------------------------------------------
# Journal generation
# ---------------------------------------------------------------------------


def generate_journal_file(size: int, tmpdir: str) -> str:
    """Generate a journal file with the given transaction count. Returns path."""
    content = generate_journal(size, seed=42)
    path = os.path.join(tmpdir, f"bench_{size}.ledger")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------


def time_external_command(
    cmd: list[str],
    iterations: int,
    timeout: float = 600.0,
    cwd: str | None = None,
) -> list[float]:
    """Run an external command multiple times and return wall-clock timings."""
    timings: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            elapsed = time.perf_counter() - start
            if result.returncode == 0:
                timings.append(elapsed)
            else:
                # Record None-equivalent: skip failed runs
                pass
        except subprocess.TimeoutExpired:
            pass
    return timings


def benchmark_python(
    journal_path: str,
    iterations: int,
) -> dict[str, dict[str, float]]:
    """Benchmark the Python implementation."""
    results: dict[str, dict[str, float]] = {}
    python_dir = PROJECT_ROOT / "python"

    # Build command base
    cmd_base = [
        "uv", "run", "muonledger",
        "-f", journal_path,
    ]

    cwd = str(python_dir)

    # Parse: run balance but we're measuring total time which includes parsing
    # For parse-only, we use source command which just parses
    parse_cmd = cmd_base + ["source"]
    results["parse"] = compute_stats(
        time_external_command(parse_cmd, iterations, cwd=cwd)
    )

    # Balance
    bal_cmd = cmd_base + ["balance"]
    results["balance"] = compute_stats(
        time_external_command(bal_cmd, iterations, cwd=cwd)
    )

    # Register
    reg_cmd = cmd_base + ["register"]
    results["register"] = compute_stats(
        time_external_command(reg_cmd, iterations, cwd=cwd)
    )

    return results


def benchmark_rust(
    journal_path: str,
    rust_binary: str,
    iterations: int,
) -> dict[str, dict[str, float]]:
    """Benchmark the Rust implementation."""
    results: dict[str, dict[str, float]] = {}

    cmd_base = [rust_binary, "-f", journal_path]

    # Parse via balance (includes parse time; Rust has no source command)
    # We benchmark balance and register separately; parse = balance as proxy
    parse_cmd = cmd_base + ["balance"]
    results["parse"] = compute_stats(
        time_external_command(parse_cmd, iterations)
    )

    bal_cmd = cmd_base + ["balance"]
    results["balance"] = compute_stats(
        time_external_command(bal_cmd, iterations)
    )

    reg_cmd = cmd_base + ["register"]
    results["register"] = compute_stats(
        time_external_command(reg_cmd, iterations)
    )

    return results


def benchmark_cpp(
    journal_path: str,
    iterations: int,
) -> dict[str, dict[str, float]]:
    """Benchmark the C++ ledger implementation."""
    results: dict[str, dict[str, float]] = {}

    cmd_base = ["ledger", "-f", journal_path]

    parse_cmd = cmd_base + ["source"]
    results["parse"] = compute_stats(
        time_external_command(parse_cmd, iterations)
    )

    bal_cmd = cmd_base + ["balance"]
    results["balance"] = compute_stats(
        time_external_command(bal_cmd, iterations)
    )

    reg_cmd = cmd_base + ["register"]
    results["register"] = compute_stats(
        time_external_command(reg_cmd, iterations)
    )

    return results


# ---------------------------------------------------------------------------
# Table formatting
# ---------------------------------------------------------------------------


def supports_color() -> bool:
    """Check if the terminal supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes if terminal supports it."""
    if not supports_color():
        return text
    codes = {
        "green": "\033[32m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    }
    return f"{codes.get(color, '')}{text}{codes.get('reset', '')}"


def format_table(results: dict[str, dict[str, dict[str, dict[str, float]]]]) -> str:
    """Format benchmark results as a human-readable comparison table.

    Structure: results[impl][size_str][operation] = stats_dict
    """
    lines: list[str] = []

    # Gather all sizes and implementations
    all_impls = sorted(results.keys())
    all_sizes: set[str] = set()
    for impl_data in results.values():
        all_sizes.update(impl_data.keys())
    sorted_sizes = sorted(all_sizes, key=lambda s: int(s))

    for op in OPERATIONS:
        lines.append("")
        lines.append(colorize(f"=== {op.upper()} ===", "bold"))

        # Header
        header = f"{'Size':>10}"
        for impl_name in all_impls:
            header += f"  {impl_name:>12}"
        lines.append(header)
        lines.append("-" * len(header))

        for size_str in sorted_sizes:
            row = f"{_format_size(size_str):>10}"
            for impl_name in all_impls:
                impl_data = results.get(impl_name, {})
                size_data = impl_data.get(size_str, {})
                op_stats = size_data.get(op, {})
                mean = op_stats.get("mean", 0.0)
                if mean > 0:
                    row += f"  {mean:>10.4f}s"
                else:
                    row += f"  {'N/A':>11}"
            lines.append(row)

    lines.append("")
    return "\n".join(lines)


def _format_size(size_str: str) -> str:
    """Format a size number as 1K, 10K, etc."""
    n = int(size_str)
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    elif n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


# ---------------------------------------------------------------------------
# Historical comparison
# ---------------------------------------------------------------------------


def find_latest_report(output_dir: Path) -> Path | None:
    """Find the most recent benchmark report JSON file."""
    if not output_dir.exists():
        return None
    reports = sorted(output_dir.glob("benchmark_*.json"))
    return reports[-1] if reports else None


def load_report(path: Path) -> dict[str, Any]:
    """Load a benchmark report from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_comparison(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> str:
    """Format a comparison between current and previous results."""
    lines: list[str] = []
    lines.append("")
    lines.append(colorize("=== COMPARISON WITH PREVIOUS REPORT ===", "bold"))
    prev_ts = previous.get("timestamp", "unknown")
    lines.append(f"Previous report: {prev_ts}")
    lines.append("")

    cur_results = current.get("results", {})
    prev_results = previous.get("results", {})

    for impl_name in sorted(set(cur_results.keys()) | set(prev_results.keys())):
        cur_impl = cur_results.get(impl_name, {})
        prev_impl = prev_results.get(impl_name, {})

        for size_str in sorted(
            set(cur_impl.keys()) | set(prev_impl.keys()),
            key=lambda s: int(s),
        ):
            cur_size = cur_impl.get(size_str, {})
            prev_size = prev_impl.get(size_str, {})

            for op in OPERATIONS:
                cur_mean = cur_size.get(op, {}).get("mean", 0.0)
                prev_mean = prev_size.get(op, {}).get("mean", 0.0)

                if prev_mean <= 0 or cur_mean <= 0:
                    continue

                delta_pct = ((cur_mean - prev_mean) / prev_mean) * 100.0
                size_label = _format_size(size_str)

                if delta_pct < -1.0:
                    # Improvement
                    delta_str = colorize(
                        f"{prev_mean:.4f}s -> {cur_mean:.4f}s ({delta_pct:+.1f}%)",
                        "green",
                    )
                elif delta_pct > 1.0:
                    # Regression
                    delta_str = colorize(
                        f"{prev_mean:.4f}s -> {cur_mean:.4f}s ({delta_pct:+.1f}%)",
                        "red",
                    )
                else:
                    delta_str = (
                        f"{prev_mean:.4f}s -> {cur_mean:.4f}s ({delta_pct:+.1f}%)"
                    )

                lines.append(f"  {impl_name}: {op} {size_label}: {delta_str}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report saving
# ---------------------------------------------------------------------------


def save_report(
    report: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Save the benchmark report as a timestamped JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = report["timestamp"].replace(":", "").replace("-", "")
    # Format: benchmark_YYYY-MM-DDTHHMMSS.json
    ts_formatted = report["timestamp"][:10] + "T" + report["timestamp"][11:].replace(":", "")
    filename = f"benchmark_{ts_formatted}.json"
    path = output_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# Main benchmark orchestration
# ---------------------------------------------------------------------------


def run_benchmarks(
    sizes: list[int],
    iterations: int,
    implementations: list[str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    compare: bool = False,
    json_output: bool = False,
) -> dict[str, Any]:
    """Run benchmarks across all available implementations.

    Returns the complete report dict.
    """
    available = discover_implementations()

    # Filter to requested implementations
    if implementations:
        run_impls = [
            impl for impl in implementations if available.get(impl, False)
        ]
        skipped = [
            impl for impl in implementations if not available.get(impl, False)
        ]
    else:
        run_impls = [impl for impl, avail in available.items() if avail]
        skipped = [impl for impl, avail in available.items() if not avail]

    if not json_output:
        print(colorize("muonledger Cross-Implementation Benchmark", "bold"))
        print(f"Implementations: {', '.join(run_impls)}")
        if skipped:
            print(f"Skipped (unavailable): {', '.join(skipped)}")
        print(f"Sizes: {', '.join(str(s) for s in sizes)}")
        print(f"Iterations: {iterations}")
        print()

    # Build Rust if needed
    rust_binary: str | None = None
    if "rust" in run_impls:
        if not json_output:
            print("Building Rust (release)...")
        if build_rust():
            rust_binary = get_rust_binary()
            if rust_binary is None:
                if not json_output:
                    print("  Rust build succeeded but binary not found, skipping.")
                run_impls.remove("rust")
        else:
            if not json_output:
                print("  Rust build failed, skipping.")
            run_impls.remove("rust")

    # Generate journals in temp directory
    tmpdir = tempfile.mkdtemp(prefix="muonbench_")
    try:
        journal_files: dict[int, str] = {}
        for size in sizes:
            if not json_output:
                print(f"Generating journal with {size:,} transactions...")
            journal_files[size] = generate_journal_file(size, tmpdir)

        # Run benchmarks
        results: dict[str, dict[str, dict[str, dict[str, float]]]] = {}

        for impl_name in run_impls:
            if not json_output:
                print(f"\nBenchmarking {impl_name}...")
            results[impl_name] = {}

            for size in sizes:
                size_str = str(size)
                journal_path = journal_files[size]
                if not json_output:
                    print(f"  Size: {_format_size(size_str)}...", end="", flush=True)

                if impl_name == "python":
                    results[impl_name][size_str] = benchmark_python(
                        journal_path, iterations
                    )
                elif impl_name == "rust":
                    results[impl_name][size_str] = benchmark_rust(
                        journal_path, rust_binary, iterations  # type: ignore[arg-type]
                    )
                elif impl_name == "cpp":
                    results[impl_name][size_str] = benchmark_cpp(
                        journal_path, iterations
                    )

                if not json_output:
                    # Show quick summary
                    bal_mean = (
                        results[impl_name][size_str]
                        .get("balance", {})
                        .get("mean", 0.0)
                    )
                    print(f" balance={bal_mean:.4f}s")

        # Build report
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        report: dict[str, Any] = {
            "timestamp": timestamp,
            "system": gather_system_info(),
            "config": {
                "sizes": sizes,
                "iterations": iterations,
                "implementations": run_impls,
            },
            "results": results,
        }

        # Save report
        report_path = save_report(report, output_dir)

        if json_output:
            print(json.dumps(report, indent=2))
        else:
            # Print table
            print(format_table(results))
            print(f"Report saved to: {report_path}")

            # Compare with previous
            if compare:
                prev_path = find_previous_report(output_dir, report_path)
                if prev_path:
                    previous = load_report(prev_path)
                    print(format_comparison(report, previous))
                else:
                    print("\nNo previous report found for comparison.")

        return report

    finally:
        # Clean up temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)


def find_previous_report(output_dir: Path, current_path: Path) -> Path | None:
    """Find the most recent report before the current one."""
    if not output_dir.exists():
        return None
    reports = sorted(output_dir.glob("benchmark_*.json"))
    # Filter out the current report
    reports = [r for r in reports if r != current_path]
    return reports[-1] if reports else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Cross-implementation benchmark for muonledger.",
    )
    parser.add_argument(
        "--sizes",
        type=str,
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help=f"Comma-separated journal sizes (default: {','.join(str(s) for s in DEFAULT_SIZES)})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of iterations per test (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--implementations",
        type=str,
        default=None,
        help="Comma-separated list of implementations to benchmark (default: all available)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare with the most recent previous report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON to stdout instead of table",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory to save reports (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    sizes = [int(s.strip()) for s in args.sizes.split(",")]
    implementations = (
        [s.strip() for s in args.implementations.split(",")]
        if args.implementations
        else None
    )
    output_dir = Path(args.output_dir)

    run_benchmarks(
        sizes=sizes,
        iterations=args.iterations,
        implementations=implementations,
        output_dir=output_dir,
        compare=args.compare,
        json_output=args.json_output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
