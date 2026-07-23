```yaml
task_id: LIVE-003
title: Protected fills, managed flat convergence, and live fill ledger
status: done
owner: execution
reviewer: audit
depends_on: [MGR-007]
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
  - backtest_config.py
  - market_data.py
  - run_contract_strategy_comparison.py
  - PROJECT_STATE.md
  - TASK_BOARD.md
  - live_orders
  - full_period_backtest
inputs:
  base_commit: b7cfc20
outputs:
  - tested commit on codex/fidelity-execution
done_when:
  - any confirmed filled quantity is protected before successful state persistence or safely failed
  - strategy flat reconciles only tagged managed orders and positions
  - fills are persisted idempotently with exchange id quantity average price fee and timestamp
  - partial fill restart and stale-order tests pass
limits:
  max_iterations: 8
  max_backtest_runs: 0
  max_files_modified: 5
  may_spawn_subagents: false
```
