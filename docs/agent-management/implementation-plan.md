# Implementation Plan

## Phase 0: Baseline and workspace hygiene

Status: Complete

- 建立 `v8.0.0` 與整合分支。
- 分類最小測試並固定資料指紋。
- 隔離拋棄式研究入口與輸出。

## Phase 1: Contracts

Status: Ready

- 指定單一 owner 處理 engine／strategy contract。
- 固定 data feed schema、時間索引、時區、排序與 micro-window 行為。
- 補足契約測試，不改變既有交易結果。

Exit criteria:

- 共用介面不再由多個 Agent 同時修改。
- 31 項以上完整測試通過。
- 固定資料快速回歸不惡化。

## Phase 2: Parallel module work

Status: Pending

- Engine Agent：撮合、成本、風控、持倉與時間安全。
- Data Agent：CSV/API/CCXT/DuckDB 與同步流程。
- Strategy Agent：BearS、V8、NFE，僅依賴已凍結介面。

## Phase 3: Analysis and entry integration

Status: Pending

- 分析輸出使用隔離 artifact 目錄。
- 統一正式策略入口、CLI、oracle、portfolio 與 live 串接。

## Phase 4: Integration checkpoint

Status: Pending

- 依 contract → data/engine → strategies → entry/analysis 順序整合。
- 執行完整測試與相同資料快照的 baseline/candidate 回測。
- 經使用者確認後才更新 `main`、標籤或遠端。
