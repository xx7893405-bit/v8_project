# 專案協作規範

## 專案目的

本專案用於交易策略開發、量化研究、歷史資料回測與結果驗證。所有變更應以結果可重現、比較公平及避免未來資料洩漏為優先。

## 工作與溝通習慣

- 使用繁體中文說明工作內容、假設、風險與結果；程式碼名稱依既有專案慣例。
- 動手前先閱讀相關策略、回測入口、設定與測試，優先沿用現有結構。
- 採最小可行變更，避免未要求的重構、新依賴或抽象層。
- 不覆蓋、不刪除使用者既有變更；發現不相關的工作區異動時保留原狀。
- 對資料區間、週期、交易成本、槓桿或策略假設不確定時，先清楚列出假設；會實質改變結果時先詢問確認。
- 報告先寫結論，再列重要數據、驗證方式、限制與檔案位置。

## V8 Manager 協調流程

- 使用者點名 Manager／主管／多 Agent，或任務同時影響兩個以上核心區塊時，主 Agent 必須使用 `.agents/skills/v8-manager/SKILL.md`。
- Manager 先判定任務規模：唯讀詢問、單一已知區塊且不改變交易行為／資料／介面／Git 狀態者視為小問題，只查最少必要證據並直接簡短回答，不建立計畫、任務、分支、worktree 或 Agent；涉及上述變更、跨區塊、資料下載、正式回測或需分階段復原者視為大任務，才啟動完整流程。若檢查後才發現需擴大，須先告知使用者。
- Manager 可依該技能自動建立或選用隔離 worktree，並分派最多三個互不重疊的執行 Agent；相依工作採階段式順序執行。
- 每個寫入 Agent 必須有明確 ownership、禁止修改範圍、固定介面、驗收測試與交付 commit。
- Manager 採無狀態模式；大任務開始必須先讀取 `PROJECT_STATE.md`、`TASK_BOARD.md`、`AGENTS.md`、`docs/ADR/`、最新 commits 與所有 worktree 狀態，完成前不得修改或分派。
- Manager 專責整合、完整驗證及維護 `PROJECT_STATE.md`、`TASK_BOARD.md`、`docs/ADR/`；執行 Agent 不得自行修改管理狀態或共用契約。
- 專案檔案、Git 狀態、測試與可重現回測是事實來源；對話上下文只作輔助。

### Hermes 最小協調介面

- Hermes 是主管角色，不是額外服務；沿用 `.agents/skills/v8-manager/SKILL.md` 的無狀態 Manager 流程。
- `PROJECT_STATE.md` 與 `TASK_BOARD.md` 仍是唯一狀態來源；`coordination/PROJECT_STATE.md` 與 `coordination/TASKS.md` 只提供入口，不複製內容。
- 正式實驗索引記錄於 `coordination/EXPERIMENTS.jsonl`；大型報表、交易明細與完整日誌只保存路徑，不寫入索引或主管摘要。
- 任務使用 `tasks/TASK_TEMPLATE.md`，每項任務只有一個 Owner，並明列可讀、可寫、禁止範圍、輸入版本、輸出與停止條件。
- 專案自訂 Agent 位於 `.codex/agents/`：`strategy`、`data`、`backtest`、`audit`。只有互相獨立且邊界明確的工作才委派；結果只回傳短摘要與產出路徑。
- 正式全期間回測只能由 `backtest` Agent 執行；其他 Agent 只可執行單元測試、smoke test 或明確限定的小型資料切片。
- `audit` Agent 預設唯讀；跨 ownership 問題建立 dependency task，不直接跨區修改。

### Token Cost Analyzer

- 每個 Agent 每次執行都必須記錄：input tokens、output tokens、執行時間、cache hits、讀取檔案、修改檔案及預估成本；若供應商未提供精確數值，須標示估算方式，不得將估算值當成實際值。
- Manager 每日彙整 Token 使用報告，至少列出各 Agent 的上述指標與合計，並標示最高成本 Agent、重複 Prompt、重複檔案讀取、可利用 Cache 的機會及具體最佳化建議。
- Agent 應避免重複載入相同 Context 或原始資料；已有可信且仍有效的摘要時優先讀取摘要，只在驗證、摘要失效或任務確實需要完整細節時重讀原始檔案。
- Manager 應以降低重複 Context 讀取為首要最佳化方向，並在每日報告中追蹤改用摘要、共用快取或縮小讀取範圍後的 Token 與成本變化。

## 專案級回測 Skills

