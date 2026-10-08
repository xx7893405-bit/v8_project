# V8｜BOSWaves A／C 獨立回測模組（第一階段）

## 結論／狀態

**已完成**：獨立回測程式、預設參數、A/C 生命週期、1 分鐘防未來函數的成交順序、成本和滑價、3/4/5 ATR 比較、短時間翻轉摩擦診斷、TradingView 逐筆對帳入口、輸出檔案與單元測試。

**已驗證**：隨附 `tv_reference/BOSWaves_1h_AC_trades.csv` 共 66 列（A/C 各 33 列），兩版本同筆交易的方向／進場時間／進場價／初始 SL 全部對齊；11 項單元測試通過、模擬 1m K 線的完整流程通過。

**尚未驗證**：目前缺使用者 V8 本機 BTCUSDT 永續合約資料（GitHub 不含 DuckDB 本體），以及 TradingView A/C 實際 Pine 原始碼與商品識別資訊，因此 **尚未完成 TradingView ↔ V8 的真實訊號對帳、更沒有五年績效結論**。程式刻意把五年正式研究鎖在對帳門檻後。

## GitHub 移交說明

目前 GitHub 分支**刻意不包含使用者上傳的逐筆 TradingView CSV**，避免將私人交易歷程發布到公開倉庫。請在 V8 本機將同名 CSV 放入 `boswaves_v8_module/tv_reference/BOSWaves_1h_AC_trades.csv` 後，才能執行 audit/parity。未放入時，單元測試的參考 CSV 相關 2 項測試會略過；其他程式功能仍可檢查。尚未取得 TV A/C 原始 Pine 與 2026/9–10 月完整本機合約行情，尚不能宣稱對帳通過。

## 模組不影響既有 V8

```
boswaves_v8_module/
  boswaves_v8.py           # 訊號/初始SL/A-C交易狀態/摩擦與ATR比較
  run_boswaves_v8.py       # audit -> parity -> full 唯一入口
  tests/test_boswaves_v8.py
  tv_reference/BOSWaves_1h_AC_trades.csv
  tv_reference_audit.json  # 目前TV檔的內部一致性審查
  README.md
```

只讀 `V8/data/btcusdt_perp_1m_202101_present.duckdb`，不修改、不覆寫、不下載、不碰原本 V8 模組與回測結果。

### 對應原始指標的候選設定

- 方向：ALMA(34, offset .85, sigma 6)；收盤高於/低於 ALMA ± 0.65 × 34 根價格標準差；ALMA 3 根變化 / ATR(14) 超過 ±.08 後，且與現有趨勢不同，產生 Flip。
- 停損：結構參考價，最短 .75 ATR、最長 3 ATR。
- `stop_reference_mode=flip_extremes` **只是候選復刻**：用最近指定數量「同方向 Flip K」的高／低極值建立結構；另留 `rolling_bars` 開關用於核對。是否含當根／是否需滿 12 個 Flip，仍需原始 Pine 或逐筆對帳判定；**不可稱 100% 與原作者相同**。
- A：確認的反向 Flip 或原始 SL 出場，停損後不在同方向再次開倉，直到新 Flip。
- C：與 A 相同的 Flip 進場／原始停損；**到 2R 才拉保本、到 3R 拉 +1R、到 4R 拉 +2R**；其後不設固定獲利上限，直到保護 SL 或反向 Flip 出場。未做分批出場。
- 手續費預設每側 .05%，成交滑價預設 0，固定每筆帳戶風險 3%、槓桿上限 20 倍。**實際 TradingView 設定須另核對，對帳必須相同。**

### 認知與時序限制

- 只使用已收盤 1h K 判斷訊號；Flip 發生在該小時 **結束時**，不會拿該小時已發生的最高、最低價替新單倒掛止損。
- 成交時序用下一分鐘的 1m 高低價檢查舊有 stop；同一分鐘同時發生止損與新 T2 時優先保守處理止損，防止使用不明的 tick 順序套利。
- 模擬使用逐筆固定風險倉位，而非每筆固定 BTC 張數。大停損相對少持幣；比較 3/4/5 ATR 時不誤把放寬 stop 當免費獲利。
- 此模組不是交易所實盤擬真：尚無歷史資金費率、標記價格或精確 tick 序列。正式實盤同等性仍需另外證明。

## 在本機 V8 使用

