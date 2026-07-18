# Project State

## Objective

以單變因候選改善 NFE V2 A 與 BearS 的進場品質，並在相同合約 snapshot、成本、5% risk 與 20x 上限下公平比較。

## Current phase

Phase 6 進行中：V2A 停損／延遲重驗證與 BearS Fib／Triple 候選分階段實作。

## Verified baseline

- Rollback：`b6556aa`（`codex/v8-modularization`）；`main`／`v8.0.0` 仍為 `76f6ee4`。
- Integration：`codex/contract-backtest-parity`，從 `b6556aa` 建立。
- Benchmark：`codex/contract-v2-a-bears-benchmark`，rollback 為 `3d28f79`。
- Entry quality：`codex/v2a-bears-entry-quality`，rollback 為 `405049c`；POC 實驗不納入。
- 本輪固定設定：Binance USDT-M `BTCUSDT`；2021-01-01 至最後完整 1m；另跑 2026-07-01 至同截止；10,000 USD、risk-based 5%、最高 20x、maker 0.02%、taker 0.05%、相同滑價與 funding fallback。
- 新合約資料：`data/btcusdt_perp_1m_202101_present.duckdb`，2,915,392 rows，2021-01-01 00:00～2026-07-18 13:51 UTC，duplicates=0、gaps=0、SHA-256 `5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965`。
- 標準比較入口預設讀取上述 DuckDB；Git 保存 `data/btcusdt_perp_1m_202101_present.manifest.json` 與 `docs/CONTRACT_BACKTEST_DATA.md`，資料庫本體維持 ignored。
- 正式報告：`reports/contract_benchmark/20260718_btcusdt_perp_risk5_lev20_ea28b7ca3c90c46b/`；snapshot fingerprint `ea28b7ca3c90c46b`。
- 全期結果：V2 +210.2279% / MDD -36.5458% / 89 trades / win 40.4494% / PF 1.8409；A -69.9109% / -74.6945% / 282 / 37.5887% / 0.7642；BearS -93.2480% / -96.3746% / 216 / 17.1296% / 0.5058。
- 2026-07 MTD：V2 +3.9231%（1 trade）；A -5.1183%（1 trade）；BearS -10.2648%（2 trades）。
- 進場品質診斷：V2A stop<0.10% 共 97 trades、win 8.25%、PF 0.006；BearS Fib 0.5／0.618／0.786 的 PF 分別 0.855／0.345／0.208，Triple PF 0.728、Double 0.368。
- 65 項 unittest、py_compile、diff-check、snapshot identity 與 trade-ledger/final-balance 一致性通過。
- 31 項 unittest 通過。
- Canonical market：Binance USDT 永續 `BTC/USDT:USDT`，NFE V2，15m/1h，isolated，10,000 USD，risk-based 1%，最高 3x。
- 現行成本 baseline：maker 0.02%、taker 0.05%、entry/limit/stop/liq 滑價沿用既有設定；candidate 必須明列 funding 與 mark/last-price 契約。
- 合約 DuckDB 快照：2024-07-01 00:00 至 2026-07-10 01:10，共 199,420 根 1m；資料密度不足，完成缺口稽核前不得宣稱為完整兩年回測。
- 舊引擎 baseline（資料指紋 `4bb323d849b703d1`，完整性未通過）：15m 13,293 bars、4 trades、2 missed、報酬 +0.5759%、最大回撤 -1.0588%、勝率 50.0%、profit factor 1.5439。
- 升級後 candidate（同一指紋與設定）：5 trades、1 missed、報酬 -0.4307%、最大回撤 -1.0224%、勝率 40.0%、profit factor 0.7898；新增交易來自舊版排除的同棒進場後停損。
- 連續窗口診斷：2024-07-01～2024-10-02 為 4 trades／-1.1432%；2026-05-26～2026-07-10 為 1 trade／+0.6936%。樣本過少，不作策略績效結論。
- 整合驗證：56 項 unittest、py_compile、diff-check 通過；實際合約資料 5,952-row signal prefix 與 4 筆截止交易通過 prefix invariance。
- 對照指標：總報酬、最大回撤、交易數、勝率、profit factor；所有差異需可追溯至時間／成交／成本修正。

## Active branches and worktrees

- Manager/integration：`codex/contract-backtest-parity`
- Engine：`codex/v8-engine-core`
- Data：`codex/v8-data-pipeline`
- Strategy/Live：`codex/v8-strategy-modules`
- Benchmark Data：`codex/contract-benchmark-data`
- Benchmark Strategy：`codex/contract-benchmark-strategy`
- Benchmark Analysis：`codex/contract-benchmark-analysis`
- 保留中的其他工作：`codex/nfe-v2-a-bears-comparison`、`codex/nfe-v2-a-strategy`、`codex/nfe-v2-a-analysis`、`codex/param-opt`。

## Known conflicts

- NFE V2 A／BearS worktree 有進行中未提交修改，本輪禁止觸碰。
- `codex/param-opt` 有未提交的 `strategy_engine.py` 與研究腳本，本輪不採用、不覆蓋。
- 舊 `data/market_data.duckdb` 快照有大量缺口且不可作正式評估；新標準資料庫已補齊至 2026-07-18 13:51 UTC 且 gaps=0。
- Live 已做到 closed-bar 增量、fill 後保護與冪等 reconcile，但交易所實際 fills 尚未回寫策略帳本，策略轉 flat 也不會自動平掉不一致的交易所倉位。
- 歷史逐期 funding 與 mark-price 清算資料尚未接入；目前只有明確方向的固定 funding fallback。
- 本輪 MDD 由已平倉交易 equity 計算，未包含持倉中的 mark-to-market 路徑；歷史 funding 未下載，使用固定 0.01%/8h fallback。

## Next checkpoint

完成單變因候選與時間安全測試後，跑七組全期及 2026-07 MTD；只有 PF≥1、MDD 改善、樣本≥50 且無單筆獲利集中才接受。
