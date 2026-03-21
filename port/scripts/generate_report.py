#!/usr/bin/env python3
"""Generate a combined timestamped markdown report.

Runs benchmark, CLOC, and parity tests, then combines the results
into a single markdown file saved to port/reports/.
"""

import argparse
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PORT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PORT_DIR.parent
REPORTS_DIR = PORT_DIR / "reports"

# Add scripts dir to path for imports
sys.path.insert(0, str(SCRIPT_DIR))


# ---------------------------------------------------------------------------
# Sub-report runners
# ---------------------------------------------------------------------------


def run_cloc() -> dict[str, Any]:
    """Run CLOC report and return the data."""
    from cloc_report import generate_report
    return generate_report(str(PROJECT_ROOT))


def run_benchmark(
    sizes: list[int], iterations: int
) -> dict[str, Any]:
    """Run benchmark and return the data."""
    from benchmark import run_benchmarks
    return run_benchmarks(
        sizes=sizes,
        iterations=iterations,
        json_output=True,
    )


def run_parity() -> dict[str, Any]:
    """Run parity tests and return the data."""
    from test_parity import (
        discover_implementations,
        get_test_cases,
        build_parity_matrix,
        matrix_to_serializable,
    )
    impls = discover_implementations()
    test_cases = get_test_cases()
    matrix = build_parity_matrix(test_cases, impls, timeout=30)
    return {
        "implementations": {
            name: {"available": impl.available}
            for name, impl in impls.items()
        },
        "matrix": matrix_to_serializable(matrix),
    }


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------


def _format_time(seconds: float) -> str:
    """Format time with auto-scaled units."""
    if seconds <= 0:
        return "N/A"
    if seconds >= 1.0:
        return f"{seconds:.3f}s"
    if seconds >= 0.001:
        return f"{seconds * 1000:.2f}ms"
    return f"{seconds * 1_000_000:.1f}µs"


def _system_info() -> str:
    """Return system info string."""
    return (
        f"- **OS**: {platform.system()} {platform.release()}\n"
        f"- **CPU**: {platform.processor() or platform.machine()}\n"
        f"- **Python**: {platform.python_version()}\n"
    )


