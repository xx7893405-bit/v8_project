# Architecture Decisions

## ADR-001: Stateless Manager

Status: Accepted

Decision: Manager 不保存對話狀態；每次先讀 `PROJECT_STATE.md`、`TASK_BOARD.md`、`AGENTS.md`、`docs/ADR/`、Git 與 worktree，再規劃或分派。

Consequence: 主管 thread 可隨時替換；repository、Git 與測試是唯一長期記憶。

## ADR-002: Exclusive worktree ownership

Status: Accepted

Decision: 每個寫入 worker 使用獨立 worktree 與互斥檔案 ownership；Manager 專責整合。

Consequence: 跨 ownership 的介面需求先回報，不由 worker 直接修改。

## ADR-003: Contracts before parallel implementation

Status: Accepted

Decision: 先凍結 engine/strategy 與 data feed 契約，再平行修改模組。

Consequence: `strategy_engine.py` 等熱點在契約階段只能有一個 owner。

## ADR-004: Minimal tests are not strategy entrypoints

Status: Accepted

Decision: 核心、資料、策略與整合測試放在 `tests/`；臨時 `run_*`、`analyze_*` 與生成物不作回歸基線。

Consequence: 拋棄式入口可重建，核心安全由小型、直接、可重現的測試保護。

## ADR-005: Fixed data snapshot for strategy comparisons

Status: Accepted

Decision: 策略比較固定資料指紋、期間、費率、滑價、槓桿與成交模型。

Consequence: 任一假設不同都必須揭露，不以單次高報酬直接判定優化成功。

## ADR-006: Automatic delegation threshold

Status: Accepted

Decision: 任務跨兩個以上獨立區塊時，Manager 自動分派最多三個平行 worker；單一區塊或高耦合工作直接處理或序列執行。

Consequence: 使用者不必維持永久主管 thread，但 Manager 必須維持互斥 ownership 與階段依賴。
