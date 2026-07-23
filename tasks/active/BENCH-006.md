```yaml
task_id: BENCH-006
title: Prevent false fidelity claims and validate baseline identity
status: done

owner: fidelity_report
reviewer: fidelity_final_audit
depends_on: [BENCH-005, AUD-001]

allowed_read:
  - run_contract_strategy_comparison.py
  - tests/analysis/test_contract_strategy_comparison.py
  - reports/contract_benchmark/20260718_btcusdt_perp_risk5_lev20_ea28b7ca3c90c46b/summary.json
allowed_write:
  - run_contract_strategy_comparison.py
  - tests/analysis/test_contract_strategy_comparison.py
forbidden:
  - strategy_engine.py
  - ccxt_market_data.py
  - execution_engine.py
  - data/**
  - full_period_backtest

inputs:
  base_commit: 76156eb
  data_version: 5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965
  universe_version: binance-usdtm-btcusdt
  config_hash: risk5-lev20-standard
  random_seed: null

outputs:
  - verified reporting commit

done_when:
  - Fidelity profile fails closed even if coverage tables exist until the engine consumes historical mark and funding.
  - Research remains explicit and visibly labeled.
  - Baseline market, snapshot, periods, and cost assumptions are validated before comparison.
  - Full unit test suite passes without another formal full-period run.

limits:
  max_iterations: 3
  max_backtest_runs: 0
  max_files_modified: 2
  may_spawn_subagents: false
```
