#!/usr/bin/env python3
"""Cross-implementation feature parity test script for muonledger.

Tests feature parity across all implementations: C++ ledger, Python, Rust,
Kotlin, and Swift.  Generates a parity matrix and saves results as JSON.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent  # port/scripts/
PORT_DIR = SCRIPT_DIR.parent                  # port/
PROJECT_ROOT = PORT_DIR.parent                # muonledger/
REPORTS_DIR = PORT_DIR / "reports" / "parity"


# ---------------------------------------------------------------------------
# Implementation registry
# ---------------------------------------------------------------------------

@dataclass
class Implementation:
    name: str
    cmd: list[str]
    cwd: str | None = None
    check_cmd: list[str] | None = None
    available: bool = False


def get_implementations() -> dict[str, Implementation]:
    """Return implementation definitions."""
    return {
        "ledger": Implementation(
            name="ledger",
            cmd=["ledger"],
            check_cmd=["ledger", "--version"],
        ),
        "python": Implementation(
            name="python",
            cmd=["uv", "run", "python", "-m", "muonledger"],
            cwd=str(PORT_DIR / "python"),
            check_cmd=["uv", "run", "python", "-m", "muonledger", "--version"],
        ),
        "rust": Implementation(
            name="rust",
            cmd=["cargo", "run", "--release", "--"],
            cwd=str(PORT_DIR / "rust"),
            check_cmd=["cargo", "build", "--release"],
        ),
        "kotlin": Implementation(
            name="kotlin",
            cmd=["./gradlew", "run", "--args"],
            cwd=str(PORT_DIR / "kotlin"),
            check_cmd=["./gradlew", "--version"],
        ),
        "swift": Implementation(
            name="swift",
            cmd=["swift", "run", "muonledger"],
            cwd=str(PORT_DIR / "swift"),
            check_cmd=["swift", "build"],
        ),
    }


def discover_implementations(
    implementations: dict[str, Implementation] | None = None,
) -> dict[str, Implementation]:
    """Probe which implementations are available."""
    if implementations is None:
        implementations = get_implementations()
    for impl in implementations.values():
        if impl.check_cmd is None:
            continue
        try:
            result = subprocess.run(
                impl.check_cmd,
                cwd=impl.cwd,
                capture_output=True,
                timeout=60,
            )
            impl.available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            impl.available = False
    return implementations


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    """A single parity test case."""

    name: str
    journal: str
    command: str          # balance | register | print
    args: list[str] = field(default_factory=list)
    description: str = ""
    # If set, expect the output to contain this substring (loose check).
    expect_contains: str | None = None
    # Extra files needed (name -> content) e.g. for include tests.
    extra_files: dict[str, str] = field(default_factory=dict)


def get_test_cases() -> list[TestCase]:
    """Return the full list of parity test cases."""
    return [
        # 1. Basic 2-posting transaction - balance
        TestCase(
            name="basic_balance",
            journal=(
                "2024-01-15 Grocery Store\n"
                "    Expenses:Food              $50.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Basic 2-posting transaction, balance report",
            expect_contains="$50.00",
        ),
        # 2. Basic 2-posting transaction - register
        TestCase(
            name="basic_register",
            journal=(
                "2024-01-15 Grocery Store\n"
                "    Expenses:Food              $50.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            description="Basic 2-posting transaction, register report",
            expect_contains="Grocery Store",
        ),
        # 3. Basic 2-posting transaction - print
        TestCase(
            name="basic_print",
            journal=(
                "2024-01-15 Grocery Store\n"
                "    Expenses:Food              $50.00\n"
                "    Assets:Checking\n"
            ),
            command="print",
            description="Basic 2-posting transaction, print command",
            expect_contains="Grocery Store",
        ),
        # 4. Multi-posting transaction
        TestCase(
            name="multi_posting_balance",
            journal=(
                "2024-01-20 Dinner\n"
                "    Expenses:Food:Dining       $30.00\n"
                "    Expenses:Food:Drinks       $15.00\n"
                "    Liabilities:CreditCard\n"
            ),
            command="balance",
            description="Multi-posting transaction balance",
            expect_contains="$45.00",
        ),
        # 5. Multi-commodity
        TestCase(
            name="multi_commodity",
            journal=(
                "2024-01-10 Opening\n"
                "    Assets:Checking            $1000.00\n"
                "    Equity:Opening\n"
                "\n"
                "2024-01-15 Buy Euros\n"
                "    Assets:Euro                100 EUR\n"
                "    Assets:Checking            $-110.00\n"
            ),
            command="balance",
            description="Multiple commodities in balance",
            expect_contains="EUR",
        ),
        # 6. Virtual posting (parentheses)
        TestCase(
            name="virtual_posting_paren",
            journal=(
                "2024-02-01 Salary\n"
                "    Assets:Checking            $3000.00\n"
                "    Income:Salary             $-3000.00\n"
                "    (Budget:Savings)            $500.00\n"
            ),
            command="balance",
            description="Virtual posting with parentheses",
            expect_contains="Budget:Savings",
        ),
        # 7. Virtual posting (brackets)
        TestCase(
            name="virtual_posting_bracket",
            journal=(
                "2024-02-01 Salary\n"
                "    Assets:Checking            $3000.00\n"
                "    Income:Salary             $-3000.00\n"
                "    [Budget:Emergency]          $200.00\n"
                "    [Budget:Emergency]         $-200.00\n"
            ),
            command="balance",
            description="Balanced virtual posting with brackets",
            expect_contains="Budget:Emergency",
        ),
        # 8. Cleared state marker
        TestCase(
            name="cleared_state",
            journal=(
                "2024-03-01 * Cleared transaction\n"
                "    Expenses:Rent              $1200.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            description="Cleared transaction marker",
            expect_contains="Cleared transaction",
        ),
        # 9. Pending state marker
        TestCase(
            name="pending_state",
            journal=(
                "2024-03-05 ! Pending payment\n"
                "    Expenses:Utilities         $85.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            description="Pending transaction marker",
            expect_contains="Pending payment",
        ),
        # 10. Transaction tags/metadata
        TestCase(
            name="transaction_tags",
            journal=(
                "2024-04-01 Office Supplies\n"
                "    ; Payee: Staples\n"
                "    Expenses:Office            $45.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Transaction with tag metadata",
            expect_contains="$45.00",
        ),
        # 11. Automated transaction
        TestCase(
            name="automated_transaction",
            journal=(
                "= Expenses:Food\n"
                "    (Budget:Food)              -1.0\n"
                "\n"
                "2024-05-01 Groceries\n"
                "    Expenses:Food              $60.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Automated transaction with = predicate",
            expect_contains="$60.00",
        ),
        # 12. Periodic transaction
        TestCase(
            name="periodic_transaction",
            journal=(
                "~ Monthly\n"
                "    Expenses:Rent              $1500.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-06-01 June Rent\n"
                "    Expenses:Rent              $1500.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Periodic transaction with ~ period",
            expect_contains="$1,500",
        ),
        # 13. Lot annotations with price
        TestCase(
            name="lot_price",
            journal=(
                "2024-01-10 Buy Stock\n"
                "    Assets:Brokerage           10 AAPL {$150.00}\n"
                "    Assets:Checking           $-1500.00\n"
            ),
            command="balance",
            description="Lot annotation with {price}",
            expect_contains="AAPL",
        ),
        # 14. Balance assertion
        TestCase(
            name="balance_assertion",
            journal=(
                "2024-01-01 Opening\n"
                "    Assets:Checking            $1000.00\n"
                "    Equity:Opening\n"
                "\n"
                "2024-01-15 Grocery\n"
                "    Expenses:Food              $50.00\n"
                "    Assets:Checking             = $950.00\n"
            ),
            command="balance",
            description="Balance assertion with = amount",
            expect_contains="$950.00",
        ),
        # 15. Cost @ syntax
        TestCase(
            name="cost_at",
            journal=(
                "2024-02-01 Buy EUR\n"
                "    Assets:Euro                100 EUR @ $1.10\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Cost with @ per-unit syntax",
            expect_contains="EUR",
        ),
        # 16. Cost @@ total syntax
        TestCase(
            name="cost_at_total",
            journal=(
                "2024-02-01 Buy EUR\n"
                "    Assets:Euro                100 EUR @@ $110.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Cost with @@ total syntax",
            expect_contains="EUR",
        ),
        # 17. Account alias
        TestCase(
            name="account_alias",
            journal=(
                "alias chk=Assets:Checking\n"
                "\n"
                "2024-03-01 Deposit\n"
                "    chk                        $500.00\n"
                "    Income:Salary\n"
            ),
            command="balance",
            description="Account alias directive",
            expect_contains="$500.00",
        ),
        # 18. Apply account
        TestCase(
            name="apply_account",
            journal=(
                "apply account Assets\n"
                "\n"
                "2024-04-01 Deposit\n"
                "    Checking                   $200.00\n"
                "    Savings                   $-200.00\n"
                "\n"
                "end apply account\n"
            ),
            command="balance",
            description="Apply account directive",
            expect_contains="Assets",
        ),
        # 19. P price directive
        TestCase(
            name="price_directive",
            journal=(
                "P 2024-01-01 EUR $1.10\n"
                "P 2024-06-01 EUR $1.08\n"
                "\n"
                "2024-01-15 Buy EUR\n"
                "    Assets:Euro                100 EUR\n"
                "    Assets:Checking           $-110.00\n"
            ),
            command="balance",
            description="Price directive with P",
            expect_contains="EUR",
        ),
        # 20. Comment blocks
        TestCase(
            name="comment_block",
            journal=(
                "comment\n"
                "This is a block comment.\n"
                "Nothing here should be parsed.\n"
                "end comment\n"
                "\n"
                "2024-01-01 After comment\n"
                "    Expenses:Test              $10.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Block comment directive",
            expect_contains="$10.00",
        ),
        # 21. Date filtering --begin
        TestCase(
            name="date_filter_begin",
            journal=(
                "2024-01-01 January\n"
                "    Expenses:A                 $10.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-06-01 June\n"
                "    Expenses:B                 $20.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            args=["--begin", "2024-03-01"],
            description="Date filter with --begin",
            expect_contains="$20.00",
        ),
        # 22. Date filtering --end
        TestCase(
            name="date_filter_end",
            journal=(
                "2024-01-01 January\n"
                "    Expenses:A                 $10.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-06-01 June\n"
                "    Expenses:B                 $20.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            args=["--end", "2024-03-01"],
            description="Date filter with --end",
            expect_contains="$10.00",
        ),
        # 23. Account filtering pattern
        TestCase(
            name="account_filter",
            journal=(
                "2024-01-01 Test\n"
                "    Expenses:Food              $30.00\n"
                "    Expenses:Rent              $1000.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            args=["Expenses:Food"],
            description="Account filter with regex pattern",
            expect_contains="$30.00",
        ),
        # 24. Null-amount inference
        TestCase(
            name="null_amount_inference",
            journal=(
                "2024-01-01 Test\n"
                "    Expenses:Food              $25.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Null amount inferred on second posting",
            expect_contains="$25.00",
        ),
        # 25. Negative amounts
        TestCase(
            name="negative_amounts",
            journal=(
                "2024-01-01 Refund\n"
                "    Expenses:Food             $-15.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Negative amount in posting",
            expect_contains="$-15.00",
        ),
        # 26. Multiple date formats
        TestCase(
            name="date_formats",
            journal=(
                "2024/01/15 Slash format\n"
                "    Expenses:Test              $10.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Date with slash separators",
            expect_contains="$10.00",
        ),
        # 27. Include directive
        TestCase(
            name="include_directive",
            journal=(
                'include included.dat\n'
            ),
            command="balance",
            description="Include directive",
            expect_contains="$75.00",
            extra_files={
                "included.dat": (
                    "2024-01-01 Included\n"
                    "    Expenses:Included          $75.00\n"
                    "    Assets:Checking\n"
                ),
            },
        ),
        # 28. Deeply nested accounts
        TestCase(
            name="deep_accounts",
            journal=(
                "2024-01-01 Deep\n"
                "    Expenses:A:B:C:D:E         $5.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Deeply nested account hierarchy",
            expect_contains="$5.00",
        ),
        # 29. Multiple transactions balance
        TestCase(
            name="multiple_xact_balance",
            journal=(
                "2024-01-01 First\n"
                "    Expenses:Food              $10.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-01-02 Second\n"
                "    Expenses:Food              $20.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-01-03 Third\n"
                "    Expenses:Food              $30.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Multiple transactions summed in balance",
            expect_contains="$60.00",
        ),
        # 30. Register with running total
        TestCase(
            name="register_running_total",
            journal=(
                "2024-01-01 First\n"
                "    Expenses:Food              $10.00\n"
                "    Assets:Checking\n"
                "\n"
                "2024-01-02 Second\n"
                "    Expenses:Food              $20.00\n"
                "    Assets:Checking\n"
            ),
            command="register",
            args=["Expenses"],
            description="Register shows running totals",
            expect_contains="$30.00",
        ),
        # 31. Commodity with comma thousands
        TestCase(
            name="large_amount",
            journal=(
                "2024-01-01 Big purchase\n"
                "    Expenses:Equipment        $12,500.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Large amount with comma separator",
            expect_contains="12",
        ),
        # 32. Payee note syntax
        TestCase(
            name="payee_note",
            journal=(
                "2024-01-01 Store | Receipt #123\n"
                "    Expenses:Supplies          $42.00\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Payee with | note separator",
            expect_contains="$42.00",
        ),
        # 33. Empty journal
        TestCase(
            name="empty_journal",
            journal="\n",
            command="balance",
            description="Empty journal produces no output",
        ),
        # 34. Comment-only journal
        TestCase(
            name="comment_only_journal",
            journal=(
                "; This is a comment\n"
                "; Another comment\n"
            ),
            command="balance",
            description="Journal with only comments",
        ),
        # 35. Posting-level comment
        TestCase(
            name="posting_comment",
            journal=(
                "2024-01-01 Test\n"
                "    Expenses:Food              $25.00  ; lunch\n"
                "    Assets:Checking\n"
            ),
            command="balance",
            description="Posting with inline comment",
            expect_contains="$25.00",
        ),
    ]


# ---------------------------------------------------------------------------
# Output normalization and comparison
# ---------------------------------------------------------------------------

def normalize_output(text: str) -> str:
    """Normalize output for comparison: strip trailing whitespace per line,
    collapse multiple blank lines, strip leading/trailing blank lines."""
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse consecutive blank lines into one
    normalized: list[str] = []
    prev_blank = False
    for line in lines:
        if line == "":
            if not prev_blank:
                normalized.append("")
            prev_blank = True
        else:
            normalized.append(line)
            prev_blank = False
    result = "\n".join(normalized).strip()
    return result


def normalize_amounts(text: str) -> str:
    """Further normalize numeric amounts: remove comma separators, strip
    trailing zeros after decimal point."""
    # Remove thousands commas in amounts like $1,000.00
    text = re.sub(r'(\$\d{1,3}),(\d{3})', r'\1\2', text)
    # Strip trailing zeros: $50.00 -> $50, $50.10 -> $50.1
    text = re.sub(r'(\$\d+)\.0+\b', r'\1', text)
    text = re.sub(r'(\$\d+\.\d*[1-9])0+\b', r'\1', text)
    return text


@dataclass
class CompareResult:
    status: str  # "exact_match", "fuzzy_match", "mismatch", "skip", "error"
    diff: str = ""
    detail: str = ""


def compare_outputs(reference: str, candidate: str) -> CompareResult:
    """Compare two outputs, returning match status."""
    if reference == candidate:
        return CompareResult(status="exact_match")

    norm_ref = normalize_output(reference)
    norm_cand = normalize_output(candidate)

    if norm_ref == norm_cand:
        return CompareResult(status="fuzzy_match", detail="whitespace difference only")

    # Try amount normalization
    if normalize_amounts(norm_ref) == normalize_amounts(norm_cand):
        return CompareResult(
            status="fuzzy_match",
            detail="numeric formatting difference",
        )

    # Mismatch -- produce diff
    diff_lines = list(difflib.unified_diff(
        norm_ref.splitlines(keepends=True),
        norm_cand.splitlines(keepends=True),
        fromfile="reference",
        tofile="candidate",
        lineterm="",
    ))
    diff_text = "\n".join(diff_lines)
    return CompareResult(status="mismatch", diff=diff_text)


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    impl_name: str
    test_name: str
    status: str  # "pass", "fail", "skip", "error"
    output: str = ""
    stderr: str = ""
    returncode: int = 0
    detail: str = ""


def run_test_case(
    test: TestCase,
    impl: Implementation,
    timeout: int = 30,
) -> RunResult:
    """Execute a single test case against an implementation."""
    if not impl.available:
        return RunResult(
            impl_name=impl.name,
            test_name=test.name,
            status="skip",
            detail="implementation not available",
        )

    # Write journal to temp file
    tmpdir = tempfile.mkdtemp(prefix="parity_")
    journal_path = os.path.join(tmpdir, "test.dat")
    with open(journal_path, "w") as f:
        f.write(test.journal)

    # Write extra files
    for fname, content in test.extra_files.items():
        fpath = os.path.join(tmpdir, fname)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(content)

    # Build command
    cmd = list(impl.cmd) + ["-f", journal_path, test.command] + test.args

    try:
        result = subprocess.run(
            cmd,
            cwd=impl.cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return RunResult(
            impl_name=impl.name,
            test_name=test.name,
            status="error",
            detail="command not found",
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            impl_name=impl.name,
            test_name=test.name,
            status="error",
            detail="timeout",
        )
    except OSError as e:
        return RunResult(
            impl_name=impl.name,
            test_name=test.name,
            status="error",
            detail=str(e),
        )

    output = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        # Some commands (like print) may not be implemented
        return RunResult(
            impl_name=impl.name,
            test_name=test.name,
            status="error",
            output=output,
            stderr=stderr,
            returncode=result.returncode,
            detail=f"exit code {result.returncode}",
        )

    return RunResult(
        impl_name=impl.name,
        test_name=test.name,
        status="pass",
        output=output,
        stderr=stderr,
        returncode=0,
    )


# ---------------------------------------------------------------------------
# Parity matrix
# ---------------------------------------------------------------------------

@dataclass
class CellResult:
    status: str  # "pass", "fail", "skip", "error", "ref"
    compare: CompareResult | None = None
    output: str = ""
    detail: str = ""


def build_parity_matrix(
    tests: list[TestCase],
    impls: dict[str, Implementation],
    reference_impl: str = "ledger",
    timeout: int = 30,
) -> dict[str, dict[str, CellResult]]:
    """Run all tests against all available implementations and compare.

    Returns: {test_name: {impl_name: CellResult}}

    The reference implementation (default: "ledger") is compared against
    expect_contains if available; other implementations are compared to it.
    If the reference is unavailable, the first available implementation
    becomes the reference.
    """
    # Determine reference
    available_names = [n for n, im in impls.items() if im.available]
    if not available_names:
        # All skipped
        matrix: dict[str, dict[str, CellResult]] = {}
        for tc in tests:
            matrix[tc.name] = {
                n: CellResult(status="skip", detail="not available")
                for n in impls
            }
        return matrix

    if reference_impl not in available_names:
        reference_impl = available_names[0]

    # Run all tests
    all_results: dict[str, dict[str, RunResult]] = {}
    for tc in tests:
        all_results[tc.name] = {}
        for impl_name, impl in impls.items():
            all_results[tc.name][impl_name] = run_test_case(tc, impl, timeout)

    # Build matrix
    matrix = {}
    for tc in tests:
        matrix[tc.name] = {}
        ref_result = all_results[tc.name].get(reference_impl)

        for impl_name, impl in impls.items():
            run_res = all_results[tc.name][impl_name]

            if run_res.status == "skip":
                matrix[tc.name][impl_name] = CellResult(
                    status="skip", detail="not available"
                )
                continue

            if run_res.status == "error":
                matrix[tc.name][impl_name] = CellResult(
                    status="error",
                    output=run_res.output,
                    detail=run_res.detail,
                )
                continue

            if impl_name == reference_impl:
                # Check expect_contains if defined
                if tc.expect_contains and tc.expect_contains not in run_res.output:
                    matrix[tc.name][impl_name] = CellResult(
                        status="fail",
                        output=run_res.output,
                        detail=f"expected '{tc.expect_contains}' not found",
                    )
                else:
                    matrix[tc.name][impl_name] = CellResult(
                        status="ref",
                        output=run_res.output,
                    )
                continue

            # Compare to reference
            if ref_result is None or ref_result.status != "pass":
                # No reference to compare against; check expect_contains
                if tc.expect_contains and tc.expect_contains not in run_res.output:
                    matrix[tc.name][impl_name] = CellResult(
                        status="fail",
                        output=run_res.output,
                        detail=f"expected '{tc.expect_contains}' not found",
                    )
                else:
                    matrix[tc.name][impl_name] = CellResult(
                        status="pass",
                        output=run_res.output,
                    )
                continue

            cmp = compare_outputs(ref_result.output, run_res.output)
            if cmp.status in ("exact_match", "fuzzy_match"):
                matrix[tc.name][impl_name] = CellResult(
                    status="pass",
                    compare=cmp,
                    output=run_res.output,
                )
            else:
                # Check expect_contains as fallback
                if tc.expect_contains and tc.expect_contains in run_res.output:
                    matrix[tc.name][impl_name] = CellResult(
                        status="pass",
                        compare=cmp,
                        output=run_res.output,
                        detail="matches expected substring but differs from reference",
                    )
                else:
                    matrix[tc.name][impl_name] = CellResult(
                        status="fail",
                        compare=cmp,
                        output=run_res.output,
                        detail=cmp.diff[:500] if cmp.diff else "output mismatch",
                    )

    return matrix


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

STATUS_SYMBOLS = {
    "pass": "PASS",
    "fail": "FAIL",
    "skip": "SKIP",
    "error": "ERR ",
    "ref": "REF ",
}


def render_table(
    tests: list[TestCase],
    impls: dict[str, Implementation],
    matrix: dict[str, dict[str, CellResult]],
) -> str:
    """Render a human-readable parity matrix table."""
    impl_names = list(impls.keys())
    name_width = max(len(tc.name) for tc in tests) if tests else 10
    col_width = 8

    header = f"{'Test':<{name_width}}  " + "  ".join(
        f"{n:^{col_width}}" for n in impl_names
    )
    separator = "-" * len(header)

    lines = [separator, header, separator]
    for tc in tests:
        cells = []
        for impl_name in impl_names:
            cell = matrix.get(tc.name, {}).get(impl_name)
            if cell is None:
                cells.append(f"{'----':^{col_width}}")
            else:
                sym = STATUS_SYMBOLS.get(cell.status, "????")
                cells.append(f"{sym:^{col_width}}")
        line = f"{tc.name:<{name_width}}  " + "  ".join(cells)
        lines.append(line)

    lines.append(separator)

    # Summary
    summary: dict[str, dict[str, int]] = {}
    for impl_name in impl_names:
        summary[impl_name] = {"pass": 0, "fail": 0, "skip": 0, "error": 0, "ref": 0}
        for tc in tests:
            cell = matrix.get(tc.name, {}).get(impl_name)
            if cell:
                summary[impl_name][cell.status] = (
                    summary[impl_name].get(cell.status, 0) + 1
                )

    lines.append("")
    for impl_name in impl_names:
        s = summary[impl_name]
        total_run = s["pass"] + s["fail"] + s["error"] + s["ref"]
        lines.append(
            f"  {impl_name}: {s['pass']+s['ref']} pass, {s['fail']} fail, "
            f"{s['error']} error, {s['skip']} skip (of {len(tests)})"
        )

    return "\n".join(lines)


def matrix_to_serializable(
    matrix: dict[str, dict[str, CellResult]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Convert matrix to JSON-serializable form."""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for test_name, cells in matrix.items():
        result[test_name] = {}
        for impl_name, cell in cells.items():
            entry: dict[str, Any] = {
                "status": cell.status,
                "detail": cell.detail,
            }
            if cell.compare:
                entry["compare_status"] = cell.compare.status
                entry["compare_detail"] = cell.compare.detail
                if cell.compare.diff:
                    entry["diff"] = cell.compare.diff[:1000]
            result[test_name][impl_name] = entry
    return result


