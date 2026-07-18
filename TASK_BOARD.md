# Task Board

狀態：`ready`、`in_progress`、`blocked`、`done`、`cancelled`。只有 Manager 可更新本檔。

| ID | Status | Owner / worktree | Depends on | Ownership | Acceptance |
|---|---|---|---|---|---|
| MGR-001 | done | Manager / `codex/contract-backtest-parity` | — | 契約、狀態、ADR、整合 | rollback `b6556aa`；canonical 合約基準已記錄 |
| ENG-001 | in_progress | Engine / `codex/v8-engine-core` | MGR-001 | `strategy_engine.py`、`backtest_config.py`、`tests/core/**` | 保守同棒路徑；帳本含費用/funding/滑價；prefix invariance；core tests |
| DATA-001 | in_progress | Data / `codex/v8-data-pipeline` | MGR-001 | `market_data.py`、`api_market_data.py`、`ccxt_market_data.py`、`tests/data/**` | 永續合約；只收 closed candle；完整 resample；缺口/重複稽核；data tests |
| LIVE-001 | in_progress | Strategy/Live / `codex/v8-strategy-modules` | MGR-001 | `nfe*_strategy.py`、`execution_engine.py`、`run_live_trading.py`、`oracle_strategy_job.py`、strategy/integration tests | 增量事件；fill 後保護；TP1/BE/trailing parity；重啟不重複 |
| INT-001 | blocked | Manager / `codex/contract-backtest-parity` | ENG-001, DATA-001, LIVE-001 | 整合、完整驗證、baseline/candidate 報告 | 全測試；同快照比較；使用者確認前不合併 `main`／不推送 |

## Current blockers

- 合約資料完整窗口尚未確認；Data Agent 驗證前，績效回測只可視為診斷。
- 實際帳戶 fee tier 與歷史 funding dataset 尚未提供；先保留可注入契約及明確 fallback，不偽造精準成本。
- NFE V2 A／BearS 與 `param-opt` 的未提交 worktree 全數保留且禁止修改。
