# 合約回測資料使用規範

## 標準資料

- 市場：Binance USDT-M `BTCUSDT` 永續合約（程式內代號 `BTC/USDT:USDT`）
- 週期：1m，只保存已收盤 K 線
- 本機路徑：`data/btcusdt_perp_1m_202101_present.duckdb`
- 版本證據：`data/btcusdt_perp_1m_202101_present.manifest.json`

DuckDB 約 200 MB，屬於可重建的市場資料，因此由 `.gitignore` 排除；Git 只保存下載器、manifest、回測程式與操作規範。這可避免 repository 膨脹，也不會把資料檔誤認成程式版本。

## 建立與更新

以下命令可首次下載，也可從資料庫最後一根 K 線續傳至目前最後一根已收盤 K 線：

```bash
python download_perpetual_history.py
```

下載完成會產生被 Git 忽略的 `data/btcusdt_perp_1m_202101_present_diagnostic.json`，其中包含筆數、起訖時間、重複、缺口與 SHA-256。正式比較前必須確認：

- `market_type` 為 `swap`，不可為 `spot`
- `duplicates`、`gap_count`、`missing_minutes` 都是 0
- `last_candle_closed` 是 `true`

更新資料後 SHA-256 與截止時間必然改變。若要把新快照設為團隊基準，應審視 diagnostic，再以它更新 manifest 並提交；舊報告不可覆蓋。

## 策略比較

```bash
python run_contract_strategy_comparison.py
```

此入口預設讀取上述合約資料，並以 10,000 USD、risk-based `risk_pct=5%`、槓桿上限 `20x`，公平比較 NFE V2、NFE V2 A 與 BearS。每次執行會建立新的 `reports/contract_benchmark/<run-id>_<fingerprint>/`，記錄資料指紋、設定、指標及逐筆交易。

## 在其他電腦使用

有兩種方式：

1. 執行下載器重建並更新到當時最新的完整快照，適合新的策略評估。
2. 若要完全重現既有報告，從團隊的 artifact/object storage 複製同一 DuckDB 到標準路徑，並用 `shasum -a 256` 對照 manifest。

除非團隊決定長期用 Git LFS 發布二進位資料，否則不要對 `*.duckdb` 使用 `git add -f`。目前尚未整合歷史 funding rate 與 mark-price，資金費率仍是固定 fallback，最大回撤也只依已平倉 equity 計算；報告必須保留這兩項限制。
