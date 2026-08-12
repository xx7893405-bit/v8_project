# ADR-010: Canonical immutable research run artifacts

Status: Accepted for Phase 1

Decision:

- V8 research runs use `run-artifact/v1` and `metrics/v1`.
- A completed run lives in a unique directory created with no-overwrite semantics.
- The manifest records an aware creation time, run identity, strategy/config identity, data snapshot identity, Git revision, period, cost assumptions, leverage assumptions and canonical relative artifact references.
- Canonical headline metrics are `return_pct`、`max_drawdown_pct`、`trades`、`win_rate_pct`、`profit_factor`、`final_balance`.
- Compact `summary.json` contains the same reviewable provenance and canonical metrics, but never embeds raw candles or full trades、equity、orders.
- `summary.md` and deterministic `review.md` are rendered from the compact summary object only. External AI review is not part of Phase 1.
- Trades、equity and diagnostics remain referenced Parquet files. Orders are explicitly marked unavailable when the runner does not emit an order ledger.
- Artifact references are run-directory-relative POSIX paths; absolute paths and parent traversal are invalid.
- Research UI is a read-only artifact consumer. It must not invoke strategy/backtest execution or recalculate canonical metrics.

Consequence:

Existing runners adopt the contract one vertical slice at a time. Phase 1 changes only report packaging for the contract comparison runner; strategy、execution、cost and metric-calculation semantics remain frozen. Existing completed reports are not migrated or overwritten. Run List、Compare、Search、Equity Viewer、Notebook、Trade Inspector、Timeline and external AI review remain dependency tickets after Phase 1.
