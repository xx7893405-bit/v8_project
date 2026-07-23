---
name: optimization-robustness
description: Validate V8 strategy parameter searches and optimization claims with chronological train/OOS splits, walk-forward testing, parameter-neighborhood stability, cost sensitivity, multiple-testing awareness, and reproducible local computation. Use for sweeps, parameter tuning, strategy optimization, selecting a candidate, or reviewing possible overfitting.
---

# Validate V8 Optimization Robustness

Read `AGENTS.md`, the strategy and run entry point, the baseline report, the search definition, and all train/test period boundaries. Use existing sweep scripts only as starting points; do not treat the best row as proof.

## Review workflow

1. Freeze the baseline, data fingerprint, search space, objective, constraints, periods, costs, leverage, and seed before seeing candidate results.
2. Keep chronology intact. Use train/OOS or rolling walk-forward splits; purge or embargo overlapping labels and holding windows when leakage is possible.
3. Evaluate all declared candidates locally. Preserve failed and invalid configurations instead of silently dropping them.
4. Compare return, max drawdown, trade count, win rate, profit factor, Sharpe/Sortino when correctly annualized, turnover, and concentration. Prefer constraints and multi-metric evidence over a single score.
5. Test neighboring parameters, subperiods, long/short sides, regimes, and realistic fee/slippage/funding stresses. Reject isolated peaks and severe OOS degradation.
6. Account for repeated trials and researcher degrees of freedom. Keep the final holdout untouched until the decision rule is fixed.
7. Recommend the simplest stable region or the unchanged baseline. Do not automatically apply the winning parameters.

## Computation and artifact contract

- Never let the LLM compute a parameter grid, walk-forward folds, metrics, or Monte Carlo samples. Call local Python for all numerical work.
- Store the complete candidate grid, fold results, equity diagnostics, and sensitivity tables as Parquet; store search space, snapshot, seed, selected rule, metrics, and warnings as JSON; store the decision and limitations as Markdown. Use installed DuckDB from Python for Parquet when needed.
- Read only the compact JSON summary and Markdown decision by default. Do not load a full grid, equity curve, or trade set into context.
- If an anomaly or candidate needs inspection, use Python or DuckDB to select a bounded neighborhood or failed fold, normally no more than 20 rows.
- Never overwrite an earlier optimization run. Use a unique experiment/run ID and retain the exact command.

Finish with `accept`, `reject`, or `insufficient evidence`, baseline deltas, OOS degradation, stability evidence, trial-count caveats, artifacts, and remaining risks.
