# 本地市場資料同步

本專案透過 CCXT 從交易所增量取得已收盤的 1m K 線，保存到本地 DuckDB。同步器預設每 15 分鐘執行一次；回測時只讀本地資料，不會再次呼叫交易所 API。

## 初次同步

預設市場為 Binance USDT 永續合約 `BTC/USDT:USDT`：

```bash
./venv/bin/python ccxt_market_data.py --once --lookback-days 30
```

指定歷史起點：

```bash
./venv/bin/python ccxt_market_data.py --once --start 2024-07-01T00:00:00Z
```

## 每 15 分鐘持續同步

```bash
./venv/bin/python ccxt_market_data.py --interval-minutes 15
```

同步器會重抓最後五分鐘並以主鍵覆寫，避免資料斷線邊界遺漏；尚未收盤的 1m K 線不會寫入。

## 本地 NFE 回測

15m 訊號、1h 結構：

```bash
./venv/bin/python run_ccxt_local_backtest.py \
  --start 2025-01-01 \
  --end 2026-01-01 \
  --ltf 15m \
  --htf 1h
```

5m 訊號、1h 結構：

```bash
./venv/bin/python run_ccxt_local_backtest.py --ltf 5m --htf 1h
```

5m、15m、1h、4h、1d 都由本地 1m 資料統一生成。缺少任何一分鐘的聚合 K 棒會被排除，避免不完整 K 棒污染策略指標。

## 切換交易所或市場

使用 CCXT 的統一交易對格式，例如 OKX 永續合約：

```bash
./venv/bin/python ccxt_market_data.py \
  --exchange okx \
  --symbol BTC/USDT:USDT \
  --market-type swap \
  --interval-minutes 15
```

現貨 BTC/USDT：

```bash
./venv/bin/python ccxt_market_data.py \
  --symbol BTC/USDT \
  --market-type spot \
  --interval-minutes 15
```
