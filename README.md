# V8 策略研究與紙上交易

這個專案分成三條資料流：

- `nfe_*_strategy.py`、`v8_strategy.py`：策略規則與訊號。
- `backtest.py`、`strategy_engine.py`、`run_*_backtest.py`：歷史回測與研究實驗。
- `oracle_strategy_job.py`、`deploy/oracle/`：Oracle VM 上每 15 分鐘執行的紙上策略。

市場資料與回測產物是本機資料，不提交到 Git。即時策略完成後會把唯讀狀態回報到獨立網站專案 `../v8_strategy_monitor`；網站不包含交易邏輯，也不會送出真實委託。

## 常用入口

```bash
python oracle_strategy_job.py --strategy nfe-v2
python run_nfe_v2_backtest.py
python run_nfe_v4_backtest.py
```

網站、發布與網站資料庫請在同層的 `v8_strategy_monitor` 專案管理。