複製整個 `boswaves_v8_module` 資料夾至 V8 專案根目錄，先在 **V8 根目錄**執行：

```bash
# 不需要市場資料，先確認這個月的 TV CSV 本身一致
python boswaves_v8_module/run_boswaves_v8.py audit \
  --tv-csv boswaves_v8_module/tv_reference/BOSWaves_1h_AC_trades.csv

# 測試
python -m unittest discover -s boswaves_v8_module/tests -v
```

### 第二關：1H TradingView 對帳

1. 先確認 TradingView 實際商品是否為 **BINANCE:BTCUSDT.P 永續合約**。如果 TV 是現貨或其他交易所，就**不要**把 V8 永續合約資料宣稱是同一市場；需先改成相同來源才可比較。
2. 先查看本機 `data/btcusdt_perp_1m_202101_present.duckdb` 是否更新、完整涵蓋 2026/9/1–2026/10/7。倉庫現有 manifest 只有到 2026/7/18，不代表本機已更新。
3. 資料充足且市場一致時，執行：

```bash
python boswaves_v8_module/run_boswaves_v8.py parity \
  --database data/btcusdt_perp_1m_202101_present.duckdb \
  --tv-csv boswaves_v8_module/tv_reference/BOSWaves_1h_AC_trades.csv \
  --tv-market BINANCE:BTCUSDT.P \
  --start 2021-01-01T00:00:00Z \
  --end 2026-10-08T00:00:00Z
```

- 輸出 `reports/boswaves/parity_.../parity.json`、`parity_details.csv`、`trades.csv`、`manifest.json`。
- 審查四項：同向 Flip 時間、進場價、初始 SL、離場原因/時間。
- **門檻：A/C 各至少 80% 交易訊號／進場價／SL 配對成功，且整體至少 80% 離場原因及時間相符；不能有超過 20% 額外訊號。** 沒達標不執行五年正式分析。
- `parity.json` 為數值比對結果，不代表取得 TradingView 原始 Pine。

### 第三關：五年 BTC 正式研究（通過對帳後）

```bash
python boswaves_v8_module/run_boswaves_v8.py full \
  --database data/btcusdt_perp_1m_202101_present.duckdb \
  --tv-csv boswaves_v8_module/tv_reference/BOSWaves_1h_AC_trades.csv \
  --tv-market BINANCE:BTCUSDT.P \
  --parity-proof reports/boswaves/parity_<本次編號>/parity.json \
  --start 2021-01-01T00:00:00Z \
  --end 2026-10-08T00:00:00Z
```

`full` 會在資料／參數／市場不符合要求時拒絕執行。正式跑的主要檔案：

- `summary.json`：A/C 勝率、PF(R)、淨 R、成本 R；翻轉 6/12/24 小時摩擦；3/4/5 ATR 對照以及「3ATR 停損但擴到 4/5ATR 後持有到翻轉且真正獲利」的筆數。
- `atr_caps_trades.csv`、`atr_cap_rescues.csv`：**固定資金風險**前提下，3/4/5 ATR 個別交易對照；防止把止損放大視為免費改善。
- `post_stop_candidates.csv`：3ATR 提前止損後，下一次翻轉前是否回到進場、觸及 1R/2R；**只能作為錯失行情候選，不等於能實際拿到的收益**。
- `trades.csv`：A/C 逐筆持倉資料、真正結算 R、最大曾到 R、初始 SL、提高後 SL、手續費與滑價成本。

## 特別需要核對的 TV 第 29 筆

使用者的 A/C CSV 同時記錄：

- `max_r ≈ 1.929674`
- `t2_hit = true`
- C 版 `exit_reason = Protect 0R`

如果 `max_r` 與 `t2_hit` 指的是**同一套價格與同一筆倉位的最大浮盈**，這三項並不一致。本模組在 `tv_reference_audit.json` 特別列出此案，不能直接把 `max_r >= 2` 和 T2 命中畫上等號。需核對原 Pine 的里程碑使用哪些價格及時序。

## 模組邊界

此版是**可執行的研究模組**，不是已通過真實對帳的「BOSWaves 官方等價實作」。在拿到 TradingView A/C Pine 原始碼、TV 商品資訊、本機更新後合約資料前，不允許對外宣稱策略已在五年 BTC 驗證有效。報告應採用明確資料指紋、時間區間、成本和成交順序，避免先看績效再改訊號。