- 以下 Skills 只安裝於 `.agents/skills/`，不得複製到全域 skills 目錄。使用者明確點名 `$skill-name` 時必須讀取對應 `SKILL.md`；描述符合時也應主動套用。
- `$backtest-auditor`：審查回測可信度、時間順序、指標與可重現性。觸發例：「稽核這份回測是否失真」。
- `$data-integrity-review`：審查資料快照、缺口、重複、未收盤 K 線、時區、重採樣與市場混用。觸發例：「正式回測前檢查資料」。
- `$execution-cost-review`：審查成交順序、滑價、maker/taker、funding、部分出場與強平。觸發例：「檢查費用與成交是否過度樂觀」。
- `$optimization-robustness`：審查參數搜尋、walk-forward、OOS、穩定區域與成本敏感度。觸發例：「驗證這次最佳化有沒有 overfit」。
- `$factor-research-review`：審查因子時間可得性、洩漏、增量價值、換手與跨區間穩定性。觸發例：「審查新 POC 因子」。
- `$token-efficient-backtest-workflow`：以本地 Python/DuckDB 執行大量運算，只讓 Agent 讀摘要與必要的異常樣本。執行、比較或診斷正式回測時預設搭配使用。
- 所有上述 Skills 均不得讓 LLM 逐根 K 線、逐筆交易或逐組參數計算；完整表格保存為 Parquet，設定與摘要保存為 JSON，結論保存為 Markdown。Agent 預設只讀 `summary.json` 與報告，發現異常後才以 Python/DuckDB 查詢最多 20 筆必要樣本。

## 變更前確認

開始修改前確認：

- 目標策略、版本及預期改善指標。
- 使用的市場、商品、K 線週期、資料來源與回測期間。
- 初始資金、倉位、槓桿、手續費、滑價及資金費率設定。
- 是否可能產生 look-ahead bias、資料洩漏、重複訊號或不合理成交。
- 現有工作區狀態及受影響的程式、設定、測試與報表。

## 大範圍變更與 Git 分版

若變更涉及多個核心檔案、策略規則或回測引擎、資料格式、執行流程，或預期難以一次審查與回復，視為大範圍變更。此時必須：

1. 先提出計畫，列出目標、影響範圍、實作步驟、驗證方式與風險。
2. 等待使用者確認計畫後再修改。
3. 從目前基準建立獨立 Git 分支，分支名稱使用 `codex/<主題>`。
4. 以可審查的提交保存版本；未經明確要求，不自行推送遠端、合併或建立 PR。

小型、單一目的且容易回復的變更可直接進行，但仍須完成必要驗證。

## 策略優化與對照回測

### 合約策略標準資料

- 合約策略評估一律優先使用 `data/btcusdt_perp_1m_202101_present.duckdb`；不得以現貨資料或有已知缺口的舊 `data/market_data.duckdb` 代替。
- 執行前核對 `data/btcusdt_perp_1m_202101_present.manifest.json` 與本機 diagnostic，確認市場為 Binance USDT-M `BTC/USDT:USDT`、`market_type=swap`、只含已收盤 1m K 線，且無重複與缺口。
- 資料更新使用 `python download_perpetual_history.py`；更新後必須重新稽核並記錄截止時間、筆數、SHA-256 與回測報告的 snapshot fingerprint，不得覆蓋舊報告。
- V2、A、BearS 的正式公平比較使用 `python run_contract_strategy_comparison.py`；預設為 risk-based `risk_pct=5%`、槓桿上限 `20x`。若改動設定，報告須明列差異，不得與標準結果混稱。
- DuckDB 本體維持 Git ignored。跨機器若需重現同一快照，從 artifact/object storage 取得後以 manifest SHA-256 驗證；若只需最新評估，可在目標機器用下載器重建。
- 完整操作與目前限制見 `docs/CONTRACT_BACKTEST_DATA.md`；歷史 funding、mark-price 與持倉中 equity 尚未整合時，必須在結論中揭露。

凡是修改進出場、過濾條件、停損停利、倉位、槓桿、參數或其他會影響交易結果的邏輯，都必須和修改前版本進行對照回測：

- 保留修改前版本作為 baseline，不以新結果覆蓋舊報表。
- 新舊版本使用相同資料快照、回測期間、商品、週期、初始資金、費率、滑價、槓桿與成交模型。
- 除策略本身欲比較的變數外，其餘設定保持一致；若無法一致，須明確揭露差異。
- 至少比較總報酬、最大回撤、交易次數、勝率、盈虧比或 profit factor；可用時補充 Sharpe、Sortino 與分年度／分市場表現。
- 檢查結果是否由少數交易、單一行情區間或過度擬合造成。
- 記錄執行命令、設定、資料範圍、隨機種子（若有）及報表位置，確保可重現。
- 不因單次回測績效較高就判定優化成功；若風險惡化或樣本不足，須如實標示。

## 變更後確認

- 執行與變更範圍相符的最小測試、語法檢查或回測。
- 確認沒有未來資料洩漏、時間索引錯位、重複計算或意外改動預設參數。
- 檢查 Git diff，確保只包含本次需求。
- 回報修改內容、驗證結果、baseline 對照結果（若適用）、已知限制及尚未執行事項。
- 不聲稱未實際執行的測試或回測已通過。
