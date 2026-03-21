# Parity Test Runner

Runs ledger `.test` files against an alternative binary and compares output to
the expected results embedded in each file.

## Quick start

```bash
python testing/parity/run_parity.py \
  --binary ./build/myledger \
  --tests 'vendor/ledger/test/baseline/*.test'
```

## Options

| Flag | Description |
|------|-------------|
| `--binary PATH` | Path to the ledger-compatible binary under test (required). |
| `--tests GLOB...` | One or more glob patterns matching `.test` files (required). |
| `--sourcepath DIR` | Root path substituted for `$sourcepath` in test commands. Defaults to two directories above each test file. |
| `--subset LIST` | Comma-separated filename prefixes to include, e.g. `cmd-balance,cmd-register`. |
| `--output-json FILE` | Write machine-readable JSON results to FILE. |
| `--timeout SECS` | Per-test timeout in seconds (default: 60). |
| `--columns N` | Value for the COLUMNS environment variable (default: 80). |
| `-v, --verbose` | Show passing/skipped tests and full diffs on failure. |

## Test file format

A `.test` file contains ledger journal data at the top, followed by one or more
test blocks:

```
2024/01/01 Payee
    Expenses:Food    $10.00
    Assets:Cash

test bal
              $10.00  Expenses:Food
             $-10.00  Assets:Cash
--------------------
                   0
end test

test reg --wide -> 1
__ERROR__
Some expected error message
end test
```

- `test <command>` starts a block; the command is passed to the binary.
- Expected stdout lines follow directly after the `test` line.
- `__ERROR__` separates expected stdout from expected stderr.
- `-> N` on the `test` line sets the expected exit code (default 0).
- `end test` closes the block.
- `$FILE` is replaced with the absolute path to the test file.
- `$sourcepath` is replaced with the configured source path.

If the command does not include `-f`, the test file itself is passed as
`-f <testfile>` automatically.

## JSON output

When `--output-json results.json` is used the output looks like:

```json
{
  "summary": { "total": 42, "pass": 40, "fail": 1, "skip": 1 },
  "results": [
    {
      "file": "/path/to/test.test",
      "line": 12,
      "command": "bal",
      "verdict": "PASS",
      "expected_exit_code": 0,
      "actual_exit_code": 0,
      "message": "",
      "stdout_diff": [],
      "stderr_diff": []
    }
  ]
}
```

## Exit code

The runner exits with **0** when all tests pass and **1** when any test fails.
