```yaml
task_id: DATA-005
title: Read-only integrity gate and fidelity market-data schema
status: in_progress
owner: data
reviewer: audit
depends_on: [MGR-007]
allowed_read:
  - download_perpetual_history.py
  - ccxt_market_data.py
  - data/btcusdt_perp_1m_202101_present.manifest.json
  - docs/CONTRACT_BACKTEST_DATA.md
  - tests/data/**
allowed_write:
  - download_perpetual_history.py
  - ccxt_market_data.py
  - tests/data/**
forbidden:
  - data/*.duckdb
  - network_download
  - strategy_engine.py
  - execution_engine.py
  - run_contract_strategy_comparison.py
  - PROJECT_STATE.md
  - TASK_BOARD.md
  - full_period_backtest
inputs:
  base_commit: b7cfc20
  data_version: 5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965
outputs:
  - tested commit on codex/fidelity-data
done_when:
  - audit can run without downloading or writing the database
  - manifest SHA and complete integrity checks fail fast
  - mark-price and funding schemas are defined without fabricating data
  - fidelity mode cannot silently fall back when required series are absent
  - focused data tests pass
limits:
  max_iterations: 8
  max_backtest_runs: 0
  max_files_modified: 4
  may_spawn_subagents: false
```