def save_report(
    tests: list[TestCase],
    impls: dict[str, Implementation],
    matrix: dict[str, dict[str, CellResult]],
    reports_dir: Path | None = None,
) -> Path:
    """Save parity report as timestamped JSON."""
    if reports_dir is None:
        reports_dir = REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    report_path = reports_dir / f"parity_{timestamp}.json"

    report = {
        "timestamp": timestamp,
        "implementations": {
            n: {"available": im.available} for n, im in impls.items()
        },
        "test_count": len(tests),
        "results": matrix_to_serializable(matrix),
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-implementation parity tests for muonledger",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Per-test timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--impl", action="append", dest="only_impls",
        help="Only test specific implementation(s)",
    )
    parser.add_argument(
        "--test", action="append", dest="only_tests",
        help="Only run specific test case(s) by name",
    )
    parser.add_argument(
        "--no-report", action="store_true",
        help="Skip saving JSON report",
    )
    parser.add_argument(
        "--report-dir", type=str, default=None,
        help="Directory for JSON reports",
    )
    args = parser.parse_args(argv)

    print("=== muonledger Cross-Implementation Parity Tests ===\n")

    # Discover implementations
    impls = get_implementations()
    print("Discovering implementations...")
    impls = discover_implementations(impls)

    if args.only_impls:
        impls = {k: v for k, v in impls.items() if k in args.only_impls}

    for name, impl in impls.items():
        status = "available" if impl.available else "not found"
        print(f"  {name}: {status}")
    print()

    available_count = sum(1 for im in impls.values() if im.available)
    if available_count == 0:
        print("No implementations available. Nothing to test.")
        return 1

    # Get test cases
    tests = get_test_cases()
    if args.only_tests:
        tests = [tc for tc in tests if tc.name in args.only_tests]
    print(f"Running {len(tests)} test cases across {available_count} implementation(s)...\n")

    # Build parity matrix
    matrix = build_parity_matrix(tests, impls, timeout=args.timeout)

    # Print table
    table = render_table(tests, impls, matrix)
    print(table)
    print()

    # Save report
    if not args.no_report:
        report_dir = Path(args.report_dir) if args.report_dir else REPORTS_DIR
        report_path = save_report(tests, impls, matrix, report_dir)
        print(f"Report saved to: {report_path}")

    # Exit code: 0 if no failures, 1 otherwise
    has_failures = any(
        cell.status == "fail"
        for cells in matrix.values()
        for cell in cells.values()
    )
    return 1 if has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
