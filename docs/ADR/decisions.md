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

## ADR-007: Contract market is the canonical execution market

Status: Accepted

Decision: 正式回測、paper 與 live 以同一永續合約商品與契約規格為準；現貨資料只能作明確標示的 signal feed，必須透過 dual-market 契約處理基差，不得直接代替合約成交價。

Consequence: 手續費、funding、mark/last-price、contract size、槓桿、維持保證金與清算皆依合約市場建模。

## ADR-008: Closed-candle and conservative intrabar semantics

Status: Accepted

Decision: 只有完整收盤 K 線可產生確認訊號；訊號最早於收盤後執行。同棒事件若無更細資料證明路徑，採不高估績效的保守結果。

Consequence: 任意時間截斷資料的歷史 prefix 必須不變；未收 K、未確認 fill 與模糊 intrabar 路徑不得生成樂觀交易。
