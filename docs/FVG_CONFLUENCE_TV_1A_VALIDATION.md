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

## 1H 鎖定 FVG 總覽（2026-09-28 22:34）

以 `8800313` 為 baseline，依使用者要求新增 1H 顯示模式。1H 只繪製仍有效、已鎖定的 1H FVG；15m 區域、重疊框、優先級、形成記號及事件標籤僅在 15m 顯示。繪圖座標改用實際時間，以保留小週期成立時刻。原有字級、粗體、參數預設及純函數契約不變。

1H 透過 `request.security_lower_tf` 依序讀取該小時的 15m OHLC，交給與 15m 模式相同的狀態更新區塊。新小時先釋出上一根已確認 1H，該步不推進 15m 計數。只處理已到收盤時間的 intrabar；未結束小時每次更新由 Pine rollback 重算已確認 15m 序列，不使用 varip 累加。依據官方 [lower-timeframe arrays](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/) 的時間排序與資料覆蓋說明。

1H 總覽讀取最近最多 2,000 根 15m，超過目前參數最大壽命 `3 × 384` 加暖機；這是目前有效區域的總覽，並非所有歷史時點回放。資料供應商修訂、缺少 intrabar 的範圍、完整即時 rollback 與跨週期逐棒 parity 未由本次有限畫面核對證明。

驗證：

- 完整最終版 Pine v6 在 TradingView 成功編譯及 Update on chart；沒有編譯或執行錯誤。
- 在使用者原有 `BITGET:ETHUSDT.P`，15m 與 1H 圖面均顯示當時兩個同位置的已鎖定看漲 1H FVG。1H 上沒有 15m FVG、重疊框、P、F+/F− 或事件標籤；返回 15m 時可見等待區、首次進區及失效的粗體標示。圖面比對未獨立重算市場 OHLC。
- 最終移除形成圓點在狀態列的 0.00 數值；編譯器中的完整內容複製回讀，CRLF 正規化後與傳入本機最終版完全相同（36,488 字元）。
- 重新產生 57 項 fixture，SHA-256 仍為 `1c8d1877ec09b2f53bf6c43eb3c07e220ded893d24a6da867f687c1400960fda`；沿用先前原生 Pine PASS 證據，未聲稱重跑，也不把純函數測試當成新跨週期接線的完整測試。
- `git diff --check` 通過；未跑正式回測，未改 V2／SMC-V2，未推送或發布腳本。

最終 Pine SHA-256：`d609162f18d3b86072207d21114433c00247420558cf321c4011ddbf51b07d2f`。已在原商品切換 1H／15m 核對；指標仍為此圖表的編輯器草稿實例，使用者可自行切換檢視。

## 最近 10 次收盤失效紀錄（2026-09-28 後續）

新增 1H FVG 來源失效及其重疊區收盤失效的最近 10 筆稽核表。每筆列出時間、類型／方向、來源 1H FVG 時間與價格範圍、失效區及 15m 收盤比較條件；過期與關鍵 K 完成不混入失效紀錄。資料依可載入圖表歷史重算，1H 視圖受目前 2,000 根 15m intrabar 範圍限制，不是跨工作階段永久保存。

驗證：從正式程式的合約函式產生 58 項 Pine fixture，新增「只保留最新 10 筆且欄位同步」斷言；TradingView 執行顯示 `PASS: 58 cases`。`rtk git diff --check` 通過。正式指標本身尚未在 TradingView 重新編譯；目前圖上成功執行的是合約 fixture，尚未確認新稽核表的實際欄位寬度、歷史事件內容或顯示位置。未推送、發布或執行正式回測。當前 Pine SHA-256：`c70514ebe952c5d79912ae56777403b0312c8171b785c4f0a91ce593e3fa6b32`；fixture SHA-256：`5eb6c18e52dc130c0866012aed68398e3b16bb584637636aee8926fc6000b88b`。


## TradingView 新版實際更新（2026-09-29 00:05）

正式指標已在使用者的 `BINANCE:BTCUSDT.P` 15m 圖表成功編譯、Update on chart，並以「V8 FVG 共振 1.0A｜視覺驗證」儲存為私人雲端腳本；圖表配置顯示 `All changes saved`。未公開發布。

