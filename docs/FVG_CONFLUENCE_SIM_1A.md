> 本文件保存 `c0d7e2b` 的單倉歷史驗收；多空各一筆新版見 [FVG_CONFLUENCE_DUAL_1A.md](FVG_CONFLUENCE_DUAL_1A.md)。

# FVG 共振 1.0A：TradingView 模擬交易版

規格 [#200](https://github.com/xx7893405-bit/v8_project/issues/200)，已核准單票 [#201](https://github.com/xx7893405-bit/v8_project/issues/201)。分支 `codex/fvg-confluence-tv-sim`，來源基準 `6ec5ac9`。原 `fvg_confluence_visual_1a.pine` 保留不變，新檔為 `tradingview/fvg_confluence_strategy_1a.pine`。

## 進出場契約

- 15m 確認關鍵 K 後送出市價委託，下一根 K 開盤模擬成交。不能把尚未收盤的 K 當成訊號。
- 每個鎖定 **1H 來源 FVG** 最多一次。資格按來源 ID 記錄，不按重疊區、P 排名或圖形物件記錄；出場與圖形回收不重置。
- 全策略最多一筆，待成交也占用名額；持倉期間新關鍵 K 忽略、不排隊、不加倉、不反手。同根多個合格來源依既有 P 排序選取。
- 送單時預留該來源，凍結來源上下界與 SL。若下一根結束仍無成交，取消委託並標示檢查模擬資金／數量，不無限卡住，也不重送該來源。
- 多單 `SL = 1H 下界 − 寬度 × 緩衝%`；空單 `SL = 1H 上界 + 寬度 × 緩衝%`。緩衝預設 **1%**、最小 1%、可增加，停損向 FVG 外側按商品最小跳動單位取整。
- `R = abs(實際進場價 − SL)`；多單 `TP = 進場價 + RR × R`，空單相反。RR 預設 **2**，可調。目標價向獲利方向取整。
- 送單時先附 SL，成交回呼取得實際均價後立即補上 TP。若跳空使風險非正，取消原 bracket 並立即保護退出，原因為 `GAP SL`。
- **成交後 SL／TP 是原生價格委託，影線觸及即可觸發**；這與進場前 FVG／重疊區的「收盤失效」是不同事件。後者規則不變。

## 圖表與操作

在目前 BTCUSDT 15m 圖加入「V8 FVG 共振 1.0A｜模擬交易」。原視覺指標保留並隱藏，避免重複繪圖。

- 藍色虛線：實際進場價；粗體多單／空單進場標籤指向成交 K。
- 紅色 SL、綠色 TP：預定價位與價格標籤。
- 已出場交易：粗體紅色停損／綠色止盈指向實際出場 K，價格來自 broker ledger；線段右端為出場 K 的結束邊界。跳空可使实际成交價不同於預定價。
- 預設保留最近 **10 筆已出場交易圖形**，另顯示目前持倉；範圍可調 1–60。此限制只影響繪圖，完全不清除來源進場紀錄或原生成交記錄。
- Inputs → 交易顯示可分別關閉「價位線」與「粗體進出場及價格標籤」。Style → Lines／Pane labels 則分別控制所有 line／label 物件。
- 原先首次進區／失效等事件文字及 F+/F- 預設隱藏，可於 Inputs 單獨開啟；區域矩形、關鍵 K 箭頭／棒色與最近十筆失效矩形仍保留。
- 失效明細表預設隱藏，可獨立開啟。Style 的資料核對欄位開關控制 Data Window 數值，不是 FVG 矩形；矩形由 Boxes 控制。
- 1H 只檢視來源 FVG 與其歷史狀態，不產生交易或 15m 箭頭／交易線／交易標籤。策略依確認收盤執行，1H 當根視圖不承諾逐 tick 更新。
- 交易表已開啟 Signal 欄，能核對來源時間、P／Z 與 `SL`／`TP` 原因。原生 Signal labels／Quantity 小字已關閉，保留原生交易箭頭和自訂粗體標記。

## 模擬與資料限制

當前商品是 **BINANCE:BTCUSDT 現貨**，圖表 UTC+8；來源 FVG 文字沿用商品時區 UTC，請勿混讀時間。未替換成永續合約。

預設初始資金 100,000、每筆 0.001 商品基礎單位、100% margin、佣金 0、滑價 0，僅供價格位置和時序驗證。Properties 可調交易成本／數量；沒有 V8 risk 5%／20x 的預設。

採 TradingView 預設 OHLC broker 路徑，未啟用 Bar Magnifier；同根同時觸及 SL／TP 時，由原生撮合路徑決定先後，不能宣稱知道真實逐筆順序。跳空依原生撮合規則成交。這不是實盤、正式 V8 回測或成交同等性驗證，沒有報酬改善主張。

`calc_on_order_fills=true` 會觸發 TradingView 的通用 look-ahead 警示。程式以成交狀態變化辨識 fill execution，這些回呼只讀凍結停損與 native fill 資料；訊號引擎只在正常確認收盤執行一次。已完成有限原生測試，但尚未長時間 forward 驗證即時回滾；不得把此測試擴大為所有市場／所有 Properties 設定均無 repaint 的保證。請保持 On order fill 開、On realtime bar tick 關、收盤立即成交關的交付設定。

官方語義：[Strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/)。

## 本次驗證（2026-09-29）

1. 原生契約 **14 項 PASS**：多空邊界停損、向外跳動取整、實際成交價 2R、錯側／零風險不建立 TP、同來源禁止再進場、不同來源空倉可進場、持倉與待成交阻擋。
2. red-green：先觀察缺少 `f_sim_stop`／`f_sim_target`／`f_sim_can_enter` 的 Pine 編譯失敗，再逐項實作並在原生圖表看到 PASS 1／5／14。
3. 原生成交排程：未設防護版本在 **bar 51** 確實失敗 `SIGNAL ENGINE REPEATED ON FILL`；加入生產 scheduler 後兩筆合成委託完成 **2 entries／2 exits**，驗證正常收盤每根只一次、下一根開盤價成交，以及入場同根 bracket 生效。這是有限合成測試，非策略績效回測。
4. 正式模擬 Pine v6 編譯並加入圖表，執行無 runtime error。實際圖上看見粗體 SL 與 TP 出場。
5. Inputs 交易線／交易標籤分別關閉與恢復，Style Lines／Pane labels 分別關閉与恢復，都逐次看圖核對。1H 模式無 15m 交易圖形，再返回 15m。
6. 原視覺檔 SHA 與 FVG 純函式区塊逐字一致。先前視覺版契約證據沿用，未冒稱本次重跑舊 58 項。

可人工重看（以下都是圖表 UTC+8）：

| 樣本 | 實際進場 | SL／TP 或出場 | 核對結果 |
|---|---|---|---|
| 空單 #22 | 9/28 22:45，82,948.33 | SL 84,143.58；TP 80,557.83；9/29 00:15 SL 出場 | 對應 22:30 關鍵 K；來源 1H 83,782.07–84,140.00、寬 357.93，1% 緩衝與 2R 數值吻合 |
| 空單 #21 | 9/24 22:45，84,413.66 | 9/28 17:00 TP 82,655.10 | 原生成交 Signal=TP 與綠色粗體出場標籤一致 |
| 空單 #23 | 9/29 05:30，83,468.32 | SL 83,801.87；TP 82,801.22 | 觀察時未平倉；R=333.55、2R=667.10，圖上價位吻合 |

上述序號會隨圖表載入歷史變動，時間／價格才是穩定核對依據。驗證視窗當時有 22 筆已平倉與一筆持倉；這不是完整資料績效結論。原指標沒有交易報表，因此不製造新舊績效比較。保留基準与訊號契約對照，依使用者範圍不跑正式 V8 回測。

重建測試（builder 只產生 Pine，不代替原生執行）：

```sh
rtk python3 tests/pine/build_fvg_sim_tests.py --output /tmp/fvg_sim_contract_tests.pine
rtk python3 tests/pine/build_fvg_sim_tests.py --mode timing --output /tmp/fvg_sim_timing_tests.pine
```

來源／fixture 指紋與實測身分見 `FVG_CONFLUENCE_SIM_1A_MANIFEST.json`。本次 screenshot 與原生執行結果顯示於 Codex 對話；未另宣稱已有圖片檔或 OHLC CSV。完整 runtime、token 與費用 unavailable。沒有修改 V2、SMC-V2 或正式資料／成交成本模組。
