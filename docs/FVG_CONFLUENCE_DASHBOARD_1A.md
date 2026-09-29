# FVG 最近 N 筆交易儀表板

2026-09-29；baseline `2207ffc`；分支 `codex/fvg-confluence-touch-option`。
範圍僅為 Pine 統計與顯示，依小型非交易變更流程處理。沒有改動策略規則、送單、資金、成本預設、V2 或 SMC-V2。

## 使用方式與口徑

- N 沿用「保留最近已出場交易圖形」（原預設 10，上限 60）；設為 30 即統計最近 30 筆已出場交易。不足 30 筆顯示實際筆數／30；未平倉不占 N。
- 新增「顯示交易統計儀表板」、位置及字體大小。自動位置為多方左下、空方右下；兩實例各自統計，不合併成單一帳戶。
- 狀態依序為持倉進行中、關鍵 K 已確認待成交、觀察中、等待觸碰／等待收盤觀察、等待 FVG 共振。只計本方向尚未消耗的來源及活動重疊區；狀態是最新計算結果，不隨十字線回到歷史。
- TP／SL／其他依 broker 出場原因；SL 包含 GAP SL。勝／負／平則依淨損益符號，兩者不混用。
- 模擬淨損益為最近 N 筆 `strategy.closedtrades.profit()` 合計，已含策略設定的手續費；手續費欄僅揭露，不能再扣一次。平均每筆損益為合計／實際筆數。
- 勝率＝正淨損益筆數／實際筆數；平手計入分母。PF＝正淨損益合計／負淨損益絕對值合計；有盈無虧顯示無虧損，無盈虧或無樣本顯示破折號。
- 價差 R＝方向價差／實際進場價到初始 SL 的風險距離，使用成交價與凍結 SL，不用設定 2R 代替成交結果。價差 R 不扣手續費；非正初始風險／缺失 SL 的交易不計 R，顯示有效 R 筆數。
- 金額風險不同時，累計 R 與金額損益可能異號。判斷這 N 筆賺賠看模擬淨損益；不是未來 N 筆的預測。未設定的交易成本及資金費率不會自動補算。
- 未平倉損益另列。1H 只顯示「請切至 15m」，不把沒有 15m 交易的 1H 視圖誤報為零交易績效。

## 原生驗證

TradingView `BINANCE:BTCUSDT` 現貨、15m、固定數量 0.001、初始資金 100000 USDT；此為 UI 與數字核對，不是正式 V8 回測／實盤績效。

1. 原生 Pine v6 正式版本 12（12:07）編譯成功。完整回讀 67,756 字元，FNV32 `669e5c30`；SHA-256 `b192a9e268997334173b300da015877fe0024ca8c49c539c86e24cf25ef743ee`。
2. 在原生版本 11 暫加 `tests/pine/fvg_dashboard_contract_cases.pine`，多空皆 PASS 17。涵蓋零樣本、30 筆 12 勝 18 負的 +6R、最近 10 筆截取、不足 N、TP 扣費後虧損、其他出場、平手、缺失 R、跳空 SL、長短對稱 R 及狀態優先序。
3. 對載入的有限成交清單逐筆核對：`(exit-entry)*signed_size*pointvalue-commission == closedtrades.profit`，並核對合計等於 `strategy.netprofit`。暫將空方手續費設為 1%、N 設為 30，仍通過；顯示 12/30 筆、TP/SL/其他 5/7/0、勝負平 1/11/0、淨損益 -18.9735 USDT、已計手續費 19.0129 USDT、價差 +3R。測試後恢復原本 0% 及 N=10。
4. 零成本 N=10 畫面：多方 TP/SL 2/8、淨損益 -1.757 USDT、價差 -4R；空方 TP/SL 4/6、淨損益 -0.2935 USDT、價差 +2R。這是金額與 R 不可混稱的實際核對例。
5. 關閉空方儀表板後右側表格消失，多方保留；再開啟恢復。切換 1H 顯示切回 15m 提示；最後回到 15m。測試程式已從正式 TV 版本移除。
6. 靜態逐字比對：僅移除本次三個新增 input 及尾端 dashboard 區塊，整份來源即等同 baseline，交易核心及舊預設完整保留。`git diff --check` 通過。

如需重現原生測試，將正式 `tradingview/fvg_confluence_strategy_1a.pine` 加上換行及 `tests/pine/fvg_dashboard_contract_cases.pine` 放入臨時 Pine 腳本；先用同商品幣別的 BINANCE:BTCUSDT 15m 執行，再暫設非零 commission。footer 應為 PASS 17，任何數字不符會觸發 runtime.error。測完恢復正式來源及原輸入。測試附加區塊不可發佈為正式策略。

官方 API 與模擬成本說明：[TradingView Strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/)。本次沒有正式全期間回測、未推送遠端。Token／cache／費用 unavailable。
