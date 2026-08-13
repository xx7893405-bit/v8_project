---
name: strategy-chart-review
description: Visualize and audit V8 trading-strategy behavior with bounded, representative candlestick samples and persist causal event indexes for later replay. Use during early strategy discussion, when validating HTF/LTF structure, signals, entries, average price, stops, targets, exits, or when the user explicitly asks to render a period from an existing backtest. During a formal full backtest, create indexes but do not render charts automatically.
---

# Review V8 Strategies with Charts

Use charts as a bounded validation aid, not as statistical proof. Keep formal computation in local Python or DuckDB and never ask the LLM to inspect raw candles trade by trade.

## Choose the operating mode

### Preliminary visual review

- Use only while discussing or diagnosing strategy logic.
- Run a smoke test or bounded slice containing at most 10 completed trades.
- Select representative cases rather than only winners or visually clean setups. Cover long, short, profitable, losing, stop-loss, take-profit, structure-invalidated, and anomalous cases when available.
- If fewer than 10 trades exist, inspect all of them.
- State that the sample cannot establish profitability or statistical significance.

### Formal full backtest

- Do not render charts automatically.
- Let only the V8 `backtest` Agent execute the formal full-period run.
- Persist an event/chart index for every trade so any period can be rendered later without rerunning the full backtest.
- Keep full tables in Parquet, manifests and compact warnings in JSON, and conclusions in Markdown.

### Explicit post-backtest rendering

- Render only after the user explicitly requests a trade, date range, month, regime, or anomaly from an existing run.
- Resolve the request through the saved run ID, manifest, data fingerprint, and event index.
- Use the original run configuration and data snapshot. Do not silently substitute current data or recompute with changed parameters.
- If the requested scope is large, summarize the matching count first and render representative cases or aggregate time windows unless the user explicitly requests every chart.

## Draw the strategy state

For a multi-timeframe strategy, default to a synchronized dual-chart layout:

1. Show HTF candles, confirmed major Swing points, BOS/MSS events, protected levels, and the mutually exclusive state `LONG`, `SHORT`, or `NEUTRAL`.
2. Show LTF candles and the SMC events that determine the retrace and entry.
3. Mark signal time, order-submission time, eligible fill time, every fill, position average price, quantity changes, stop-loss, take-profit levels, partial exits, final exit, and exit reason.
4. Distinguish `pivot_time` from `confirmed_at`. A marker may be drawn at the historical extreme only if its later confirmation time is also visible.
5. Mark whether each price is a decision-time value, simulated fill, or hindsight-only annotation.
6. Include symbol, market type, HTF/LTF periods, timezone, data fingerprint, run ID, fees, slippage, leverage, and sizing method in metadata rather than crowding the plot.

Never use P3 or a third trendline touch to determine HTF direction unless a strategy explicitly defines it. For the accepted V2 prototype, use confirmed major-Swing close BOS for direction, MSS for return to `NEUTRAL`, and require an opposite BOS before reversing direction.

## Persist a reusable event index

Write `chart_index.parquet` under the immutable run directory with one or more rows per trade. Include at least:

- run ID, trade ID, symbol, market type, HTF, LTF, timezone, and direction;
- signal, order, fill, scale-in, average-price change, stop, target, partial-exit, final-exit, and structure-event timestamps;
- suggested HTF and LTF chart start/end times;
- module names, trigger reasons, exit reason, and representative-sample tags;
- data snapshot fingerprint, Git commit/dirty state, strategy-parameter hash, execution-configuration hash, and cache-manifest ID.

The event index may contain realized PnL, win/loss, and exit outcomes for research and exact replay. Never use those hindsight fields to generate signals, select the universe, prune dates, or accelerate a new backtest.

## Separate safe caches from hindsight artifacts

Maintain distinct layers:

1. **Certified market data**: immutable source candles and snapshot fingerprint.
2. **Causal feature cache**: resampled closed candles, ATR, indicators, confirmed Swing, BOS/MSS, and module state.
3. **Strategy-signal cache**: reuse only when every strategy input and parameter is identical.
4. **Event/chart index**: research, diagnostics, chart lookup, and exact replay of the same run only.
5. **Execution and portfolio results**: fills, quantities, margin, liquidation, fees, funding, equity, and PnL.

Reuse layers 1-2 only when their complete identity matches. Recompute layer 3 when any strategy parameter changes. Recompute layer 5 whenever capital, leverage, risk percentage, fixed amount, sizing rule, pyramiding, tick/lot rounding, minimum notional, fees, slippage, funding, market impact, order type, fill timing, intrabar priority, margin, or liquidation rules change.

Do not reuse a prior trade ledger merely because symbol and date range match. Different leverage or order size can change rounding, fees, slippage, liquidation, available margin, fills, and later signals.

## Enforce causal cache identity

Key each reusable cache by canonical values that include:

- dataset SHA-256 and certification/version;
- symbol, market type, timezone, timeframe, resampling and closed-bar policy;
- requested range plus warm-up range;
- module/indicator name, implementation version or Git commit, and canonical parameter hash;
- missing-data policy and numerical-library/runtime versions when they can affect results.

Store `event_time` and `available_at` for every causal feature. Permit the backtest to read a value only when `available_at <= decision_time`. For resampled data, expose an HTF bar only after that HTF bar closes. Never backfill a later-confirmed Swing, BOS, label, regime, or trade result into earlier timestamps.

Treat a missing identity field, dirty incompatible code, hash mismatch, incomplete warm-up, or changed data snapshot as a cache miss. Rebuild instead of guessing compatibility.

## Verify cached and uncached equivalence

Before trusting a new or changed cache path:

1. Run a small deterministic slice without cache.
2. Run the identical slice from a cold cache build.
3. Run it again from a warm cache.
4. Compare feature timestamps and values, state transitions, signals, eligible fills, trade ledger, and summary metrics.
5. Require exact timestamp/state/trade equality and documented numerical tolerance only where floating-point serialization requires it.
6. Reject and invalidate the cache on any unexplained difference.

Record the comparison command, seed, manifests, row counts, hashes, and mismatch diagnostics. Never claim cache correctness from faster runtime alone.

## Report the result

Lead with whether the chart matches the intended strategy behavior. Then report the sample rule, exact run/data identity, visible discrepancies, causality checks, and artifact paths. Clearly distinguish visual plausibility from backtested profitability.
