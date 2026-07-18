# Spot vs Perpetual 2021–2026 回測結果

## 結論

低期望不能只歸因於現貨／永續資料差異。價格來源會實質改變訊號與績效幅度，但在共同時間索引、相同合約成本與風險設定下：

- V2 在 Spot proxy 與 Perp 都維持正期望，Perp 表現較好。
- V2A 與 BearS 在兩邊都為負報酬、profit factor 都低於 1；Perp 的虧損更重。
- 因此 V2A／BearS 的低期望主要仍是策略進場／出場品質與成本承受能力問題，不能以「先前用了現貨資料」解釋；基差與 OHLC 差異是放大或減輕結果的次要因子。

本比較把 Spot 價格套入相同做空、槓桿、fee 與 funding 的合約經濟模型，只用來隔離價格資料影響，不代表可實際執行的現貨帳戶績效。

## 固定契約

- 資料期間：2021-01-01 00:00 至 2026-07-06 06:37 UTC。
- 共同 1m timestamps：2,896,605；共同 fingerprint：`d67917d4724ab20d`。
- 所有 5m／15m／1h／4h／1d 都從共同 1m 重建；兩市場索引完全相同，並同步排除不完整棒。
- 初始資金 10,000 USD；risk-based `risk_pct=5%`；槓桿上限 `20x`。
- maker 0.02%、taker 0.05%；相同滑價；固定 funding fallback 0.01%/8h。
- V2：15m，最長 96 bars；V2A：5m、延遲 90m，最長 288 bars；BearS：1h，最長 24 bars。

## 全期結果

| 策略 | 市場價格 | 報酬 | MDD | 交易 | 勝率 | PF | 平均每筆 PnL | 平均實現 R |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| V2 | Spot proxy | +133.5406% | -47.4755% | 94 | 38.2979% | 1.4553 | +142.06 | +0.2447 |
| V2 | Perp | +198.5200% | -36.5451% | 88 | 39.7727% | 1.7941 | +225.59 | +0.3062 |
| V2A | Spot proxy | -32.6988% | -73.1563% | 288 | 39.9306% | 0.9149 | -11.35 | -0.0542 |
| V2A | Perp | -67.6774% | -74.6945% | 280 | 37.8571% | 0.7729 | -24.17 | -0.0877 |
| BearS | Spot proxy | -62.2611% | -93.0131% | 191 | 19.8953% | 0.8670 | -32.60 | +0.0143 |
| BearS | Perp | -92.0797% | -96.1838% | 213 | 17.3709% | 0.5214 | -43.23 | -0.1276 |

BearS Spot proxy 的平均實現 R 微正但淨 PnL 為負，顯示未扣成本的 R 路徑不足以承受 fee、funding 與複利倉位變化，不能視為正期望。

## 市場與交易重疊

- close correlation：0.99999942；1m return correlation：0.98828613。
- median Perp-vs-Spot basis：-3.9148 bps；p95 absolute basis：9.9271 bps。
- V2：61 筆匹配，Spot／Perp match rate 64.89%／69.32%；56 筆完全同時。
- V2A：178 筆匹配，61.81%／63.57%；157 筆完全同時。
- BearS：115 筆匹配，60.21%／53.99%；105 筆完全同時。

約三至四成交易只存在單一價格來源，證明小幅 basis／OHLC 差異會跨過策略的離散門檻；但高度同時的共同交易與兩邊一致的 PF 正負方向，也證明資料來源不是 V2A／BearS 低期望的唯一或主要解釋。

## 可重現位置與限制

- 執行：`venv/bin/python run_spot_perp_comparison.py --run-id 20260718_btcusdt_spot_vs_perp_risk5_lev20`
- 報告：`reports/spot_perp_benchmark/20260718_btcusdt_spot_vs_perp_risk5_lev20_d67917d4724ab20d/`
- 六份 trade ledger 均已核對：`10,000 + sum(trade.pnl) == final_balance`。
- 本輪 MDD 仍以已平倉 equity 計算，未包含持倉中 mark-to-market；未使用歷史 funding／mark-price，故不能宣稱為精準的實盤合約績效。
