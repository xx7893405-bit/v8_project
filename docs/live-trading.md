# 交易所下單（安全預設）

`run_live_trading.py` 預設只做 dry-run。下單使用 CCXT 統一交易對格式，預設為 Binance／OKX USDT 永續：`BTC/USDT:USDT`，並預設 isolated 保證金。

安裝依賴後，先執行 dry-run：

```bash
python3 run_live_trading.py --exchange binance --dry-run
```

需要 testnet API key 時，設定對應環境變數；OKX 需要額外設定 passphrase：

```bash
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
# OKX：OKX_API_KEY、OKX_API_SECRET、OKX_API_PASSWORD
python3 run_live_trading.py --exchange binance --live --sandbox
```

真實帳戶必須同時明確設定 `ALLOW_LIVE_TRADING=YES` 並使用 `--no-sandbox`：

```bash
export ALLOW_LIVE_TRADING=YES
python3 run_live_trading.py --exchange binance --live --no-sandbox
```

`--risk-pct` 不得超過 `--max-risk-pct`，預設為 1%／2%；`--max-leverage` 預設為 3 倍。API key 不應寫入程式碼或提交至 Git。

策略數量是基礎資產數量；adapter 會依交易所回報的 `contractSize` 轉成合約張數，再套用數量精度與最小下單量。持倉對帳會把交易所 contracts 轉回基礎資產數量，並保留交易所回報的槓桿、初始／維持保證金與清算價。

目前 adapter 也會處理槓桿上限、reduce-only 保護單、同方向持倉去重與反方向持倉衝突；實盤前仍應先以 testnet 驗證交易所帳戶模式、觸發單格式與最小下單量。
