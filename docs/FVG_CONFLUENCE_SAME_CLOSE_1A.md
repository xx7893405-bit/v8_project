# FVG 1.0A：1H 確認同收盤判定

日期：2026-09-29。規格／單一實作票：[Issue #204](https://github.com/xx7893405-bit/v8_project/issues/204)。
分支 `codex/fvg-confluence-same-close`；凍結程式基準 `61ce4be`（TV 私有 v21）。只修改原生 Pine 模擬版，不修改視覺基準指標、V2 或 SMC-V2。

## 已核准語義

- 14:00–15:00 的 1H 在 15:00 確認時，可立即檢查 **14:45–15:00** 這根 15m；不回看並追認 14:00、14:15、14:30 的 K。
- 當根確認的 1H／15m FVG 可一起形成有效重疊，立即判定當根。舊 1H 配上普通新 15m FVG，維持下一根 eligibility。
- 需先觸碰開關、50/20 等參數、失效優先、方向阻擋、每來源一次及多空各一筆均沿用。關鍵 K 當根是觀察第 1 根。
- `process_orders_on_close=false`；確認後送單，下一根可成交 tick（歷史為下一根開盤）成交。不得回填過去的訊號或價格。
- 矩形左界仍為第三根 1H 的開盤時間；來源識別仍是確認收盤時間。

## 實作

保留 offset-1/lookahead-on 的已確認前一小時資料作缺棒 fallback，另讀取 lookahead-off 當小時封包。當小時資料只在正常訊號引擎、已確認 15m、兩週期收盤時間完全相等時消費；成交回呼不執行訊號引擎。以 `lastReleasedHtf` 去重，每個小時即使沒有 FVG 也記錄釋放。缺少最後一根 15m 時保守延後，不回補過去訊號。

1H 檢視依序重播 15m，只有最後同收盤 intrabar 能用該小時新封包；hour seed 只可用前一小時 fallback。新增資料欄位的 plot 也只在實際釋放時顯示。

## 驗證證據

- 紅燈：TV v22 原版釋放語義的原生案例在 bar 0 失敗：`SAME CLOSE FAIL: last 15m is available at 1H close`。
- 綠燈：TV v23，兩份實例各 **18** 項原生斷言，涵蓋早一根／未確認禁止、同收盤、重複／缺棒 fallback、多空、觸碰、收盤失效優先與不追認早期 K；15m、1H 均顯示 18。
- 整合：TV v24，BINANCE:BTCUSDT 15m 上兩份實例各 **499** 次 1H 收盤，當前／第 1 根 FVG 的高低價均與四根 15m 重建相符。多方 **21**、空方 **11** 筆原生進場檢查通過：確認後成交、來源不重複；成交回呼核對下一根開盤的 bar index 與價格。
- 實例：新版多方 `Z96`、來源確認時間 2026-09-29 15:00 UTC+8（entry note 使用交易所 UTC，顯示 07:00），在 **15:00／84,007.07** 成交。舊版同來源當時未進場。未將 14:00 大陽線回填為關鍵 K。
- 最終 TV 私有 **v25** 已移除全部測試探針。全碼讀回 **72,764 字元，FNV32 `6d681b2c`**，與本地一致。SHA-256 `16f9a9090a885c0d40e5fdbc3f8e4c6e911e593af4856ce25be45999282b302e`。
- 保存 layout 後重載雲端，仍為 v25；再次全碼讀回完全一致，15m／多方顯示／空方隱藏均保留。
- 基準靜態對照確認 input 順序與預設、strategy Properties、觀察／停損停利／入場資格 helper 與 fill scheduler 逐字未變。
- `git diff --check` 通過；測試 builder 產生 18 項原生 fixture（不是本地 Pine 執行器）。

重現：

```sh
rtk python3 tests/pine/build_fvg_sim_tests.py --mode same-close --output /tmp/fvg-same-close-contract.pine
```

合約檔可單獨在 TV 執行；實際交付驗證是在既有策略暫附 `fvg_same_close_contract_cases.pine` 與 `fvg_same_close_live_cases.pine`。後者限定本次無滑價／正常 15m K 的整合資料，不能套用到有滑價或非標準圖後仍要求成交價等於 open。

## 修改前後有限對照

同一 TV 載入範圍 2026-09-08～09-29、BINANCE:BTCUSDT 現貨 15m、固定 0.001、資金 100,000 USDT、1x、費率／滑價 0、原生 4 ticks/bar，無更動 Properties。多方：50%、20%、96、觸碰 OFF、反向 veto ON、SL buffer 1%、TP 2R。

| 原生報表 | 基準 v21 | 新版 v23/v25 |
|---|---:|---:|
| 已出場 | 21 | 20 |
| 未出場 | 0 | 1 |
| 勝／負 | 6／15 | 4／16 |
| 勝率 | 28.57% | 20.00% |
| 已實現淨額（USDT，UI 精度） | +0.97 | 約 -2.11（gross 3.09 − 5.20） |
| PF | 1.206 | 0.595 |
| 最大回撤（USDT，UI 快照） | 2.55 | 2.86 |
| UI 報酬顯示 | +0.00% | 0.00% |

來源更早被使用會改變後續機會；結果沒有支持績效提升。此為相同設定的原生圖表行為對照，並非凍結 OHLCV 檔的正式公平回測：末端行情仍在更新，新版有未平倉單，Total PnL 與回撤可能隨行情變動；上述已實現額為畫面四捨五入值，未以浮動總損益充當已平倉績效。不報 Sharpe／Sortino／年度結果。

## 交付限制

1H UI 驗證只證明有限歷史的原生執行與顯示；沒有宣稱全市場逐棒 parity。TV 1H intrabar 歷史仍有 2000 根窗口。尚未等待長時間即時 forward 樣本；正常收盤 guard、原生歷史與重載驗證不能替代長期 repaint 觀察。

TV 仍可能因 `calc_on_order_fills` 顯示通用 look-ahead 警示；本次檢查未以該警示為通過／失敗的替代證據。未執行正式 V8 回測、實盤、push。保留原來長方顯示、空方隱藏、儀表板關閉與輸入參數。

成本：原生 runtime、token、cache、費用 unavailable；只進行上述有限原生驗證，不新增全期計算。
