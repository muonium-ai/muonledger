#!/usr/bin/env python3
"""CLOC (Count Lines of Code) report script for muonledger ports.

Counts lines of code across all implementations (Python, Rust, Kotlin, Swift)
and produces a formatted comparison report with optional JSON output.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# Skip patterns for directory walking
SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "target",
    "build",
    "dist",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.egg-info",
}

# Language configurations
LANGUAGE_CONFIG = {
    ".py": {
        "name": "Python",
        "line_comment": "#",
        "block_comment_start": None,
        "block_comment_end": None,
        "docstring": True,
    },
    ".rs": {
        "name": "Rust",
        "line_comment": "//",
        "block_comment_start": "/*",
        "block_comment_end": "*/",
        "docstring": False,
    },
    ".kt": {
        "name": "Kotlin",
        "line_comment": "//",
        "block_comment_start": "/*",
        "block_comment_end": "*/",
        "docstring": False,
    },
    ".swift": {
        "name": "Swift",
        "line_comment": "//",
        "block_comment_start": "/*",
        "block_comment_end": "*/",
        "docstring": False,
    },
    ".cc": {
        "name": "C++",
        "line_comment": "//",
        "block_comment_start": "/*",
        "block_comment_end": "*/",
        "docstring": False,
    },
    ".h": {
        "name": "C++",
        "line_comment": "//",
        "block_comment_start": "/*",
        "block_comment_end": "*/",
        "docstring": False,
    },
}

# Port configurations: (name, source_dir, test_dir, extensions)
# extensions can be a single string or list of strings
PORT_CONFIGS = [
    ("C++ (ledger)", "vendor/ledger/src", "vendor/ledger/test", [".cc", ".h"]),
    ("Python", "port/python/src/muonledger", "port/python/tests", ".py"),
    ("Rust", "port/rust/src", "port/rust/tests", ".rs"),
    ("Kotlin", "port/kotlin/src", "port/kotlin/tests", ".kt"),
    ("Swift", "port/swift/src", "port/swift/tests", ".swift"),
]


def should_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped during traversal."""
    if dirname.startswith("."):
        return True
    if dirname in SKIP_DIRS:
        return True
    if dirname.endswith(".egg-info"):
        return True
    return False


def find_files(directory: str, extension: str) -> list[str]:
    """Find all files with the given extension in directory, skipping hidden/build dirs."""
    files = []
    if not os.path.isdir(directory):
        return files
    for root, dirs, filenames in os.walk(directory):
        # Filter out directories to skip (modifies in-place for os.walk)
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for filename in sorted(filenames):
            if filename.endswith(extension) and not filename.startswith("."):
                files.append(os.path.join(root, filename))
    return sorted(files)


def count_lines(filepath: str) -> dict[str, int]:
    """Count code, comment, and blank lines in a file.

    Returns a dict with keys: code, comments, blanks, total.
    """
    ext = os.path.splitext(filepath)[1]
    config = LANGUAGE_CONFIG.get(ext)
    if config is None:
        return {"code": 0, "comments": 0, "blanks": 0, "total": 0}

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return {"code": 0, "comments": 0, "blanks": 0, "total": 0}

    total = len(lines)
    blanks = 0
    comments = 0
    code = 0

    in_block_comment = False
    in_docstring = False
    docstring_char = None

    for line in lines:
        stripped = line.strip()

        # Blank line
        if not stripped:
            blanks += 1
            continue

        # Handle Python docstrings
        if config.get("docstring") and ext == ".py":
            if not in_block_comment and not in_docstring:
                # Check for docstring start
                for quote in ('"""', "'''"):
                    if stripped.startswith(quote):
                        if stripped.count(quote) >= 2 and len(stripped) > len(quote):
                            # Single-line docstring like """text"""
                            # Check if it closes on the same line
                            rest = stripped[len(quote):]
                            if quote in rest:
                                comments += 1
                                in_docstring = False
                                docstring_char = None
                                break
                            else:
                                in_docstring = True
                                docstring_char = quote
                                comments += 1
                                break
                        elif stripped == quote:
                            # Just the opening quotes
                            in_docstring = True
                            docstring_char = quote
                            comments += 1
                            break
                        else:
                            # Opens and possibly closes
                            rest = stripped[len(quote):]
                            if quote in rest:
                                # Single line docstring
                                comments += 1
                                break
                            else:
                                in_docstring = True
                                docstring_char = quote
                                comments += 1
                                break
                else:
                    # No docstring found, fall through to line comment check
                    if stripped.startswith(config["line_comment"]):
                        comments += 1
                    else:
                        code += 1
                continue

            if in_docstring:
                comments += 1
                if docstring_char and docstring_char in stripped:
                    # Check it's actually closing (not the same line as opening)
                    # If the line ends with or contains the closing quote
                    in_docstring = False
                    docstring_char = None
                continue

        # Handle block comments (Rust, Kotlin, Swift)
        if config["block_comment_start"] and config["block_comment_end"]:
            if in_block_comment:
                comments += 1
                if config["block_comment_end"] in stripped:
                    in_block_comment = False
                continue

            if stripped.startswith(config["block_comment_start"]):
                comments += 1
                if config["block_comment_end"] not in stripped[2:]:
                    in_block_comment = True
                continue

        # Line comment
        if config["line_comment"] and stripped.startswith(config["line_comment"]):
            comments += 1
            continue

        # Code line
        code += 1

    return {"code": code, "comments": comments, "blanks": blanks, "total": total}


