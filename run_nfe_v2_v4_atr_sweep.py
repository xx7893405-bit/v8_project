import os
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from nfe_v2_strategy import NFEV2Strategy
from nfe_v4_strategy import NFEV4Strategy


DATA_DIR = Path("202101-202607_merged")
ATR_MULTIPLIERS = (0.3, 0.4, 0.5, 0.6, 0.7)
PERIODS = {"train": ("2021-01-01", "2024-12-31"), "test": ("2025-01-01", "2026-06-30")}


def base_config():
    return StrategyConfig(
        initial_balance=10_000.0, risk_pct=0.01, position_sizing_mode="risk_based",
        fixed_margin_usd=1000.0, slippage_usd=15.0, limit_order_slippage_usd=5.0,
        stop_loss_slippage_usd=10.0, maker_fee=0.0002, taker_fee=0.0005, max_vol_pct=0.05,
        funding_rate_8h=0.0001, max_holding_bars=96, min_net_profit_r=3.0,
        enable_be=True, tp1_close_pct=0.5, be_trigger_ratio=1.5, mode="NONE",
    )


def strategy_for(version, atr_mult):
    common = dict(htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0)
    if version == "V2":
        return NFEV2Strategy(**common, use_dynamic_sl=True, sl_padding_atr_mult=atr_mult, use_trailing_stop=True)
    return NFEV4Strategy(**common, defensive_atr_mult=atr_mult)


def restrict_period(backtester, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    backtester.df_15m = backtester.df_15m.loc[start:end]
    if not backtester.df_5m.empty:
        backtester.df_5m = backtester.df_5m.loc[start:end]
    backtester.df_1h = backtester.df_1h.loc[start - pd.Timedelta(days=10):end]
    backtester.df_4h = backtester.df_4h.loc[start - pd.Timedelta(days=15):end]
    backtester.df_1d = backtester.df_1d.loc[start - pd.Timedelta(days=30):end]


def run(version, atr_mult, period):
    cfg = base_config()
    start, end = PERIODS[period]
    backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_dir=".", strategy=strategy_for(version, atr_mult))
    restrict_period(backtester, start, end)
    session = backtester.run_session(**replace(cfg, mode="NONE").to_run_config().__dict__)
    return {"version": version, "atr_mult": atr_mult, "period": period, "trades": len(session.trades), "ending_balance": round(session.balance, 2), "return_pct": round((session.balance / cfg.initial_balance - 1) * 100, 2)}


def main():
    original_cwd = os.getcwd()
    os.chdir(DATA_DIR)
    try:
        results = [run(version, atr, period) for version in ("V2", "V4") for atr in ATR_MULTIPLIERS for period in PERIODS]
    finally:
        os.chdir(original_cwd)
    report = pd.DataFrame(results)
    pivot = report.pivot(index=["version", "atr_mult"], columns="period", values=["return_pct", "trades"]).reset_index()
    pivot.columns = ["_".join(str(part) for part in col if part) for col in pivot.columns]
    pivot.to_csv(DATA_DIR / "nfe_v2_v4_atr_sweep.csv", index=False, encoding="utf-8-sig")
    print(pivot.sort_values("return_pct_test", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
