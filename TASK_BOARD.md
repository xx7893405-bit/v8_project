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
| DATA-003 | done | Data / `codex/contract-benchmark-data` | DATA-001 | 新永續合約資料檔、下載稽核；不覆蓋既有 DB/CSV | `4f39765` + `96ce976`；2,915,392 rows；0 duplicates/gaps |
| STR-002 | done | Strategy / `codex/contract-benchmark-strategy` | LIVE-001 | `nfe_v2_a_strategy.py`、A tests | `474a2bf`；A 6 tests；5m close 後延遲 90m |
| ANL-001 | done | Analysis / `codex/contract-benchmark-analysis` | MGR-001 | comparison runner、analysis tests、獨立 reports | `0536133` + `e42e9cc`；risk 5%、20x；兩期間與必要指標 |
| BENCH-001 | done | Manager / `codex/contract-v2-a-bears-benchmark` | DATA-003, STR-002, ANL-001 | 整合、完整測試、正式回測與 handoff | 65 tests；snapshot `ea28b7ca3c90c46b`；報告完成；未 push |
| MGR-002 | done | Manager / `codex/contract-v2-a-bears-benchmark` | BENCH-001 | 標準資料路徑、manifest、使用文件與 Git 版本化 | DuckDB 保持 ignored；預設入口及跨機器重建流程已驗證 |

## Current blockers

- 舊 `data/market_data.duckdb` 有 864,811 分鐘缺口且已停用；正式評估須使用新的標準合約資料路徑。
- 實際帳戶 fee tier、歷史 funding 與 mark-price dataset 尚未提供；不偽造精準成本。
- Live fill ledger 與 flat-position convergence 尚未完成，禁止直接宣稱 production-ready。
- NFE V2 A／BearS 與 `param-opt` 的未提交 worktree 全數保留且禁止修改。
