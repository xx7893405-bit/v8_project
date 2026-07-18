# Project State

## Objective

升級合約策略回測系統，使 closed-candle 訊號、撮合事件、成本帳務與 paper/live 執行可重現且一致，並保留舊版回復點。

## Current phase

Phase 1：合約與時間契約已凍結；Engine、Data、Strategy/Live 分區實作。

## Verified baseline

- Rollback：`b6556aa`（`codex/v8-modularization`）；`main`／`v8.0.0` 仍為 `76f6ee4`。
- Integration：`codex/contract-backtest-parity`，從 `b6556aa` 建立。
- 31 項 unittest 通過。
- Canonical market：Binance USDT 永續 `BTC/USDT:USDT`，NFE V2，15m/1h，isolated，10,000 USD，risk-based 1%，最高 3x。
- 現行成本 baseline：maker 0.02%、taker 0.05%、entry/limit/stop/liq 滑價沿用既有設定；candidate 必須明列 funding 與 mark/last-price 契約。
- 合約 DuckDB 快照：2024-07-01 00:00 至 2026-07-10 01:10，共 199,420 根 1m；資料密度不足，完成缺口稽核前不得宣稱為完整兩年回測。
- 舊引擎診斷 baseline（資料指紋 `4bb323d849b703d1`，完整性未通過）：15m 13,293 bars、4 trades、2 missed、報酬 +0.5759%、最大回撤 -0.3350%、勝率 50.0%、profit factor 1.7215；只用於修正前後追蹤，不作績效結論。
- 對照指標：總報酬、最大回撤、交易數、勝率、profit factor；所有差異需可追溯至時間／成交／成本修正。

## Active branches and worktrees

- Manager/integration：`codex/contract-backtest-parity`
- Engine：`codex/v8-engine-core`
- Data：`codex/v8-data-pipeline`
- Strategy/Live：`codex/v8-strategy-modules`
- 保留中的其他工作：`codex/nfe-v2-a-bears-comparison`、`codex/nfe-v2-a-strategy`、`codex/nfe-v2-a-analysis`、`codex/param-opt`。

## Known conflicts

- NFE V2 A／BearS worktree 有進行中未提交修改，本輪禁止觸碰。
- `codex/param-opt` 有未提交的 `strategy_engine.py` 與研究腳本，本輪不採用、不覆蓋。
- 合約 1m 資料存在大量缺口；Data 任務需先產出完整性契約與可用窗口。

## Next checkpoint

三個 worker 各自提交互斥 ownership 變更後，Manager 依 Data → Engine → Strategy/Live 整合，執行完整測試、prefix invariance、closed-candle parity 與固定快照 baseline/candidate 對照。
