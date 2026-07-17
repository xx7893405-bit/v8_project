# Task Board

狀態：`ready`、`in_progress`、`blocked`、`done`、`cancelled`。只有 Manager 可更新本檔。

| ID | Status | Owner / worktree | Depends on | Ownership | Acceptance |
|---|---|---|---|---|---|
| MGR-001 | done | Manager / `codex/v8-modularization` | — | Manager skill、狀態檔、測試分類 | 31 tests；新 Manager 可從 repo 接管 |
| CTR-001 | ready | Engine / `codex/v8-engine-core` | MGR-001 | engine/strategy 共用契約與 core tests | 行為不變；完整測試與固定資料回歸通過 |
| DATA-001 | blocked | Data / `codex/v8-data-pipeline` | CTR-001 | feed adapters、同步、data tests | 統一 schema、時間與 micro-window 契約 |
| STR-001 | blocked | Strategies / `codex/v8-strategy-modules` | CTR-001 | BearS、V8、NFE 與策略測試 | 不再新增 engine 私有耦合；NFE 單一 owner |
| ENTRY-001 | blocked | Manager/integration | DATA-001, STR-001 | 正式入口、oracle、portfolio、live 串接 | CLI smoke、完整測試、相同快照回歸 |
| INT-001 | blocked | Manager/integration | ENTRY-001 | 分支整合與 checkpoint | 使用者確認後才更新 `main` 或遠端 |

## Current blockers

- CTR-001 開始前，需決定如何處理 `codex/param-opt` 的未提交 engine 修改。
- DATA-001 開始前，需決定是否先移植 `codex/strategy-admin-controls` 的 API feed 變更。