- 從圖上舊版讀回 603 行，與 Git baseline 的 36,488 字元內容指紋相同；套用本機新版差異後，完整貼入並再次複製回讀。正規化換行後為 675 行、43,303 字元，回讀字串與傳入字串完全相同，內容指紋與本機新版相同，沒有截斷。
- 正式指標的最近 10 筆表格已出現，畫面可見「重疊區收盤失效」與「1H FVG 本體收盤失效」、來源時間／價格範圍，以及觸發收盤價與邊界比較；未把先前 fixture 的 PASS 誤當成正式指標編譯證據。
- 實際切換 1H 後可正常載入紀錄表，15m 事件標籤與小週期框未顯示；返回 15m 可見首次進區、收盤失效與關鍵 K 標記。當時畫面未有可確認的有效鎖定 1H 框，故未新增該框的實例驗證結論。
- 已知顯示限制：目前約 830 px 寬的側邊瀏覽器中，五欄表格過寬，左側部分欄位遭裁切且文字較小；欄寬／換行排版尚待修正。尚未對表格內每筆市場 OHLC 獨立重算，也未重新完整測試 Style 所有勾選項。
- 本輪僅完成正式腳本傳入、原生編譯、私人儲存及兩週期畫面檢查；Pine 檔案未再修改，沿用上節 SHA-256。未新增 Git commit、推送或正式回測。


## 失效矩形、BTC 三根 K 核對與 Style 標籤（2026-09-29 00:26）

依使用者補充，最近 10 筆失效事件對應的來源 1H FVG 已補上淡紅矩形；同來源合併，保留最近事件的種類與失效時間，矩形右界停在觸發失效的 15m 收盤時刻。歷史矩形使用獨立物件，來源退出有效陣列後仍可供稽核；不新增交易判定。

- 最終 Pine 712 行、45,846 字元，SHA-256 `395c311dde30e2a7414e03d20b1a488fec3920bff5de50c17ed53e27d6dc7177`。本機內容與 TV 貼入後回讀的字串一致，原生編譯及 Update on chart 成功，私人腳本已儲存。15m／1H 均實際看到淡紅矩形，15m 畫面可見多方來源框停於 22:45。
- Style → Graphic objects → `Pane labels` 完成關閉、開啟、再關閉：首次進區／收盤失效／關鍵 K 指向標籤及 F+/F− 文字隨之消失、恢復、消失；`Boxes` 與 `Tables` 保持勾選，矩形及其框內文字保留。最終保持 Pane labels 關閉。`Labels on price scale` 只控制價格軸標示，不是此類指向標籤的開關。
- 此輪未宣稱其餘所有 Style checkbox 皆已重測。表格在窄側欄裁切的既有限制仍在。
- 合約函數區塊未改，重產生的 58 項 fixture SHA-256 仍為 `5eb6c18e52dc130c0866012aed68398e3b16bb584637636aee8926fc6000b88b`，沿用先前原生 PASS 58 證據，未宣稱這輪重跑。Git diff whitespace 檢查通過；未執行正式回測。

### 使用者指定的 BTC 18／19／20 時範例

來源為 TradingView 資料視窗，`BINANCE:BTCUSDT.P`，日期 2026-09-28，以下時間均為圖表的 UTC+8，K 線時間代表開盤時刻。僅檢查此有限樣本，未取得可用的全圖 CSV。

| 1H K 線 | Open | High | Low | Close |
| --- | ---: | ---: | ---: | ---: |
| 18:00 | 82640.0 | 83024.6 | 82640.0 | 82928.5 |
| 19:00 | 82928.6 | 83081.6 | 82928.6 | 83054.5 |
| 20:00 | 83054.5 | 83609.4 | 82979.9 | 83546.5 |
| 21:00 | 83546.4 | 83794.9 | 83270.0 | 83609.1 |

18／19／20 的第三根 low 82979.9 並未高於第一根 high 83024.6；影線範圍重疊 44.7，依標準三根定義並未形成看漲 FVG。19／20／21 才形成 83081.6～83270.0 的看漲 FVG，寬度 188.4，於 22:00 確認（表格商品時區 UTC 顯示來源 14:00）。

| 15m K 線 | Low | Close | 下界 83081.6 的核對 |
| --- | ---: | ---: | --- |
| 22:00 | 83283.6 | 83357.3 | 未跌破 |
| 22:15 | 83059.4 | 83194.7 | 影線刺穿，但收盤在下界上方，未失效 |
| 22:30 | 82800.2 | 82907.8 | 收盤低於下界 173.8，於 22:45 確認失效 |

稽核表的失效時間 14:45 是 UTC，對應圖表 UTC+8 的 22:45。此次樣本符合「以收盤判定，影線刺穿不直接失效」規則；不把一般來源隱藏一概當成收盤失效。


## BTC 現貨 10:00 空方來源框缺失（2026-09-29 00:47）

本次 baseline 為 `7b0b427`。使用者指出的畫面商品是 `BINANCE:BTCUSDT` 現貨，與上一節 `BTCUSDT.P` 永續不同。依當時畫面檢查 2026-09-28，時間均為圖表 UTC+8；從 TradingView Data window 讀取，未使用其他市場資料代替。

| 1H K 線開盤時刻 | High | Low |
| --- | ---: | ---: |
| 08:00 | 84999.00 | 84140.00 |
| 09:00 | 84238.87 | 83613.80 |
| 10:00 | 83782.07 | 83389.07 |