def count_directory(directory: str, extension: str | list[str]) -> dict[str, Any]:
    """Count lines for all matching files in a directory.

    Returns dict with keys: files, code, comments, blanks, total, file_details.
    ``extension`` can be a single string or a list of strings.
    """
    if isinstance(extension, list):
        files = []
        for ext in extension:
            files.extend(find_files(directory, ext))
    else:
        files = find_files(directory, extension)
    result = {
        "files": 0,
        "code": 0,
        "comments": 0,
        "blanks": 0,
        "total": 0,
        "file_details": [],
    }

    for filepath in files:
        counts = count_lines(filepath)
        result["files"] += 1
        result["code"] += counts["code"]
        result["comments"] += counts["comments"]
        result["blanks"] += counts["blanks"]
        result["total"] += counts["total"]
        result["file_details"].append({"path": filepath, **counts})

    return result


def generate_report(project_root: str) -> dict[str, Any]:
    """Generate CLOC report for all implementations.

    Returns the full report as a dict.
    """
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    implementations = {}

    for name, source_dir, test_dir, ext in PORT_CONFIGS:
        key = name.lower()
        src_path = os.path.join(project_root, source_dir)
        test_path = os.path.join(project_root, test_dir)

        source = count_directory(src_path, ext)
        tests = count_directory(test_path, ext)

        # Compute totals
        total = {
            "files": source["files"] + tests["files"],
            "code": source["code"] + tests["code"],
            "comments": source["comments"] + tests["comments"],
            "blanks": source["blanks"] + tests["blanks"],
            "total": source["total"] + tests["total"],
        }

        # Remove file_details from summary (keep for verbose)
        source_summary = {k: v for k, v in source.items() if k != "file_details"}
        tests_summary = {k: v for k, v in tests.items() if k != "file_details"}

        implementations[key] = {
            "source": source_summary,
            "tests": tests_summary,
            "total": total,
            "_source_details": source.get("file_details", []),
            "_tests_details": tests.get("file_details", []),
        }

    return {"timestamp": timestamp, "implementations": implementations}


def format_table(report: dict[str, Any]) -> str:
    """Format the report as a comparison table."""
    lines = []

    # Header
    header = (
        f"{'Implementation':<16} {'Source Files':>12} {'Source LOC':>11} "
        f"{'Test Files':>11} {'Test LOC':>10} {'Total LOC':>11} {'Ratio':>7}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    impls = report["implementations"]

    # Use C++ as baseline for ratio, fallback to max if C++ not present
    cpp_key = "c++ (ledger)"
    baseline_total = 0
    if cpp_key in impls:
        baseline_total = impls[cpp_key]["total"]["code"]
    if baseline_total == 0:
        for data in impls.values():
            t = data["total"]["code"]
            if t > baseline_total:
                baseline_total = t

    display_names = {
        "c++ (ledger)": "C++ (ledger)",
        "python": "Python",
        "rust": "Rust",
        "kotlin": "Kotlin",
        "swift": "Swift",
    }

    for name in ["c++ (ledger)", "python", "rust", "kotlin", "swift"]:
        if name not in impls:
            continue
        data = impls[name]
        src = data["source"]
        tst = data["tests"]
        total_code = data["total"]["code"]

        if baseline_total > 0 and total_code > 0:
            ratio = total_code / baseline_total
            ratio_str = f"{ratio:.1f}x"
        else:
            ratio_str = "\u2014"

        display = display_names.get(name, name.capitalize())
        line = (
            f"{display:<16} "
            f"{src['files']:>12,} "
            f"{src['code']:>11,} "
            f"{tst['files']:>11,} "
            f"{tst['code']:>10,} "
            f"{total_code:>11,} "
            f"{ratio_str:>7}"
        )
        lines.append(line)

    return "\n".join(lines)


def format_verbose(report: dict[str, Any]) -> str:
    """Format verbose per-file breakdown."""
    lines = []

    for name in ["python", "rust", "kotlin", "swift"]:
        data = report["implementations"].get(name)
        if not data:
            continue
        if data["total"]["files"] == 0:
            continue

        lines.append(f"\n{'=' * 60}")
        lines.append(f"  {name.capitalize()}")
        lines.append(f"{'=' * 60}")

        for section, label in [("_source_details", "Source"), ("_tests_details", "Tests")]:
            details = data.get(section, [])
            if not details:
                continue
            lines.append(f"\n  {label}:")
            lines.append(f"  {'File':<50} {'Code':>6} {'Comment':>8} {'Blank':>6} {'Total':>6}")
            lines.append(f"  {'-' * 76}")
            for fd in details:
                short = fd["path"]
                # Shorten path for display
                parts = short.split(os.sep)
                if len(parts) > 4:
                    short = os.sep.join(parts[-4:])
                lines.append(
                    f"  {short:<50} {fd['code']:>6} {fd['comments']:>8} "
                    f"{fd['blanks']:>6} {fd['total']:>6}"
                )

    return "\n".join(lines)


def save_report(report: dict[str, Any], output_dir: str) -> str:
    """Save report as timestamped JSON file. Returns the filepath."""
    os.makedirs(output_dir, exist_ok=True)

    # Clean report (remove internal details)
    clean = {
        "timestamp": report["timestamp"],
        "implementations": {},
    }
    for name, data in report["implementations"].items():
        clean["implementations"][name] = {
            "source": data["source"],
            "tests": data["tests"],
            "total": data["total"],
        }

    ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    filename = f"cloc_{ts}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")

    return filepath


