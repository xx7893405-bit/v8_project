# Oracle Cloud Always Free 部署

這個部署使用一台 Ubuntu VM 與 `systemd timer`。每個紙上帳戶有固定的 `account_id`、策略與獨立帳本；首次從固定起點建立 10,000 USDT 狀態，之後每 15 分鐘接續保存餘額、持倉、掛單及交易。

> 這是策略觀察與紙上判定，不會送出真實交易委託。上線交易前仍需另外處理 API 金鑰、風控、冪等委託與告警。

## 1. 建立免費 VM

在帳戶的 Home Region 建立 `VM.Standard.A1.Flex`、Ubuntu 24.04、2 OCPU / 12 GB RAM，Boot Volume 保持免費額度內。安全清單只開 SSH 22，來源限制為自己的 IP；本工作不需開放 HTTP。

## 2. 安裝專案

```bash
sudo mkdir -p /opt/v8_project
sudo chown ubuntu:ubuntu /opt/v8_project
git clone <你的-repository-url> /opt/v8_project
cd /opt/v8_project
sudo apt update
sudo apt install -y python3-venv build-essential
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p data runtime
```

先手動驗證一次（首次會回補 45 天）：

```bash
cd /opt/v8_project
.venv/bin/python oracle_strategy_job.py --account-id paper-nfe-v2 --strategy nfe-v2 --risk-pct 0.05 --state-path runtime/accounts/paper-nfe-v2/state.json --forward-start-path runtime/accounts/paper-nfe-v2/forward_start.json --events-path runtime/accounts/paper-nfe-v2/events.jsonl
jq . runtime/accounts/paper-nfe-v2/state.json
```

可用策略為 `nfe-v2`（預設）、`nfe`、`v8`。例如測試原始 NFE：

```bash
.venv/bin/python oracle_strategy_job.py --strategy nfe
```

## 3. 啟用 15 分鐘排程

```bash
sudo cp deploy/oracle/nfe-*-strategy.service deploy/oracle/nfe-*-strategy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nfe-v2-strategy.timer nfe-v4-strategy.timer
systemctl list-timers nfe-v2-strategy.timer nfe-v4-strategy.timer
```

正式排程分別由 `nfe-v2-strategy.service` 與 `nfe-v4-strategy.service` 決定。新增策略時必須配置唯一 `ACCOUNT_ID`，並使用 `runtime/accounts/${ACCOUNT_ID}/` 下的獨立狀態、起點與事件檔。

多幣種帳戶使用 `portfolio-account@.service`／`portfolio-account@.timer` template。先將帳戶設定放在 `runtime/accounts/<account_id>/config.json`，再啟用對應 timer：

```bash
sudo cp deploy/oracle/portfolio-account@.service deploy/oracle/portfolio-account@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now portfolio-account@paper-user-001.timer
```

設定中的每個 symbol 只能指定一個 strategy；新增 symbol 只能消耗該帳戶的 `unallocated_balance`，不能重用其他 symbol 的資金。

若要在新進場或平倉時收到 Telegram 通知，建立 `/etc/v8_project/telegram.env`（不要提交到 Git）：

```bash
sudo install -d -m 700 /etc/v8_project
sudo sh -c 'printf "TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n" "<bot-token>" "<chat-id>" > /etc/v8_project/telegram.env'
sudo chmod 600 /etc/v8_project/telegram.env
sudo systemctl daemon-reload
```

未設定這兩個變數時，策略仍會執行，但不會發送 Telegram 訊息。

查看執行結果與日誌：

```bash
jq '{account_id, strategy, evaluated_at, snapshot}' /opt/v8_project/runtime/accounts/*/state.json
journalctl -u nfe-v2-strategy.service -u nfe-v4-strategy.service -n 100 --no-pager
systemctl status nfe-v2-strategy.timer nfe-v4-strategy.timer
```

更新程式後執行：

```bash
cd /opt/v8_project
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo systemctl start nfe-v2-strategy.service nfe-v4-strategy.service
```

## 維運重點

- DuckDB 留在 Block Volume，重開機後資料仍在；首次預設回補 45 天，之後每次只抓尚未同步的 1m K 線（並重抓最後 5 分鐘，以主鍵覆寫）。
- `runtime/accounts/<account_id>/forward_start.json` 固定測試起點；同目錄的 `state.json` 是該帳戶累積狀態。只有要建立全新的 10,000 USDT 測試時才刪除該帳戶目錄。
- timer 使用 `Persistent=true`，VM 停機期間錯過排程，開機後會補跑一次。
- service 最長執行 12 分鐘；避免前一輪卡住撞上下一個 15 分鐘週期。systemd 不會同時啟動同一 service。
- `ProtectSystem=strict` 限制寫入範圍。若 VM 使用者不是 `ubuntu` 或專案路徑不同，必須同步修改 service 的 `User`、`WorkingDirectory`、`ExecStart` 和 `ReadWritePaths`。
- 建議另做每日 DuckDB 備份，並為 service failed、狀態檔過期（超過 20 分鐘）建立告警。
- Always Free VM 仍可能被 Oracle 判定為閒置而回收；15 分鐘小工作不能保證達到官方 CPU、網路與記憶體門檻。重要服務應升級 PAYG（並用 quota/budget 限制支出）或準備第二個外部監控/備援執行點。
