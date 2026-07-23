---
name: token-efficient-backtest-workflow
description: Orchestrate V8 Python backtests and reviews without placing raw candles, full trades, equity curves, grids, or logs in LLM context. Use when running, comparing, diagnosing, or reporting a V8 backtest, especially for large datasets, many parameters, formal experiments, or token-cost reduction.
---

# Run Token-Efficient V8 Backtests

Use the LLM to define the experiment, invoke local code, inspect compact results, and explain findings. Use Python and DuckDB as the numerical engine.

## Workflow

1. Read `AGENTS.md` and select the existing `run_*` entry point. Record strategy, commit/dirty state, snapshot fingerprint, period, costs, leverage, seed, baseline, command, and acceptance metrics.
2. Run the smallest relevant tests first. Only the project's backtest Agent may run a formal full-period backtest.
3. Send normal computation to local Python. Redirect verbose output to an artifact log and keep the terminal handoff to status, duration, summary path, and at most five warnings.
4. Write each run to a new directory:

   ```text
   reports/<experiment>/<run-id>/
   ├── manifest.json
   ├── summary.json
   ├── report.md
   ├── trades.parquet
   ├── equity.parquet
   ├── diagnostics.parquet
   └── run.log
   ```

   Add `parameters.parquet` or `folds.parquet` only when the experiment creates them.
5. Put full tabular results in Parquet, machine-readable configuration and compact metrics/warnings in JSON, and conclusions in Markdown. Use Python with installed DuckDB `COPY ... FORMAT PARQUET` when a pandas Parquet engine is unavailable; do not add a dependency just for serialization.
6. Read `summary.json` and `report.md` first. Stop there when they answer the question.
7. When a warning needs evidence, query Parquet with Python/DuckDB and return aggregate counts plus a bounded sample, normally at most 20 rows and only necessary columns. Save the query and sample scope in diagnostics.
8. Verify the ledger, snapshot stability, expected files, row counts, and JSON validity locally. Never infer missing metrics from prose.

## Hard limits

- Never calculate candle-by-candle, trade-by-trade, equity-curve, factor, fold, or parameter-grid results in the LLM.
- Never paste complete raw candles, trades, equity curves, grids, DataFrames, or logs into the prompt or response.
- Never overwrite completed runs or source data. Never claim a formal run completed when only a smoke test ran.
- Prefer one summary read and one anomaly query over repeated broad file reads. Reuse a valid summary until its commit, configuration, or data fingerprint changes.

Finish with the verdict, core metrics and baseline deltas, no more than five warnings, checks run, exact artifact paths, and limitations.
