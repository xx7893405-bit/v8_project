# V8 策略監控網站

啟動後開啟 <http://127.0.0.1:8787>：

```bash
python3 legacy/dashboard_server.py
```

網站使用既有 SSH 金鑰唯讀查詢 Oracle VM，預設位置為 `~/Downloads/ssh-key-2026-07-10.key`。可用環境變數覆寫：

```bash
V8_SSH_HOST=ubuntu@主機 V8_SSH_KEY=金鑰路徑 V8_DASHBOARD_PORT=8787 python3 legacy/dashboard_server.py
```

這是保留的舊版本機唯讀工具；正式網站在同層的 `../v8_strategy_monitor` 專案。若未來加入參數或策略控制，應先在獨立服務中加入驗證與確認機制。