08／09／10 三根的空方 FVG 為 83782.07～84140.00，寬 357.93，於 11:00 確認。15m 11:00 Data window 的「1H 新確認 FVG 下界／上界」與之相同。10:00 形成的 15m 空方 FVG 為 83782.07～83803.81，與來源相交的窄紫色框價格亦正確。

顯示問題來自來源生命週期的繪圖處理：21:30 的 15m 首次觸碰，22:30 的 K 線 O=83244.00、H=83480.01、L=82856.00、C=82948.33，位移 82.6055%、順向影線 14.7962%，於 22:45 收盤完成關鍵 K。舊版最後子區結束即將整個來源框透明化，只留下窄重疊歷史框，容易被誤認成 1H FVG 範圍縮窄。

修正僅限繪圖：最後子區以關鍵 K 完成時保留完整來源框，標示「1H 看跌／看漲 FVG｜關鍵 K 完成」，右界停在完成 K 的收盤時刻；來源仍退出 active、不接受新配對、不延伸到現在。沿用既有 1H 物件數上限，不新增永久物件。失效與過期分支、FVG 定義、鎖定、訊號、P 排序及門檻不變。

驗證：

- Pine v6 在原 TradingView 圖表成功更新並執行；15m 實際看到 83782.07～84140.00 的完整來源框及下方窄重疊框，右界停於 22:45。切到 1H 亦看到同一有限來源框與「關鍵 K 完成」，未出現 15m 重疊框／事件資訊。
- 傳入 719 行、46,505 字元，編輯器完整複製回讀相等；SHA-256 `92d468303c003a8ae1815b507e0592660c38b4b4996dad1be5c14cdd8c00a8ed`。私人雲端腳本已保存為版本 3（00:45）。
- 純合約函數區塊逐字未變；未重跑先前 58 項 Pine fixture。`git diff --check` 通過。這是指定樣本的價格／事件與視覺核對，不是跨週期全歷史 parity 或正式回測。
- 暫時關閉 Tables 以排除遮擋，驗證後已恢復勾選；Boxes 保持勾選，Pane labels 保持關閉。返回 BTCUSDT 15m。
- 未修改 V2／SMC-V2、未公開發布或推送。執行時間、token、cache hits、費用未取得可靠整段實測，`unavailable`。


## 關鍵 K 直接定位（2026-09-29 01:02）

以 `b4c677c` 為 baseline，依使用者要求改善「關鍵 K 文字難以辨認對應 K 棒」的顯示。新增只在已確認關鍵 K 棒成立的視覺旗標，15m 當根棒色與實心三角形使用零偏移：多方藍色／K 棒下方上三角，空方橘色／K 棒上方下三角。區域框內的歷史狀態與原本粗體事件文字保留，訊號判定、來源 FVG、門檻及生命週期未改。

- 新增 Style 獨立項目「多方關鍵 K 箭頭」「空方關鍵 K 箭頭」「關鍵 K 棒色」。採 TradingView 官方 [plotshape](https://www.tradingview.com/pine-script-docs/visuals/text-and-shapes/) 與 [barcolor](https://www.tradingview.com/pine-script-docs/visuals/bar-coloring/)；三角形不含固定小字，原有動態文字仍使用既有粗體繪圖。
- 最終 730 行、47,463 字元；SHA-256 `8f8f47efd14aa51f85d673a9c5a8c6a207303172f82b30ddb283346c0b9c7411`。Pine Editor 完整回讀比對相符，私人版本 6（00:55）已儲存。初版細箭頭在畫面不夠明顯，最終改為實心三角形。
- TV 原生編譯與載入成功。在 BTCUSDT 15m，9/28 22:30 空方 K 棒可見橘色實體與上方橘色下三角；早晨多方關鍵 K 可見藍色實體與下方藍色上三角。關閉空方箭頭後三角消失而棒色保留；恢復空方箭頭、關閉棒色後三角仍在而 K 棒恢復原色；多方箭頭亦完成關閉與恢復。三個新 Style 開關有效。
- `Pane labels` 關閉時，新三角及棒色仍可見。1H 總覽檢視中不顯示 15m 三角或棒色。最後返回 15m，三個新項目皆開啟，Boxes／Tables 開啟，Pane labels 關閉。
- 儲存後的圖表實例曾仍連結版本 4；已明確核對版本身分、加入版本 6，再只移除被取代的版本 4。圖表只有一個本指標實例，其他指標保留。
- 純合約函數逐字未變，沿用先前 58 項 fixture 證據，未宣稱重新執行；`git diff --check` 通過。未跑正式回測、未修改 V2／SMC-V2。執行時間、token、cache hits、費用未取得可靠整段實測，`unavailable`。
