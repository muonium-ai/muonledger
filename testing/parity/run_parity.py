#!/usr/bin/env python3
"""Parity test runner for ledger-compatible binaries.

Parses .test files in the format used by ledger's test suite and runs them
against an arbitrary binary, comparing actual output to expected output.
Useful for verifying that an alternative implementation produces identical
results to the reference ledger binary.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from difflib import unified_diff
from enum import Enum, auto
from pathlib import Path
from typing import TextIO


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Verdict(Enum):
    PASS = auto()
    FAIL = auto()
    SKIP = auto()


@dataclass
class TestCase:
    """A single ``test … end test`` block inside a .test file."""

    command: str
    expected_stdout: list[str] = field(default_factory=list)
    expected_stderr: list[str] = field(default_factory=list)
    expected_exit_code: int = 0
    source_file: Path = field(default_factory=lambda: Path())
    line_number: int = 0


@dataclass
class TestResult:
    """Outcome of running one TestCase."""

    test: TestCase
    verdict: Verdict
    actual_stdout: list[str] = field(default_factory=list)
    actual_stderr: list[str] = field(default_factory=list)
    actual_exit_code: int = 0
    stdout_diff: list[str] = field(default_factory=list)
    stderr_diff: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class FileSummary:
    """Aggregated results for a single .test file."""

    path: Path
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.SKIP)


# ---------------------------------------------------------------------------
# .test file parser
# ---------------------------------------------------------------------------

class TestFileParser:
    """Reads a .test file and yields ``TestCase`` objects."""

    def __init__(self, path: Path, sourcepath: Path) -> None:
        self.path = path.resolve()
        self.sourcepath = sourcepath.resolve()
        self._line_num = 0

    # Variable substitution -------------------------------------------------

    def _transform(self, line: str) -> str:
        return (
            line
            .replace("$FILE", str(self.path))
            .replace("$sourcepath", str(self.sourcepath))
        )

    # Parsing ----------------------------------------------------------------

    def parse(self) -> list[TestCase]:
        """Return all test cases found in the file."""
        cases: list[TestCase] = []
        self._line_num = 0

        with open(self.path, encoding="utf-8") as fh:
            line = self._next(fh)
            while line is not None:
                if line.startswith("test "):
                    case, line = self._read_block(fh, line)
                    if case is not None:
                        cases.append(case)
                    # _read_block already consumed the next line after
                    # ``end test``, so do *not* call _next again here.
                    continue
                line = self._next(fh)

        return cases

    def _next(self, fh: TextIO) -> str | None:
        raw = fh.readline()
        if raw == "":
            return None
        self._line_num += 1
        return raw

    def _read_block(self, fh: TextIO, first_line: str) -> tuple[TestCase | None, str | None]:
        """Parse a ``test … end test`` block.

        Returns ``(TestCase, next_line)`` where *next_line* is the first
        line read after ``end test`` (or ``None`` at EOF).
        """
        start_line = self._line_num
        command_part = first_line[5:]  # strip leading "test "

        # Check for ``-> N`` exit-code suffix on the command line.
        exit_code = 0
        match = re.match(r"(.*?)\s*->\s*(\d+)\s*$", command_part)
        if match:
            command_part = match.group(1)
            exit_code = int(match.group(2))

        command = self._transform(command_part.rstrip("\n"))
        if not command.strip():
            print(
                f"WARNING: {self.path}:{start_line}: empty command after "
                f"'test' directive",
                file=sys.stderr,
            )
            # Skip to end-of-block or EOF.
            line = self._next(fh)
            while line is not None and line.rstrip() != "end test":
                line = self._next(fh)
            return None, self._next(fh)

        tc = TestCase(
            command=command,
            expected_exit_code=exit_code,
            source_file=self.path,
            line_number=start_line,
        )

        in_error = False
        line = self._next(fh)
        while line is not None:
            stripped = line.rstrip("\n")
            if stripped == "end test":
                return tc, self._next(fh)
            if line.startswith("__ERROR__"):
                in_error = True
                line = self._next(fh)
                continue
            transformed = self._transform(line)
            if in_error:
                tc.expected_stderr.append(transformed)
            else:
                tc.expected_stdout.append(transformed)
            line = self._next(fh)

        # Reached EOF without ``end test``.
        print(
            f"WARNING: {self.path}:{start_line}: unterminated test block "
            f"(missing 'end test' before end of file)",
            file=sys.stderr,
        )
        return None, None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class ParityRunner:
    """Executes test cases against a binary and collects results."""

    def __init__(
        self,
        binary: Path,
        sourcepath: Path,
        *,
        timeout: int = 60,
        columns: int = 80,
    ) -> None:
        self.binary = binary.resolve()
        self.sourcepath = sourcepath.resolve()
        self.timeout = timeout
        self.columns = columns

    def run_file(self, path: Path) -> FileSummary:
        summary = FileSummary(path=path)

        if path.stat().st_size == 0:
            print(f"WARNING: empty test file: {path}", file=sys.stderr)
            return summary

        parser = TestFileParser(path, self.sourcepath)
        cases = parser.parse()

        if not cases:
            print(f"WARNING: no test blocks found in: {path}", file=sys.stderr)
            return summary

        for tc in cases:
            result = self._run_case(tc)
            summary.results.append(result)

        return summary

    def _build_command(self, tc: TestCase) -> str:
        """Assemble the full shell command.

        Mirrors the logic in ``RegressTests.py``: if the test command does
        not already contain ``-f ``, the test file itself is supplied as
        the input journal.
        """
        cmd = tc.command
        if "-f " in cmd:
            # User-specified file; just prepend the binary.
            full = f'"{self.binary}" {cmd}'
            if re.search(r"-f\s+(-|/dev/stdin)(\s|$)", cmd):
                # Reads from stdin – not supported in this runner yet.
                return full
        else:
            full = f'"{self.binary}" -f "{tc.source_file}" {cmd}'
        return full

    def _run_case(self, tc: TestCase) -> TestResult:
        cmd = self._build_command(tc)

        env = os.environ.copy()
        # Unless the command already sets --columns, force a default so
        # that output is deterministic.
        if "--columns" not in tc.command:
            env["COLUMNS"] = str(self.columns)

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                test=tc,
                verdict=Verdict.FAIL,
                message=f"TIMEOUT after {self.timeout}s",
            )

        actual_stdout = proc.stdout.decode("utf-8", errors="replace").splitlines(keepends=True)
        actual_stderr = proc.stderr.decode("utf-8", errors="replace").splitlines(keepends=True)

        stdout_diff = list(
            unified_diff(tc.expected_stdout, actual_stdout, lineterm="")
        )
        stderr_diff = list(
            unified_diff(tc.expected_stderr, actual_stderr, lineterm="")
        )

        exit_ok = proc.returncode == tc.expected_exit_code
        stdout_ok = not stdout_diff
        stderr_ok = not stderr_diff

        if stdout_ok and stderr_ok and exit_ok:
            verdict = Verdict.PASS
            message = ""
        else:
            verdict = Verdict.FAIL
            parts: list[str] = []
            if not stdout_ok:
                parts.append("stdout mismatch")
            if not stderr_ok:
                parts.append("stderr mismatch")
            if not exit_ok:
                parts.append(
                    f"exit code {proc.returncode} != expected {tc.expected_exit_code}"
                )
            message = "; ".join(parts)

        return TestResult(
            test=tc,
            verdict=verdict,
            actual_stdout=actual_stdout,
            actual_stderr=actual_stderr,
            actual_exit_code=proc.returncode,
            stdout_diff=stdout_diff,
            stderr_diff=stderr_diff,
            message=message,
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_human(summaries: list[FileSummary], *, verbose: bool = False) -> None:
    total_pass = total_fail = total_skip = 0

    for fs in summaries:
        for r in fs.results:
            match r.verdict:
                case Verdict.PASS:
                    total_pass += 1
                    if verbose:
                        print(f"  PASS  {fs.path.name} : {r.test.command.strip()}")
                case Verdict.FAIL:
                    total_fail += 1
                    print(f"  FAIL  {fs.path.name}:{r.test.line_number} : "
                          f"{r.test.command.strip()}")
                    if r.message:
                        print(f"        {r.message}")
                    if verbose:
                        for d in r.stdout_diff[2:]:  # skip --- / +++ header
                            print(f"        stdout> {d.rstrip()}")
                        for d in r.stderr_diff[2:]:
                            print(f"        stderr> {d.rstrip()}")
                case Verdict.SKIP:
                    total_skip += 1
                    if verbose:
                        print(f"  SKIP  {fs.path.name} : {r.test.command.strip()}")

    total = total_pass + total_fail + total_skip
    print()
    print(f"Total: {total}  |  Pass: {total_pass}  |  Fail: {total_fail}  |  Skip: {total_skip}")
    if total_fail:
        print("RESULT: FAIL")
    else:
        print("RESULT: PASS")


def _result_to_dict(r: TestResult) -> dict:
    return {
        "file": str(r.test.source_file),
        "line": r.test.line_number,
        "command": r.test.command.strip(),
        "verdict": r.verdict.name,
        "expected_exit_code": r.test.expected_exit_code,
        "actual_exit_code": r.actual_exit_code,
        "message": r.message,
        "stdout_diff": r.stdout_diff,
        "stderr_diff": r.stderr_diff,
    }


def _write_json(summaries: list[FileSummary], dest: Path) -> None:
    total_pass = total_fail = total_skip = 0
    all_results: list[dict] = []

    for fs in summaries:
        for r in fs.results:
            all_results.append(_result_to_dict(r))
            match r.verdict:
                case Verdict.PASS:
                    total_pass += 1
                case Verdict.FAIL:
                    total_fail += 1
                case Verdict.SKIP:
                    total_skip += 1

    payload = {
        "summary": {
            "total": total_pass + total_fail + total_skip,
            "pass": total_pass,
            "fail": total_fail,
            "skip": total_skip,
        },
        "results": all_results,
    }

    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    print(f"JSON report written to {dest}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_test_files(patterns: list[str], subset: str | None) -> list[Path]:
    """Expand glob patterns and optionally filter by subset prefixes."""
    paths: list[Path] = []
    for pat in patterns:
        paths.extend(Path(p) for p in sorted(glob.glob(pat, recursive=True)))

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(p)

    if subset:
        prefixes = [s.strip() for s in subset.split(",") if s.strip()]
        unique = [
            p for p in unique if any(p.stem.startswith(pfx) for pfx in prefixes)
        ]

    return unique


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ledger parity tests against an alternative binary.",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        required=True,
        help="Path to the ledger-compatible binary under test.",
    )
    parser.add_argument(
        "--tests",
        nargs="+",
        required=True,
        help="Glob pattern(s) matching .test files to run.",
    )
    parser.add_argument(
        "--sourcepath",
        type=Path,
        default=None,
        help="Root source path for $sourcepath substitution (defaults to "
             "parent of the directory containing each test file).",
    )
    parser.add_argument(
        "--subset",
        default=None,
        help="Comma-separated list of filename prefixes to include "
             "(e.g. 'cmd-balance,cmd-register').",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write machine-readable JSON results to FILE.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-test timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=80,
        help="Value for COLUMNS env variable (default: 80).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show passing/skipped tests and full diffs on failure.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.binary.exists():
        print(f"ERROR: binary not found: {args.binary}", file=sys.stderr)
        return 1

    test_files = _collect_test_files(args.tests, args.subset)
    if not test_files:
        print("ERROR: no test files matched the given patterns/subset.", file=sys.stderr)
        return 1

    # Determine a default sourcepath if none was provided.
    default_sourcepath = args.sourcepath

    summaries: list[FileSummary] = []
    for tf in test_files:
        sourcepath = default_sourcepath or tf.resolve().parent.parent.parent
        runner = ParityRunner(
            binary=args.binary,
            sourcepath=sourcepath,
            timeout=args.timeout,
            columns=args.columns,
        )
        summaries.append(runner.run_file(tf))

    _print_human(summaries, verbose=args.verbose)

    if args.output_json:
        _write_json(summaries, args.output_json)

    has_failures = any(
        r.verdict is Verdict.FAIL for fs in summaries for r in fs.results
    )
    return 1 if has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
