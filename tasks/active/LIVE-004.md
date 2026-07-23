```yaml
task_id: LIVE-004
title: Fail closed on unowned existing exchange positions
status: done

owner: fidelity_execution
reviewer: fidelity_final_audit
depends_on: [LIVE-003, AUD-001]

allowed_read:
  - execution_engine.py
  - run_live_trading.py
  - tests/core/test_execution_engine.py
  - tests/integration/test_live_execution_contract.py
  - tests/integration/test_run_live_incremental.py
allowed_write:
  - execution_engine.py
  - run_live_trading.py
  - tests/core/test_execution_engine.py
  - tests/integration/test_live_execution_contract.py
  - tests/integration/test_run_live_incremental.py
forbidden:
  - strategy_engine.py
  - ccxt_market_data.py
  - run_contract_strategy_comparison.py
  - live_orders
  - full_period_backtest

inputs:
  base_commit: 76156eb
  data_version: 5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965
  universe_version: binance-usdtm-btcusdt
  config_hash: null
  random_seed: null

outputs:
  - verified execution commit

done_when:
  - Existing same-side and same-size position without exchange-side managed evidence is not touched.
  - A verified managed resume can continue protection reconciliation.
  - Snapshot does not advance on ownership failure.
  - Full unit test suite passes.

limits:
  max_iterations: 3
  max_backtest_runs: 0
  max_files_modified: 5
  may_spawn_subagents: false
```
