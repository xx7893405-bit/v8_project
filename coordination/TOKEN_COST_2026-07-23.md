# Token Cost Report — 2026-07-23

Exact provider token, cache-hit, and monetary-cost telemetry was unavailable for all Agents. No estimate is presented as an actual value.

| Agent | Elapsed | Files read | Files modified | Token/cache/cost |
|---|---:|---:|---:|---|
| Engine | unavailable | scoped Engine/tests | 2 | actual unavailable |
| Data | unavailable | scoped Data/tests and one snapshot audit | scoped Data/tests | actual unavailable |
| Execution | about 30 minutes across amendments | scoped Execution/tests | 5 | actual unavailable |
| Backtest | about 32 minutes including one formal run | 8 then 6 scoped files | 2 | actual unavailable |
| Audit | unavailable | about 20 scoped files | 0 | actual unavailable |
| Manager | unavailable | management state, summaries, diffs | management state only | actual unavailable |

Formal computation stayed local. The Agent read `summary.json`, `manifest.json`, reports, and at most targeted samples; it did not place raw candles, 591 full trades, or 93,614 equity events into model context.

Highest likely cost areas were repeated Execution amendments and audit context reconstruction. Future optimization: reuse this completed state summary, keep Parquet as the detail layer, query at most 20 exceptions, and avoid rereading unchanged Engine/Data files.
