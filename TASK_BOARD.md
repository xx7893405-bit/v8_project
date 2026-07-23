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
| MGR-004 | done | Manager / `codex/v2a-bears-entry-quality` | MGR-002 | 單變因契約、ownership、整合與狀態 | rollback `405049c`；不帶入 POC；固定 snapshot／成本／風險 |
| STR-004 | done | V2A Agent / `codex/entry-v2a` | MGR-004 | `nfe_v2_a_strategy.py` 與專屬 tests | `2f807bd`；預設不變；stop gate／target revalidation 獨立 |
| STR-005 | done | BearS Agent / `codex/entry-bears` | MGR-004 | `bears_strategy.py` 與專屬 tests | `a540964`；預設不變；Fib／Triple filters 與 counters |
| ANL-003 | done | Analysis Agent / `codex/entry-analysis` | MGR-004 | entry-quality runner、analysis tests、獨立 reports | `fbcef28` + `da23051`；七組、兩期間、grouped quality metrics |
| BENCH-003 | done | Manager / `codex/v2a-bears-entry-quality` | STR-004, STR-005, ANL-003 | 整合、完整測試、正式回測與判定 | 75 tests；Triple-only 通過初階數值門檻，其餘淘汰／診斷 |
| MGR-005 | done | Manager / `codex/spot-vs-perp-2021-2026` | BENCH-003 | paired-market 契約、ownership、整合與狀態 | rollback `5000021`；策略 defaults；共同 timestamps／成本／風險 |
| DATA-004 | done | Data Agent / `codex/spot-perp-data` | MGR-005 | paired 1m loader、共同索引、完整 resample、audit tests | `e1a197e` → `59c08dc`；共同 2,896,605 rows；各 TF 索引相同 |
| ANL-004 | done | Analysis Agent / `codex/spot-perp-analysis` | MGR-005, DATA-004 | 六組 runner、basis／trade-overlap／grouped reports | `4479cb9` → `5316c44`；六組與 grouped reports 完成 |
| BENCH-004 | done | Manager / `codex/spot-vs-perp-2021-2026` | DATA-004, ANL-004 | 整合、完整測試、正式回測與因果判讀 | 78 tests；snapshot `d67917d4724ab20d`；六份 ledger 與 final balance 相符 |
| MGR-006 | done | Manager / `codex/spot-vs-perp-2021-2026` | — | Hermes 協調入口、任務模板、四個專案 Agent 設定 | TOML／JSONL 解析與 diff-check 通過；未改交易行為 |
| MGR-007 | done | Manager / `codex/backtest-live-fidelity` | MGR-006 | 契約、狀態、ADR、整合 | `ed3a3b1`；105 tests；Final Audit 無 Critical／High |
| ENG-002 | done | Engine / `codex/fidelity-engine` | MGR-007 | `strategy_engine.py`、`backtest_config.py`、`tests/core/**` | `fdd6aca` → integration `a51783e`；完整整合測試通過 |
| LIVE-003 | done | Execution / `codex/fidelity-execution` | MGR-007 | `execution_engine.py`、`run_live_trading.py`、live execution tests | `9a58276` → integration `76156eb`；保護、flat convergence、idempotent fill ledger |
| DATA-005 | done | Data / `codex/fidelity-data` | MGR-007 | downloader／DuckDB feed／`tests/data/**` | `e52e185` → integration `b28cb60`；真實 snapshot identity 與 18 tests 通過 |
| BENCH-005 | done | Backtest / `codex/fidelity-report` | ENG-002, DATA-005 | comparison runner、analysis tests、獨立 fidelity reports | `abe5eb7`；research-only artifact；MTM MDD 與 ending equity 對帳 |
| LIVE-004 | done | Execution / `codex/fidelity-execution-ownership` | LIVE-003, AUD-001 | existing-position ownership gate、execution tests | `5f806f8` → integration `9bd95d2`；無 managed 證據不碰既有倉位 |
| BENCH-006 | done | Backtest / `codex/fidelity-report` | BENCH-005, AUD-001 | fidelity capability gate、baseline identity tests | `5698d77` → integration `ed3a3b1`；unsupported fidelity 與 baseline mismatch 均 fail closed |
| AUD-001 | done | Audit / 唯讀 | LIVE-003, BENCH-005 | 時序、資料、成本、live parity 稽核 | HEAD `ed3a3b1` 無 Critical／High；41 focused tests |
| SHADOW-001 | blocked | Execution / testnet-shadow | LIVE-003, AUD-001 | testnet／paper 執行證據 | scripted lifecycle 通過；自然訊號觀察；需外部執行授權與時間 |

## Current blockers

- 舊 `data/market_data.duckdb` 有 864,811 分鐘缺口且已停用；正式評估須使用新的標準合約資料路徑。
- 實際帳戶 fee tier、歷史 funding 與 mark-price dataset 尚未提供；不偽造精準成本。
- 歷史 funding／mark-price 尚未下載；DATA-005 僅建立 schema 與嚴格門檻，正式 fidelity run 前需另行取得資料。
- historical mark/funding 尚未實際接入策略引擎；因此 `fidelity` 刻意 fail closed，目前只有明確標示的 `research_only` 報告。
- Live ownership、保護與 ledger 已完成程式層驗收，但 testnet/shadow lifecycle 尚需外部執行授權與觀察時間，仍不得宣稱 production-ready。
- NFE V2 A／BearS 與 `param-opt` 的未提交 worktree 全數保留且禁止修改。
