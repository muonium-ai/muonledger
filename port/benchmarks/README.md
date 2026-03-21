# muonledger Performance Benchmarks

Benchmark scripts for comparing Python and Rust implementations of muonledger.

## Quick Start

```bash
# Generate benchmark journal files
python generate_journal.py --generate-all --output-dir .

# Run all benchmarks (Python + Rust)
python run_benchmarks.py

# Run Python-only benchmarks
python run_benchmarks.py --python-only

# Run Rust-only benchmarks
python run_benchmarks.py --rust-only
```

## Scripts

### `generate_journal.py`

Generates synthetic ledger journal files with realistic transactions.

```bash
# Generate a single file
python generate_journal.py --count 10000 --output bench_10k.ledger

# Generate all standard sizes (1K, 10K, 100K, 1M)
python generate_journal.py --generate-all --output-dir ./journals

# Use a specific random seed
python generate_journal.py --count 1000 --seed 123 --output test.ledger
```

Generated journals include:
- Sequential dates spanning multiple years
- Random payees from a pool of ~50 common payees
- Random accounts from ~30 accounts (Expenses, Income, Assets, Liabilities)
- Realistic amounts ($1-$5000)
- Mixed transaction states (80% unmarked, 10% cleared, 10% pending)
- Occasional tags, notes, and multi-posting transactions

### `bench_python.py`

Python-specific benchmark that imports muonledger modules directly.

```bash
python bench_python.py --file bench_1k.ledger --iterations 5
python bench_python.py --file bench_10k.ledger --json
```

Measures:
- **parse**: Time to parse the journal file into memory
- **balance**: Time to run the balance report
- **register**: Time to run the register report
- **total**: Wall-clock time for all operations

### `run_benchmarks.py`

Main benchmark runner that tests both implementations.

```bash
# Default: 1K, 10K, 100K with 3 iterations
python run_benchmarks.py

# Custom sizes and iterations
python run_benchmarks.py --sizes 100 1000 5000 --iterations 5

# Output as JSON
python run_benchmarks.py --json --output results.json

# Reuse generated journals
python run_benchmarks.py --journal-dir ./journals
```

## What Is Measured

| Operation | Description |
|-----------|-------------|
| parse     | Time to read and parse the journal file |
| balance   | Time to compute and format the balance report |
| register  | Time to compute and format the register report |
| total     | Total wall-clock time for all operations |

Each operation is run multiple times (default: 3 iterations). Results include:
- **Mean**: Average time across iterations
- **Median**: Middle value (less sensitive to outliers)
- **Min**: Best-case time (least OS interference)

## Expected Output Format

```
==============================================================================
MUONLEDGER BENCHMARK RESULTS
==============================================================================

--- Python 1k ---
  File: /tmp/muonbench_xyz/bench_1k.ledger
  Iterations: 3

  Operation        Mean     Median        Min
  --------------------------------------------
  parse          0.0523s    0.0510s    0.0498s
  balance        0.0012s    0.0011s    0.0010s
  register       0.0045s    0.0044s    0.0042s
  total          0.0580s    0.0565s    0.0550s
```

## Notes

- Benchmarks use a fixed random seed (42) for reproducible journal generation.
- The Rust benchmark measures end-to-end command time (includes parse + report).
- For Rust, ensure `cargo build --release` completes before running benchmarks.
- The 1M transaction benchmark may take significant time; start with smaller sizes.
