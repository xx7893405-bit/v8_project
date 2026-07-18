# Task Board

狀態：`ready`、`in_progress`、`blocked`、`done`、`cancelled`。只有 Manager 可更新本檔。

| ID | Status | Owner / worktree | Depends on | Ownership | Acceptance |
|---|---|---|---|---|---|
| MGR-001 | done | Manager / `codex/contract-backtest-parity` | — | 契約、狀態、ADR、整合 | rollback `b6556aa`；canonical 合約基準已記錄 |
| ENG-001 | done | Engine / `codex/v8-engine-core` | MGR-001 | `strategy_engine.py`、`backtest_config.py`、`tests/core/**` | `8b6904a` + `8819deb`；15 core tests |
| DATA-001 | done | Data / `codex/v8-data-pipeline` | MGR-001 | `market_data.py`、`api_market_data.py`、`ccxt_market_data.py`、`tests/data/**` | `61dfbc3`；7 data tests；缺口已量化 |
| LIVE-001 | done | Strategy/Live / `codex/v8-strategy-modules` | MGR-001 | NFE V1-V4、execution、live/API/paper entry、strategy/integration tests | `962e5b7` + `e3f5ebf`；closed-bar 增量與 fill-aware 保護 |
| INT-001 | done | Manager / `codex/contract-backtest-parity` | ENG-001, DATA-001, LIVE-001 | 整合、完整驗證、baseline/candidate 報告 | 56 tests；prefix invariant；同指紋對照完成；未合併／未 push |
| DATA-002 | blocked | 未分派 | DATA-001 | 回補 swap 1m、funding、mark price | 補齊 864,811 分鐘缺口並更新至當前；需資料下載授權 |
| LIVE-002 | blocked | 未分派 | LIVE-001, DATA-002 | fill ledger、flat convergence、testnet shadow | 實際 fill 回寫；flat 自動收斂；無裸倉／無重複；需新一輪計畫確認 |
| DATA-003 | in_progress | Data / `codex/contract-benchmark-data` | DATA-001 | 新永續合約資料檔、下載稽核；不覆蓋既有 DB/CSV | 2021-01-01 至最後 closed 1m；0 duplicates；gaps 明列；指紋與命令 |
| STR-002 | in_progress | Strategy / `codex/contract-benchmark-strategy` | LIVE-001 | `nfe_v2_a_strategy.py`、A tests | A=5m signal＋close 後 90m release；與升級 engine 相容；無 look-ahead |
| ANL-001 | in_progress | Analysis / `codex/contract-benchmark-analysis` | MGR-001 | comparison runner、analysis tests、獨立 reports | V2/A/BearS 同 snapshot/config；全期＋2026-07；return/MDD/trades/win/PF |
| BENCH-001 | blocked | Manager / `codex/contract-v2-a-bears-benchmark` | DATA-003, STR-002, ANL-001 | 整合、完整測試、正式回測與 handoff | 指紋一致；完整測試；兩期間結果；不覆蓋舊報表、不 push |

## Current blockers

- 合約資料有 864,811 分鐘缺口且已過期，績效結果只可視為診斷。
- 實際帳戶 fee tier、歷史 funding 與 mark-price dataset 尚未提供；不偽造精準成本。
- Live fill ledger 與 flat-position convergence 尚未完成，禁止直接宣稱 production-ready。
- NFE V2 A／BearS 與 `param-opt` 的未提交 worktree 全數保留且禁止修改。
