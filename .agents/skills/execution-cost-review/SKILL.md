---
name: execution-cost-review
description: Review V8 order fills and trading-cost realism across entries, exits, partial fills, same-bar events, slippage, maker/taker fees, funding, leverage, liquidation, and market impact assumptions. Use when execution or cost code changes, simulated and live results diverge, or a user asks whether V8 fills and net PnL are realistic.
---

# Review V8 Execution and Costs

Read `AGENTS.md`, `backtest_config.py`, relevant sections of `strategy_engine.py`, `execution_engine.py` when live parity matters, the run entry point, and `tests/core/test_execution_fidelity.py`.

## Review workflow

1. Map every order type to decision time, first eligible fill, reference price, adverse slippage direction, fee class, expiry, and rejection rule.
2. Check ambiguous intrabar paths. Verify the 1m micro feed is used when available and the conservative fallback does not grant impossible TP/SL ordering.
3. Reconcile entry fee, partial-exit fee, remaining-exit fee, realized PnL, balance delta, and final balance. Detect double charging or omitted costs.
4. Verify maker/taker classification, long/short symmetry, limit slippage, stop and market slippage, force-close handling, and liquidation fees.
5. Verify funding sign, cadence, price basis, remaining size, and partial holding periods. State that fixed fallback funding is not historical funding when applicable.
6. Test cost sensitivity around the configured values. Flag assumptions missing spread, depth, participation limits, latency, partial fills, or size-dependent impact.
7. Compare backtest semantics with the live execution client without changing live state or placing orders.

## Computation and artifact contract

- Never have the LLM simulate candles, fills, fees, or trade ledgers row by row. Execute local Python tests and bounded reconciliation scripts.
- Store full fill, trade-ledger, and sensitivity tables as Parquet; store configuration, reconciliation totals, and warnings as JSON; store the evidence-backed review as Markdown. Use Python plus installed DuckDB for Parquet output when needed.
- Read only summary JSON and Markdown by default. Query full artifacts only after an aggregate mismatch identifies a specific trade, event type, or time range.
- Extract a bounded anomaly sample with Python or DuckDB, normally at most 20 rows and only the necessary columns. Never paste a full trade ledger into context.
- Write outputs under a unique run ID and keep raw data and earlier reports unchanged.

Finish with net-PnL reconciliation status, unrealistic assumptions ordered by expected impact, checks run, artifact paths, and the smallest next experiment.
