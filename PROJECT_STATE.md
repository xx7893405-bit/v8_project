# Project State

## Objective

將 V8 專案分成回測核心、資料、策略、分析與入口串接區塊，由無狀態 `v8-manager` 分階段協調多 Agent 修改與整合。

## Current phase

Phase 1：共用契約準備。

## Verified baseline

- `main` 與 `v8.0.0` 指向 `76f6ee4`。
- `codex/v8-modularization` 已包含最小測試分類與 Manager workflow。
- 31 項測試通過。
- V1→V4 快速回歸通過；資料指紋 `adcc5df0ab1e82ee`。
- 拋棄式研究入口與輸出暫存於 `/private/tmp/v8_project_disposable_20260717`。

## Active branches and worktrees

- Manager/integration: `codex/v8-modularization`
- Engine: `codex/v8-engine-core`
- Data: `codex/v8-data-pipeline`
- Strategies: `codex/v8-strategy-modules`
- Existing: `codex/ai-signal-webhook`, `codex/param-opt`, `codex/strategy-admin-controls`

## Known conflicts

- `codex/param-opt` 有未提交的 `strategy_engine.py` 修改。
- `codex/strategy-admin-controls` 與資料工作可能同時涉及 `api_market_data.py`。

## Next checkpoint

凍結 engine／strategy 與 data feed 契約；共用契約完成前，不允許 strategy 與 engine worker 同時修改核心介面。
