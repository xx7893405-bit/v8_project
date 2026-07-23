---
name: factor-research-review
description: Review V8 trading factors and signal features for timestamp availability, look-ahead or target leakage, implementation correctness, incremental value, turnover, concentration, regime stability, and reproducible local evaluation. Use when adding or changing a factor, feature, filter, labeling rule, ML input, POC/order-flow signal, or factor research report.
---

# Review V8 Factor Research

Read `AGENTS.md`, the factor implementation and every caller, the source-feed contract, strategy integration point, baseline report, and relevant tests. Separate factor quality from the profitability of the full strategy.

## Review workflow

1. Define the factor value, source fields, timestamp, earliest availability, lookback, warm-up, missing-value rule, normalization, and expected trading use before reviewing results.
2. Trace every shift, rolling window, resample, join, label, and forward return. Reject centered windows, backward joins to future observations, closed-bar violations, or preprocessing fit on the full sample.
3. Test deterministic examples and boundary cases locally. Confirm the production strategy consumes the same value evaluated by research code.
4. Compare an unchanged baseline with factor-only ablation under identical data, costs, leverage, and execution semantics.
5. Measure coverage, signal frequency, turnover, trade overlap, incremental trades, concentration, long/short behavior, subperiods, regimes, and OOS/walk-forward stability. Use IC or predictive metrics only when their horizon and sampling are valid for the factor.
6. Stress thresholds and neighboring definitions. Flag a factor whose benefit comes from a tiny subset, one regime, implicit parameter mining, or omitted costs.
7. Keep descriptive exploration separate from a claim that the factor improves a tradable strategy.

## Computation and artifact contract

- Never make the LLM calculate factor values, forward returns, correlations, trades, or candles row by row. Run the V8 Python pipeline for all numeric results.
- Store complete factor values, labels, ablation trades, and diagnostic tables as Parquet; store definitions, snapshot, metrics, and warnings as JSON; store the research verdict as Markdown. Use the installed DuckDB from Python for Parquet output when pandas has no engine.
- Read only summary JSON and Markdown by default. Do not load complete feature matrices, candles, or trades into context.
- Investigate anomalies with a Python/DuckDB query over the smallest relevant columns and date range, normally at most 20 rows.
- Preserve raw data and earlier reports. Use unique run IDs and record code revision, command, periods, costs, and seeds.

Finish with factor validity, incremental evidence, leakage verdict, OOS stability, artifacts, and the next falsification test. Do not recommend deployment from in-sample improvement alone.
