# Project State

## Objective

下載 2021-01-01 至今的 Binance BTCUSDT 永續合約資料，並以已升級回測引擎公平比較 NFE V2、NFE V2 A 與 BearS 的全期及 2026-07 月迄今結果。

## Current phase

Phase 3：合約資料下載、A 策略相容與三策略比較入口平行準備。

## Verified baseline

- Rollback：`b6556aa`（`codex/v8-modularization`）；`main`／`v8.0.0` 仍為 `76f6ee4`。
- Integration：`codex/contract-backtest-parity`，從 `b6556aa` 建立。
- Benchmark：`codex/contract-v2-a-bears-benchmark`，rollback 為 `3d28f79`。
- 本輪固定設定：Binance USDT-M `BTCUSDT`；2021-01-01 至最後完整 1m；另跑 2026-07-01 至同截止；10,000 USD、risk-based 1%、3x、maker 0.02%、taker 0.05%、相同滑價與 funding fallback。
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
- 合約 1m 資料存在大量缺口；Data 任務需先產出完整性契約與可用窗口。
- 合約資料缺口為 2024-10-02 10:29～2026-05-25 23:59，共 864,811 分鐘；資料也停在 2026-07-10，不能作 2026-07-18 live 判斷。
- Live 已做到 closed-bar 增量、fill 後保護與冪等 reconcile，但交易所實際 fills 尚未回寫策略帳本，策略轉 flat 也不會自動平掉不一致的交易所倉位。
- 歷史逐期 funding 與 mark-price 清算資料尚未接入；目前只有明確方向的固定 funding fallback。

## Next checkpoint

Data 完成 rows/gaps/duplicates/fingerprint 驗收，Strategy 完成 A 相容測試，Analysis 完成公平指標入口後，由 Manager 整合並跑全期與 2026-07 月迄今；原始資料與報告使用新路徑，不覆蓋現貨資料或舊報表。
