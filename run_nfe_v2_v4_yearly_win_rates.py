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


def config():
    return StrategyConfig(initial_balance=10_000.0, risk_pct=0.01, position_sizing_mode="risk_based", fixed_margin_usd=1000.0, slippage_usd=15.0, limit_order_slippage_usd=5.0, stop_loss_slippage_usd=10.0, maker_fee=0.0002, taker_fee=0.0005, max_vol_pct=0.05, funding_rate_8h=0.0001, max_holding_bars=96, min_net_profit_r=3.0, enable_be=True, tp1_close_pct=0.5, be_trigger_ratio=1.5, mode="NONE")


def strategy_for(version):
    common = dict(htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0)
    return NFEV2Strategy(**common, use_dynamic_sl=True, sl_padding_atr_mult=0.3, use_trailing_stop=True) if version == "V2" else NFEV4Strategy(**common, defensive_atr_mult=0.3)


def main():
    cfg = config()
    rows = []
    original_cwd = os.getcwd()
    os.chdir(DATA_DIR)
    try:
        for version in ("V2", "V4"):
            backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_dir=".", strategy=strategy_for(version))
            trades, _ = backtester.run_strategy(replace(cfg, mode="NONE"))
            df = pd.DataFrame(trades)
            df["year"] = pd.to_datetime(df["exit_time"]).dt.year
            for (year, side), group in df.groupby(["year", "type"]):
                rows.append({"version": version, "year": year, "side": side, "trades": len(group), "win_rate_pct": round((group["pnl"] > 0).mean() * 100, 2), "net_pnl_usd": round(group["pnl"].sum(), 2)})
    finally:
        os.chdir(original_cwd)
    report = pd.DataFrame(rows).sort_values(["version", "year", "side"])
    report.to_csv(DATA_DIR / "nfe_v2_v4_yearly_win_rates.csv", index=False, encoding="utf-8-sig")
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
