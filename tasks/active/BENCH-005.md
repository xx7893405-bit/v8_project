```yaml
task_id: BENCH-005
title: Reproducible fidelity reports and formal corrected-engine comparison
status: done
owner: backtest
reviewer: audit
depends_on: [ENG-002, DATA-005]
allowed_read:
  - run_contract_strategy_comparison.py
  - strategy_engine.py
  - download_perpetual_history.py
  - ccxt_market_data.py
  - data/btcusdt_perp_1m_202101_present.manifest.json
  - reports/contract_benchmark/20260718_btcusdt_perp_risk5_lev20_ea28b7ca3c90c46b/summary.json
  - tests/analysis/**
allowed_write:
  - run_contract_strategy_comparison.py
  - tests/analysis/test_contract_strategy_comparison.py
  - reports/contract_fidelity/**
forbidden:
  - strategy_engine.py
  - backtest_config.py
  - execution_engine.py
  - run_live_trading.py
  - download_perpetual_history.py
  - ccxt_market_data.py
  - PROJECT_STATE.md
  - TASK_BOARD.md
inputs:
  base_commit: a51783e
  data_version: 5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965
  baseline_report: reports/contract_benchmark/20260718_btcusdt_perp_risk5_lev20_ea28b7ca3c90c46b/summary.json
outputs:
  - manifest.json
  - summary.json
  - report.md
  - trades.parquet
  - equity.parquet
  - diagnostics.parquet
  - run.log
done_when:
  - fidelity is the default and fails when historical mark/funding coverage is absent
  - explicit research profile remains runnable and labels fallback assumptions
  - manifest records Git revision dirty state command config data SHA period and baseline
  - headline MDD uses session equity_events and ending equity reconciles with balance
  - completed runs are immutable and all artifacts validate
  - analysis and full integration tests pass
  - formal research-profile candidate is compared with the frozen baseline on the same snapshot
limits:
  max_iterations: 8
  max_backtest_runs: 1
  max_files_modified: 2
  may_spawn_subagents: false
```
