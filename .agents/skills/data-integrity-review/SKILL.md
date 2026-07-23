---
name: data-integrity-review
description: Review V8 market-data snapshots, loaders, resampling, and temporal alignment for duplicates, gaps, unclosed candles, timezone errors, schema drift, spot/perpetual mixing, and leakage. Use for dataset audits, feed changes, download or synchronization changes, unexplained backtest differences, or before a formal V8 backtest.
---

# Review V8 Data Integrity

Read `AGENTS.md`, `docs/CONTRACT_BACKTEST_DATA.md`, the selected feed, its downloader or synchronizer, manifest, and matching tests. Treat the Binance USDT-M `BTC/USDT:USDT` 1m DuckDB snapshot named by `AGENTS.md` as the default contract-strategy source.

## Review workflow

1. Identify exchange, symbol, market type, interval, UTC/open-time semantics, requested period, database path, manifest, row range, and SHA-256/fingerprint.
2. Run the existing local audit path, including `download_perpetual_history.py --audit` where applicable. Verify uniqueness, monotonic order, expected interval, gaps, OHLCV validity, and that the last candle was closed at ingestion time.
3. Trace each derived timeframe. Check aggregation boundaries, labels, closed-bar availability, warm-up rows, forward filling, joins, shifts, and as-of direction.
4. Confirm signal and execution feeds are intentionally separated and aligned. Reject silent spot/perpetual substitution or post-hoc duplicate removal that hides conflicting rows.
5. Compare the manifest and report fingerprint before and after a run. Stop if the snapshot changes during computation.
6. Classify gaps and missing fields by whether the engine rejects, skips, fills, or proceeds. State how each policy can bias results.

## Computation and artifact contract

- Never ask the LLM to inspect or calculate across candles one by one. Run local Python, SQL, `audit_datetime_index`, `audit_database`, and feed contract tests.
- Store complete row-level diagnostics and extracted integrity tables as Parquet, the data manifest and compact audit summary as JSON, and the review conclusion as Markdown. Use the installed DuckDB from Python to write Parquet if pandas lacks a Parquet engine.
- Read only the JSON summary and Markdown review by default. Do not place the full OHLCV dataset or a full gap table in model context.
- Investigate an anomaly by querying only the affected columns and bounded interval with Python or DuckDB, normally at most 20 example rows plus aggregate counts.
- Preserve source data and completed audits. Write a new run-specific output directory and record every query or command used.

Finish with data fitness (`pass`, `conditional`, or `fail`), snapshot identity, critical anomalies, affected backtests, checks run, artifacts, and remaining limitations.
