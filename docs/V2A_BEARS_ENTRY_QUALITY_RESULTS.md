# V2A／BearS 進場品質單變因結果

## 結論

- V2A 的 0.10% 最小停損門檻有改善，但 PF 仍只有 0.7912，不接受。
- V2A 延遲期間 TP1 過期重驗證使績效惡化，不接受。
- BearS Fib 0.5-only 接近損益平衡，但 PF 0.9584，未通過。
- BearS Triple-only 通過第一階段數值門檻：85 trades、+11.2199%、PF 1.0496、MDD -70.5630%、最大勝單占總獲利 15.8624%。但分年度與空單不穩定，只接受為下一輪研究候選，不取代 baseline。
- BearS Fib 0.5 + Triple 為診斷組，雖然 +28.1714%、PF 1.1660，但只有 30 trades，低於 50 筆門檻，不接受。

POC 實驗不在本分支，也未參與任何候選。

## 固定契約

- Binance USDT-M `BTC/USDT:USDT` closed 1m；snapshot `ea28b7ca3c90c46b`
- 2021-01-01～2026-07-18 13:51 UTC；另跑 2026-07 MTD
- 10,000 USD；risk-based 5%；槓桿上限 20x
- maker 0.02%；taker 0.05%；fixed funding fallback 0.01%/8h
- V2A：5m、訊號 K 收盤後延遲 90m、max holding 288 bars
- BearS：1h、max holding 24 bars

## 全期結果

| Strategy | Return | MDD | Trades | Win | PF | Avg R | Quick exit | Top win share | Filtered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V2A baseline | -69.9109% | -74.6945% | 282 | 37.5887% | 0.7642 | -0.0921 | 28.0142% | 9.1809% | 0 |
| V2A min stop 0.10% | -62.6156% | -73.5776% | 266 | 38.3459% | 0.7912 | -0.0618 | 25.9398% | 9.0532% | 290 |
| V2A delay TP1 revalidate | -72.1689% | -77.9336% | 274 | 36.8613% | 0.7513 | -0.1000 | 28.1022% | 10.1686% | 49 |
| BearS baseline | -93.2480% | -96.3746% | 216 | 17.1296% | 0.5058 | -0.1402 | 55.0926% | 31.5190% | 0 |
| BearS Fib 0.5 | -20.2362% | -65.4930% | 90 | 22.2222% | 0.9584 | +0.0630 | 45.5556% | 10.4419% | 224 |
| BearS Triple | +11.2199% | -70.5630% | 85 | 20.0000% | 1.0496 | +0.1981 | 50.5882% | 15.8624% | 219 |
| BearS Fib 0.5 + Triple (diagnostic) | +28.1714% | -31.7958% | 30 | 23.3333% | 1.1660 | +0.3261 | 46.6667% | 24.3564% | Fib 225 / Triple 229 |

Filter counters 不是直接從 baseline trades 扣除：過濾後會釋放資金與持倉互斥，使後續可見 setup 改變，因此可能大於最終交易差額。

## 穩定性判讀

BearS Triple 的 LONG 為 +34.6611%、36 trades、PF 1.3594；SHORT 為 -21.6891%、49 trades、PF 0.8392，且 short-side MDD -80.1263%。分年度 2021、2022 為負，2023～2026 轉正；2026 只有 4 筆，不能把近期 +79.4782%視為穩定。

Fib 0.5 + Triple 的 LONG 為 +45.1593%、PF 1.6350，但只有 15 筆；SHORT 為 -12.2222%、PF 0.8277。這支持下一輪只研究 BearS Triple LONG，但不足以直接改預設策略。

V2A min-stop 只有 2025 年 PF>1；LONG／SHORT PF 分別 0.7736／0.8060，問題並非單一方向。0.10% 門檻改善幅度不足，不進一步用參數網格尋找漂亮門檻。

## 2026-07 MTD

- V2A 三組都只有 1 筆成交且 -5.1183%，不可判讀。
- BearS Triple 有 1 筆，-5.5730%；Fib 0.5 與組合診斷為 0 筆。

## 重現與驗證

```bash
python run_entry_quality_comparison.py \
  --run-id 20260718_btcusdt_entry_quality_risk5_lev20
```

正式產物：`reports/entry_quality_benchmark/20260718_btcusdt_entry_quality_risk5_lev20_ea28b7ca3c90c46b/`。

- baseline 精確重現既有 V2A／BearS return、trades、PF
- 75 項 unittest、py_compile、diff-check 通過
- DB SHA-256 與 canonical manifest 一致
- 每組 trade ledger 與 final balance 一致
- 報告包含分年度、LONG／SHORT、實現 R、快停、損平勝率與獲利集中度

## 限制

- 歷史 funding 與 mark-price 尚未整合；MDD 為已平倉 equity，不含持倉中 mark-to-market。
- 5% risk／20x 上限會放大負期望與交易順序效應。
- Triple 與 Fib 候選源自同一 in-sample 診斷；下一步必須做 long-only 獨立候選及 walk-forward／out-of-sample 檢查。