def render_cloc_section(data: dict[str, Any]) -> str:
    """Render CLOC data as markdown."""
    lines = ["## Lines of Code", ""]

    impls = data.get("implementations", {})

    # Find C++ baseline for ratio
    cpp_key = "c++ (ledger)"
    baseline = impls.get(cpp_key, {}).get("total", {}).get("code", 0)
    if baseline == 0:
        for v in impls.values():
            c = v.get("total", {}).get("code", 0)
            if c > baseline:
                baseline = c

    display_names = {
        "c++ (ledger)": "C++ (ledger)",
        "python": "Python",
        "rust": "Rust",
        "kotlin": "Kotlin",
        "swift": "Swift",
    }

    lines.append(
        "| Implementation | Source Files | Source LOC | Test Files | Test LOC "
        "| Total LOC | Ratio |"
    )
    lines.append(
        "|----------------|-------------|-----------|------------|----------"
        "|-----------|-------|"
    )

    for key in ["c++ (ledger)", "python", "rust", "kotlin", "swift"]:
        if key not in impls:
            continue
        d = impls[key]
        src = d.get("source", {})
        tst = d.get("tests", {})
        total = d.get("total", {}).get("code", 0)

        if src.get("files", 0) == 0 and tst.get("files", 0) == 0:
            continue

        ratio = f"{total / baseline:.1f}x" if baseline > 0 and total > 0 else "—"
        name = display_names.get(key, key)
        lines.append(
            f"| {name} | {src.get('files', 0):,} | {src.get('code', 0):,} "
            f"| {tst.get('files', 0):,} | {tst.get('code', 0):,} "
            f"| {total:,} | {ratio} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_benchmark_section(data: dict[str, Any]) -> str:
    """Render benchmark data as markdown."""
    lines = [
        "## Benchmark",
        "",
        f"- **Iterations**: {data.get('iterations', 'N/A')}",
        f"- **Sizes**: {', '.join(str(s) for s in data.get('sizes', []))}",
        "",
    ]

    results = data.get("results", {})
    if not results:
        lines.append("*No benchmark results available.*\n")
        return "\n".join(lines)

    # Collect all implementations and sizes
    all_impls = []
    impl_order = ["cpp", "rust", "python", "kotlin", "swift"]
    for name in impl_order:
        if name in results:
            all_impls.append(name)

    all_sizes = set()
    for impl_data in results.values():
        all_sizes.update(impl_data.keys())
    sorted_sizes = sorted(all_sizes, key=lambda s: int(s))

    display_names = {
        "cpp": "C++ (ledger)",
        "python": "Python",
        "rust": "Rust",
        "kotlin": "Kotlin",
        "swift": "Swift",
    }

    for op in ["parse", "balance", "register"]:
        lines.append(f"### {op.capitalize()}")
        lines.append("")

        header = "| Size |"
        sep = "|------|"
        for impl_name in all_impls:
            header += f" {display_names.get(impl_name, impl_name)} |"
            sep += "--------|"
        lines.append(header)
        lines.append(sep)

        for size_str in sorted_sizes:
            n = int(size_str)
            if n >= 1_000_000:
                label = f"{n // 1_000_000}M"
            elif n >= 1_000:
                label = f"{n // 1_000}K"
            else:
                label = str(n)

            row = f"| {label} |"
            for impl_name in all_impls:
                impl_data = results.get(impl_name, {})
                size_data = impl_data.get(size_str, {})
                op_stats = size_data.get(op, {})
                mean = op_stats.get("mean", 0.0)
                row += f" {_format_time(mean)} |"
            lines.append(row)

        lines.append("")

    return "\n".join(lines)


def render_parity_section(data: dict[str, Any]) -> str:
    """Render parity data as markdown."""
    lines = ["## Feature Parity", ""]

    impls_info = data.get("implementations", {})
    matrix = data.get("matrix", {})

    if not matrix:
        lines.append("*No parity results available.*\n")
        return "\n".join(lines)

    # Determine which impls are available
    impl_order = ["ledger", "python", "rust", "kotlin", "swift"]
    active_impls = [
        name for name in impl_order
        if impls_info.get(name, {}).get("available", False)
    ]

    display_names = {
        "ledger": "C++ (ledger)",
        "python": "Python",
        "rust": "Rust",
        "kotlin": "Kotlin",
        "swift": "Swift",
    }

    # Build table
    header = "| Test |"
    sep = "|------|"
    for name in active_impls:
        header += f" {display_names.get(name, name)} |"
        sep += "--------|"
    lines.append(header)
    lines.append(sep)

    status_icons = {
        "pass": "✅",
        "ref": "🔷",
        "fail": "❌",
        "error": "⚠️",
        "skip": "⏭️",
    }

    for test_name, impl_results in matrix.items():
        row = f"| {test_name} |"
        for name in active_impls:
            status = impl_results.get(name, {}).get("status", "skip")
            icon = status_icons.get(status, status)
            row += f" {icon} |"
        lines.append(row)

    lines.append("")

    # Summary
    lines.append("### Summary")
    lines.append("")
    lines.append("| Implementation | Pass | Fail | Error | Skip | Total |")
    lines.append("|----------------|------|------|-------|------|-------|")

    for name in active_impls:
        counts = {"pass": 0, "ref": 0, "fail": 0, "error": 0, "skip": 0}
        for impl_results in matrix.values():
            status = impl_results.get(name, {}).get("status", "skip")
            if status == "ref":
                counts["pass"] += 1
            else:
                counts[status] = counts.get(status, 0) + 1
        total = len(matrix)
        display = display_names.get(name, name)
        lines.append(
            f"| {display} | {counts['pass']} | {counts['fail']} "
            f"| {counts['error']} | {counts['skip']} | {total} |"
        )

    lines.append("")
    lines.append(
        "Legend: ✅ Pass | 🔷 Reference | ❌ Fail | ⚠️ Error | ⏭️ Skip"
    )
    lines.append("")
    return "\n".join(lines)


def generate_markdown(
    cloc_data: dict[str, Any],
    benchmark_data: dict[str, Any],
    parity_data: dict[str, Any],
    timestamp: str,
) -> str:
    """Generate the combined markdown report."""
    lines = [
        f"# MuonLedger Port Report — {timestamp}",
        "",
        "## System",
        "",
        _system_info(),
        "---",
        "",
        render_cloc_section(cloc_data),
        "---",
        "",
        render_benchmark_section(benchmark_data),
        "---",
        "",
        render_parity_section(parity_data),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save report
# ---------------------------------------------------------------------------


def save_report(
    markdown: str,
    timestamp: str,
    output_dir: Path = REPORTS_DIR,
    json_data: dict[str, Any] | None = None,
) -> Path:
    """Save the markdown report and optional JSON sidecar."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts_fmt = timestamp.replace(":", "").replace("-", "").replace("T", "T")
    md_path = output_dir / f"report_{ts_fmt}.md"
    md_path.write_text(markdown, encoding="utf-8")

    if json_data is not None:
        json_path = output_dir / f"report_{ts_fmt}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, default=str)

    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate combined markdown report for muonledger ports.",
    )
    parser.add_argument(
        "--sizes",
        default="1000,10000,100000",
        help="Comma-separated journal sizes for benchmark (default: 1000,10000,100000)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Benchmark iterations (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPORTS_DIR),
        help=f"Output directory (default: {REPORTS_DIR})",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Skip benchmark (faster report generation)",
    )
    parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="Skip parity tests",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    sizes = [int(s.strip()) for s in args.sizes.split(",")]

    print(f"Generating muonledger report at {timestamp}\n")

    # CLOC
    print("Running CLOC analysis...")
    cloc_data = run_cloc()
    print("  Done.\n")

    # Benchmark
    if args.skip_benchmark:
        print("Skipping benchmark.\n")
        benchmark_data = {"results": {}, "sizes": sizes, "iterations": args.iterations}
    else:
        print("Running benchmarks...")
        benchmark_data = run_benchmark(sizes, args.iterations)
        print("  Done.\n")

    # Parity
    if args.skip_parity:
        print("Skipping parity tests.\n")
        parity_data = {"implementations": {}, "matrix": []}
    else:
        print("Running parity tests...")
        parity_data = run_parity()
        print("  Done.\n")

    # Generate markdown
    markdown = generate_markdown(cloc_data, benchmark_data, parity_data, timestamp)

    # Save
    output_dir = Path(args.output_dir)
    combined_json = {
        "timestamp": timestamp,
        "cloc": cloc_data,
        "benchmark": benchmark_data,
        "parity": parity_data,
    }
    md_path = save_report(markdown, timestamp, output_dir, combined_json)

    print(f"Report saved to: {md_path}")
    print()

    # Also print to stdout
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
