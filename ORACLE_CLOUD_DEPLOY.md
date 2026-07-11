# Oracle Cloud Always Free 部署

這個部署使用一台 Ubuntu VM 與 `systemd timer`。首次從固定起點建立 10,000 USDT forward-test 狀態；之後每 15 分鐘抓取所有尚未同步且已收盤的 1m K 線，只處理新的完整訊號 K 線，並接續保存餘額、持倉、掛單及交易。`as_of` 保證同一根 K 線不會重複入帳；手動重跑但沒有新 K 線時只會同步資料，不會改變績效。預設策略是 NFE V2，也可切換成 NFE V1 或 V8。

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
.venv/bin/python oracle_strategy_job.py --strategy nfe-v2 --risk-pct 0.05
jq . runtime/oracle_strategy_state.json
```

可用策略為 `nfe-v2`（預設）、`nfe`、`v8`。例如測試原始 NFE：

```bash
.venv/bin/python oracle_strategy_job.py --strategy nfe
```

## 3. 啟用 15 分鐘排程

```bash
sudo cp deploy/oracle/v8-strategy.service /etc/systemd/system/
sudo cp deploy/oracle/v8-strategy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now v8-strategy.timer
systemctl list-timers v8-strategy.timer
```

正式排程由 `deploy/oracle/v8-strategy.service` 內的 `STRATEGY=nfe-v2`、`RISK_PCT=0.05`、`MAX_LEVERAGE=1000`、`START_AT=2026-07-01T00:00:00Z` 決定。此 1000x 僅適用於紙上模擬，等同不以槓桿上限截斷倉位；仍會記錄有效槓桿與模擬強平價。更改後，重新複製 service 並執行 `sudo systemctl daemon-reload`。

查看執行結果與日誌：

```bash
cat /opt/v8_project/runtime/oracle_strategy_state.json
journalctl -u v8-strategy.service -n 100 --no-pager
systemctl status v8-strategy.timer
```

更新程式後執行：

```bash
cd /opt/v8_project
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo systemctl start v8-strategy.service
```

## 維運重點

- DuckDB 留在 Block Volume，重開機後資料仍在；首次預設回補 45 天，之後每次只抓尚未同步的 1m K 線（並重抓最後 5 分鐘，以主鍵覆寫）。
- `runtime/oracle_forward_start.json` 固定 forward-test 起點；`runtime/oracle_strategy_state.json` 是累積帳戶狀態。只有要建立全新的 10,000 USDT 測試時才刪除兩者。
- timer 使用 `Persistent=true`，VM 停機期間錯過排程，開機後會補跑一次。
- service 最長執行 12 分鐘；避免前一輪卡住撞上下一個 15 分鐘週期。systemd 不會同時啟動同一 service。
- `ProtectSystem=strict` 限制寫入範圍。若 VM 使用者不是 `ubuntu` 或專案路徑不同，必須同步修改 service 的 `User`、`WorkingDirectory`、`ExecStart` 和 `ReadWritePaths`。
- 建議另做每日 DuckDB 備份，並為 service failed、狀態檔過期（超過 20 分鐘）建立告警。
- Always Free VM 仍可能被 Oracle 判定為閒置而回收；15 分鐘小工作不能保證達到官方 CPU、網路與記憶體門檻。重要服務應升級 PAYG（並用 quota/budget 限制支出）或準備第二個外部監控/備援執行點。