def load_latest_report(output_dir: str) -> dict[str, Any] | None:
    """Load the most recent saved report from output_dir."""
    if not os.path.isdir(output_dir):
        return None

    files = sorted(
        [f for f in os.listdir(output_dir) if f.startswith("cloc_") and f.endswith(".json")],
        reverse=True,
    )
    if not files:
        return None

    filepath = os.path.join(output_dir, files[0])
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def format_comparison(current: dict[str, Any], previous: dict[str, Any]) -> str:
    """Format comparison between current and previous report."""
    lines = []
    lines.append(f"\nComparison with previous report ({previous.get('timestamp', 'unknown')}):")
    lines.append("-" * 70)

    for name in ["python", "rust", "kotlin", "swift"]:
        curr_impl = current["implementations"].get(name, {})
        prev_impl = previous["implementations"].get(name, {})

        if not curr_impl and not prev_impl:
            continue

        curr_total = curr_impl.get("total", {})
        prev_total = prev_impl.get("total", {})

        for section in ["source", "tests"]:
            curr_sec = curr_impl.get(section, {})
            prev_sec = prev_impl.get(section, {})
            curr_code = curr_sec.get("code", 0)
            prev_code = prev_sec.get("code", 0)

            if curr_code == 0 and prev_code == 0:
                continue

            delta = curr_code - prev_code
            if prev_code > 0:
                pct = (delta / prev_code) * 100
                pct_str = f"{pct:+.1f}%"
            else:
                pct_str = "new"

            sign = "+" if delta >= 0 else ""
            lines.append(
                f"  {name.capitalize()} {section}: "
                f"{prev_code:,} -> {curr_code:,} "
                f"({sign}{delta:,} lines, {pct_str})"
            )

    return "\n".join(lines)


def find_project_root() -> str:
    """Find the project root by looking for port/ directory."""
    # Start from the script location
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Try going up from script location
    current = script_dir
    for _ in range(5):
        if os.path.isdir(os.path.join(current, "port")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # Try current working directory
    cwd = os.getcwd()
    current = cwd
    for _ in range(5):
        if os.path.isdir(os.path.join(current, "port")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return cwd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count lines of code across muonledger implementations"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON to stdout"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save JSON report (default: port/reports/cloc)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show per-file breakdown"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare with most recent saved report",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (auto-detected if not specified)",
    )

    args = parser.parse_args()

    project_root = args.project_root or find_project_root()
    output_dir = args.output_dir or os.path.join(project_root, "port", "reports", "cloc")

    report = generate_report(project_root)

    if args.json:
        # Output clean JSON to stdout
        clean = {
            "timestamp": report["timestamp"],
            "implementations": {},
        }
        for name, data in report["implementations"].items():
            clean["implementations"][name] = {
                "source": data["source"],
                "tests": data["tests"],
                "total": data["total"],
            }
        json.dump(clean, sys.stdout, indent=2)
        print()
        return

    # Print table
    print()
    print(format_table(report))
    print()

    if args.verbose:
        print(format_verbose(report))
        print()

    # Compare with previous
    if args.compare:
        previous = load_latest_report(output_dir)
        if previous:
            print(format_comparison(report, previous))
            print()
        else:
            print("No previous report found for comparison.")
            print()

    # Save report
    filepath = save_report(report, output_dir)
    print(f"Report saved to: {filepath}")


if __name__ == "__main__":
    main()
