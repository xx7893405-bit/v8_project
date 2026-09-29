# FVG 1.0A 可選首次觸碰重疊區

2026-09-29；Issue #203；baseline `20a7a42`；分支 `codex/fvg-confluence-touch-option`。

## 使用方式與契約

TradingView 私人腳本「V8 FVG 共振 1.0A｜多空獨立」v4，Inputs／觀察新增 **需先觸碰重疊區才開始觀察**，預設開啟。

- 開啟：保持舊版；等待首次 touch，該根為觀察第 1 根。
- 關閉：仍須有效同方向 1H／15m 重疊與來源鎖定，從既有 eligibility 的第一根已收盤 15m K 開始觀察，可在同根成為關鍵 K，不要求回踩。
- #203 當時契約：已確認 1H 新建重疊沿用當根 15m eligibility；15m FVG 收盤新建重疊沿用下一根 eligibility。後續 #204 允許新 1H 與同收盤 15m 當根判定，其餘新 15m 仍維持下一根；見 `FVG_CONFLUENCE_SAME_CLOSE_1A.md`。
- 關閉後同樣只觀察 96 根（可調），第 96 根可成立關鍵 K，否則到期；第 97 根不得成立。之後的 touch 不會重置時鐘。
- 收盤失效優先；位移／影線門檻、反向 FVG veto、每来源一次、多空各一筆、SL/TP 及下一根開盤成交均保留。
- 免觸碰狀態文字為「免觸碰觀察」，事件為「開始觀察（免觸碰）」。`首次進區數` 只計算觸碰模式啟動，不把免觸碰啟動算作碰觸。

兩個原生策略實例需各自設定這個開關。交付時兩份皆還原開啟，方向仍為僅做多／僅做空，FVG 圖形只由多方實例顯示。新 input 附加於既有 inputs 末尾以保留 instance input IDs，分組仍出現在「觀察」。

切換會重算歷史。更早的關鍵 K 可能先消耗該來源；較早進場也可能延長持倉而阻擋後續同向交易。因此取消 touch 不保證特定截圖的 08:45 棒一定變成第一根關鍵 K，也不保證交易總筆數增加。

## 驗證證據

1. Native red：旧 `f_step` 收到新參數時，Pine 回報 `Passed 17 arguments but expected 16 (CE10115)`。
2. Native green：先通過 1 項，再在原有兩個策略實例暫加診斷 fixture；兩份均顯示 **Observation assertions passed = 22.00**、**ON baseline cases passed = 640.00**。測試涵蓋多空免觸碰、未確認／未 eligible、方向／位移／影線、失效優先、96／97 邊界、後續 touch 不重置及終態不復活。
3. 640 組有限合成狀態同時比較新函式的省略參數與 explicit ON，兩者都逐欄等同凍結於測試檔的 `20a7a42` 函式。這不是全市場回測。
4. 測試 fixture 的 screenshot-OHLC 案例使用合成區域 119.3～119.4、合成 1H 寬度 1，不代表已驗證 SOL 截圖的實際來源寬度／鎖定歷程。
5. 正式 v4 原生編譯／兩份更新成功；完整複製回讀 59,055 字元、887 行，FNV32 `c33ed778`，與本地一致。診斷 helpers／plots 已從正式腳本移除，未新增測試圖表實例。
6. ON 與 baseline：同一 BINANCE:BTCUSDT 現貨、15m、09-08～09-29 載入範圍、相同參數及零成本下，空方已平倉 #11～#5 共七筆的完整可見文字完全相同。原即時 #12 出場時間 09:32 在重算後成為历史 09:30；價格不變，因此不把該筆當作歷史逐字 parity 證據。
7. UI 分別切換兩份 OFF，確認 checkbox 狀態及原生交易清單改變；多方可見最新編號由 16 變 21，空方由 12 筆已平倉變為 7 筆已平倉 + 1 筆持倉。空 Z68 在 OFF 於 09-24 11:30／84,056.01 進場且驗證時仍持有；ON 為 09-24 22:45／84,413.66 進場、09-28 17:00 TP。僅作開關與持倉名額的行為診斷，非績效比較。
8. 還原空方 ON 後整個可見清單與新版初始 ON 相同；兩份方向、原數值參數、FVG overlay、交易線／標籤及各自開關已核對，圖表已儲存。未變更使用者其他指標。
9. `SIM CONTRACT FUNCTIONS`、`SIM SCHEDULER` 與 `20a7a42` 逐字相同；原視覺 Pine 不變。原 23 項 simulation 契約沿用 baseline 證據，本次不宣稱重跑。

TV 方案不允許再添加測試指標，因此透過更新現有策略暫時執行測試，最後恢復正式程式；沒有升級方案或刪除其他指標。UI 看得到 checkbox 並實際改變交易；免觸碰文字分支已檢查原始碼，未宣稱在目前歷史視窗看見仍活動的免觸碰區。

## 重現、限制與回復

```sh
rtk proxy python3 tests/pine/build_fvg_sim_tests.py --mode observation --output /private/tmp/fvg-observation-tests.pine
rtk proxy python3 -X pycache_prefix=/private/tmp/fvg-pycache -m py_compile tests/pine/build_fvg_sim_tests.py
rtk git diff --check
```

生成器只抽取 production helper 並產生 Pine，必須在 TV 執行才算通過。新增測試檔包含 frozen baseline 與 22 項字面預期以及 640 組 ON 對照矩陣；若無法新增指標，可暫把案例接到現有策略末尾驗證後移除。

兩份原生策略的資金和報表仍獨立。`calc_on_order_fills=true` 的 TV 通用警示保留；native OHLC path、未開 Bar Magnifier，沒有新增长期即時或跨平台 parity 證據。本次未跑正式 V8 回測／實盤／push，未改 V2/SMC-V2。舊版文件與 manifest 保存當時證據，回復來源為 `20a7a42`。

單一寫入者；變更範圍為獨立 Pine、native fixture、驗證文件及 checkout 狀態。token／cache／費用與完整執行秒數沒有可信實測，均為 unavailable。
