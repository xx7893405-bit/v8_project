# Task Template

```yaml
task_id: TASK-0000
title: Short task title
status: ready

owner: agent-name
reviewer: null
depends_on: []

allowed_read:
  - path/to/input/**
allowed_write:
  - path/to/output/**
forbidden:
  - path/outside/ownership/**
  - full_period_backtest

inputs:
  base_commit: null
  data_version: null
  universe_version: null
  config_hash: null
  random_seed: null

outputs:
  - artifacts/TASK-0000/summary.json

done_when:
  - expected result is verified

limits:
  max_iterations: 6
  max_backtest_runs: 0
  max_files_modified: 5
  may_spawn_subagents: false
```

完成交接只回報：Task ID、狀態、修改檔案、測試、核心發現、風險、產出路徑與建議的下一個 Owner。不要附完整日誌、DataFrame、交易明細或冗長推理。
