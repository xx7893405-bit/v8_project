---
name: backtest-auditor
description: Audit the V8 Python backtest engine and reports for result distortion, including look-ahead, signal timing, fill semantics, costs, leverage, liquidation, metric correctness, baseline identity, and reproducibility. Use when the user asks whether a V8 backtest is trustworthy, requests a backtest audit, or changes backtest, strategy, data, execution, cost, or reporting logic.
---

# Audit V8 Backtests

Act as a read-only reviewer unless the user separately asks for fixes. Read `AGENTS.md`, the invoked `run_*` entry point, `backtest_config.py`, relevant strategy, feed, `strategy_engine.py`, tests, and only the compact report artifacts needed for the claim.

## Audit workflow

1. Freeze the experiment identity: Git commit and dirty state, command, strategy parameters, data path and fingerprint, market type, period, costs, leverage, seed, and baseline.
2. Trace signal timestamp to order creation, eligible fill bar, position management, exit, and ledger update. Reject same-bar knowledge that was unavailable at decision time.
3. Review feed integrity, closed-candle handling, spot/perpetual separation, resampling, warm-up, gaps, duplicates, and timezone alignment.
4. Review maker/taker fees, adverse slippage, funding direction and schedule, partial exits, liquidation, force close, and intrabar event priority.
5. Recompute selected ledger and headline metrics with local Python. Check PnL reconciliation, drawdown, annualization, trade count, win rate, profit factor, and concentration.
6. Require an unchanged baseline and identical non-target assumptions for comparisons. Flag weak sample size, missing OOS/walk-forward evidence, parameter instability, or cost sensitivity.
7. Report findings by `critical`, `high`, `medium`, or `low`, with file evidence, consequence, and the smallest verification or remediation.

Use focused tests such as `tests/core/test_execution_fidelity.py`, data contract tests, report tests, and `quick_regression_check.py` before any formal full-period run. Follow the project's rule that only the backtest Agent runs formal full-period backtests.

## Computation and artifact contract

- Never use the LLM to calculate candle-by-candle, trade-by-trade, equity-curve, or parameter-grid results. Call the repository's local Python code for every numeric result.
- Store complete tabular results such as trades, equity, diagnostics, and grids as Parquet; use Python with the installed DuckDB `COPY ... FORMAT PARQUET` path when no pandas Parquet engine is present. Store the run manifest and compact metrics/warnings in JSON, and the conclusions in Markdown.
- Default to reading `summary.json` and the Markdown report. Do not load complete candles, trades, equity, grids, or logs into context.
- When a summary exposes an anomaly, use Python or DuckDB to filter the relevant columns and time range, then inspect a bounded sample, normally at most 20 rows. Record the query and sample scope.
- Keep terminal output compact. Save full results under a new run ID; never overwrite a completed run or source data.

Finish with a trust verdict, evidence-backed findings, checks actually run, artifact paths, and untested risks. Do not claim a backtest passed when only code inspection or a smoke test was performed.
