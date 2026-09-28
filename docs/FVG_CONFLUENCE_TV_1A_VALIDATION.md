# FVG 1.0A 視覺驗證記錄

日期：2026-09-28，Asia/Taipei。範圍：Issue [#199](https://github.com/xx7893405-bit/v8_project/issues/199) 與本次對話核准的生命週期補充。未修改 V2、SMC-V2、資料、成交、成本或回測引擎；未跑正式回測。

## 版本與恢復

- 分支：`codex/fvg-confluence-tv-1a`；隔離 worktree 保留主 checkout 未提交修改。
- baseline：`f41a2dfa6d02acf6adbc642f3469c3879ebde208`。
- baseline Pine SHA-256：`f572c38c091ded78d19627a25fcd79104399e03040d7e235ffdf5cdfb4bf3f69`。
- candidate Pine SHA-256：`3b3a3a49733d5242fbf4dbee73662f7b2612396ba83649557de7ccc8d98762a9`。
- 取回原版：`git show f41a2dfa6d02acf6adbc642f3469c3879ebde208:tradingview/fvg_confluence_visual_1a.pine`。

## 檢查與修正

| 項目 | 證據與判定 |
|---|---|
| Pine v6 | 完整修正版已在 TradingView 編譯並更新圖表；合成測試腳本獨立執行 |
| 1H 已收盤資料 | `request.security` 的 OHLC / time_close 全部至少偏移一根，`lookahead_on` 只釋出上一根已完成 1H；三根 FVG 比較 `[1]` 與 `[3]` |
| 即時 rollback | 移除建立 HTF 物件的 `barstate.isnew` 限制；新 1H 的首根 15m 每次更新都重建，收盤才提交，避免只在 opening tick 建立後被 rollback 清除 |
| FVG / 交集 | 多空三根定義、max 下界 / min 上界、零寬度排除，均有原生 Pine 斷言 |
| 優先級 | 沿用中點價格方向排序；修正同中點重複 P1，以 Z 建立順序打破平手；有效集合改變才重排 |
| touch | 影線與區間相交即可，邊界相等有效；不把建立前的 15m 影線算入新區域 |
| 失效 | 先檢查收盤穿越遠端，優先於 touch / 關鍵 K / 到期；影線穿越不直接失效 |
| 到期 | 原版晚一根才標過期；現為 touch=第 1 根，第 96 根最後可確認關鍵 K，否則當根收盤過期 |
| 生命周期 | 未 touch 等待期限、touch 後獨立觀察期限；未鎖定 1H 隱藏；共享來源最後子區結束才隱藏，來源禁止無限新增配對續命 |
| 關鍵 K | 方向、實體 / 1H FVG 寬度、順向影線 / 全 K；30/50/70 與 10/20/30 的等號邊界均有斷言；反向影線不限制 |
| 首次 touch 標籤 | 與當根關鍵 K 同時成立時仍保留兩種事件；每方向每根彙整一標籤，帶 Z / P 與比率 |
| 顯示效能 | 原版及中間版有接近方案 20 秒上限提示；改為候選集合變動才排序、結束物件不逐根重設、活動文字僅最新棒更新。未取得 Profiler 的實測秒數 |

時序判讀依 TradingView 官方 [HTF requests](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/) 及 [execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/) 的 offset / rollback 說明。此為來源審查加 UI 驗證，未做整段歷史與即時錄製後逐棒對帳，不能宣稱已證明所有情境皆不 repaint。

## 原生 Pine 測試

`tests/pine/build_fvg_confluence_tests.py` 直接抽取正式指標的純函數區塊，接上固定合成 OHLC 斷言，避免 Python 模型與 Pine 實作各自漂移。產生器不執行 Pine，也不做交易回測。

```sh
rtk proxy python3 tests/pine/build_fvg_confluence_tests.py --output /private/tmp/fvg_confluence_contract_tests.pine
rtk git diff --check
```

本輪實際在 TradingView 經過：

1. 原版到期語義出現 `FAIL: expiry at close of candle 96`；修正後 PASS 1。
2. 同價位排序出現 `FAIL: equal-price zones have stable distinct ranks`；修正後 PASS 2。
3. 擴充 FVG、交集、邊界、關鍵 K、影線、失效優先與已收盤限制至 PASS 43。
4. 加入等待、共享來源、禁止續命、反向開關，畫面顯示 **PASS: 57 cases**。

最終 fixture SHA-256：`1c8d1877ec09b2f53bf6c43eb3c07e220ded893d24a6da867f687c1400960fda`。最終繪圖／首次可 touch 棒接線修正未變更函數區塊，重產出的 fixture 指紋相同，沿用該原生執行證據。另通過產生器 Python AST 語法檢查及 Git diff whitespace 檢查。

這 57 項驗證純函數契約，並未覆蓋 TradingView 物件數上限、完整真實市場逐棒資料或 Pine rollback 的所有整合情境。

## 畫面及人工核對

驗證入口：[TradingView 圖表](https://www.tradingview.com/chart/WVcin0WD/)。先在原有 `BINANCE:BTCUSDT.P` 15m 更新，再依需求檢查 `BINANCE:BTCUSDT` 15m。指標是未公開的編輯器草稿／本圖表實例；沒有按 Publish script，也沒有聲稱已另存成雲端腳本。

22:04 台北時間的 BTCUSDT 圖面已載入修正版並顯示 PASS 57：可見多空已鎖定 1H FVG、15m FVG、空方 Z2294 P1 首次進區、Z2295 P2 收盤失效，以及左側關鍵 K 的位移 302.3%／順向影線 16.5%。以上是圖面標記觀察，尚未以匯出 OHLC 對每個值獨立重算。Inputs UI 已展開核對所有位移與影線選項，保留預設 50%／20%／96、反向阻擋開啟。未把所有九組參數組合逐一重載圖表。

22:07 再從實際圖表的 Pine Editor 複製原始碼，CRLF 正規化後與本機傳入內容完全相同（28,269 字元、兩處下一根 touch 接線及繪圖效能修正皆存在），Update on chart 為停用狀態且沒有先前的 Heavy script 提示。這不取代 Profiler 的計時資料。驗證表已隱藏，正式圖表保留。圖片下載未取得可用檔案；本輪畫面證據顯示於對話及側邊 TradingView，未宣稱已保存 PNG。

人工仍需判定：

- 標準三根 FVG 是否與你的手動畫法一致。
- 中點價格排序、重疊或同價區域按建立順序是否符合 P1 的直覺。
- 15m 新重疊區「下一根才可 touch」是本輪採用的因果時序解讀，尚無使用者明確回答。
- 共用來源最後子區結束才隱藏、歷史終止框保留，以及物件數上限造成更早移除的可讀性。
- 真實市場 96 根到期、影線刺穿後收回、多空案例需人工逐根再核對；合成斷言通過不等同已逐根驗收所有圖表樣本。

本次只交付視覺驗證，不提供績效、交易勝率或 Pine/V8 parity 結論。執行時間、token、cache hits、費用：未取得可靠整段實測值，`unavailable`。

## 字體調整（2026-09-28 22:17）

以 `8222d99` 為 baseline，依使用者要求放大文字及加粗訊號。區域／F+／F- 字體預設 14；首次進區、關鍵 K、收盤失效、等待／觀察過期事件預設 16 並使用真正粗體；P 等級與區域狀態也加粗。Inputs「顯示」可分別調整兩種字級。使用 Pine v6 的 `text_formatting = text.format_bold`，依據官方 [Text and shapes](https://www.tradingview.com/pine-script-docs/visuals/text-and-shapes/)。此指標仍無實際交易進出場或下單規則。

F+／F- 的固定字級 plotshape 文字改為可調 label，圓點形成記號保留；文字與事件共用 Pine 的 500 個標籤上限，較舊標籤可能被回收。未改 FVG、時序、排序、生命週期或關鍵 K 判定。

Pine SHA-256：`f57b09ea39f3b23a74593f35e7fe9e96898e7dc07450071e0dbf31ce84cb40b2`。重新產生 fixture，SHA-256 仍為上述 `1c8d1877...960fda`，沿用已執行的 57 項契約證據，沒有宣稱本次重跑。`git diff --check` 通過。TradingView 已在使用者當前 `BITGET:ETHUSDT.P` 15m 圖表成功編譯、顯示 14／16 參數及粗體事件；未改商品或時間週期，未跑回測。
