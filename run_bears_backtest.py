from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from bears_strategy import BearSStrategy
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from nfe_v4_strategy import NFEV4Strategy


DATA_DIR = Path("202101-202607_merged")
REPORT_DIR = Path("data/backtests/bears_20260717")


def config() -> StrategyConfig:
    return StrategyConfig(
        initial_balance=10_000.0,
        risk_pct=0.01,
        position_sizing_mode="risk_based",
        fixed_margin_usd=1_000.0,
        leverage=1.0,
        slippage_usd=15.0,
        limit_order_slippage_usd=5.0,
        stop_loss_slippage_usd=10.0,
        maker_fee=0.0002,
        taker_fee=0.0005,
        max_vol_pct=0.05,
        funding_rate_8h=0.0001,
        max_holding_bars=96,
        min_net_profit_r=3.0,
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
    )


def metrics(trades: list[dict], initial_balance: float, maker_fee: float) -> dict:
    if not trades:
        return {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "long_trades": 0,
            "short_trades": 0,
        }
    frame = pd.DataFrame(trades).sort_values("exit_time")
    frame["net_pnl"] = frame["pnl"] - frame["size"] * frame["entry_price"] * maker_fee
    equity = pd.Series([initial_balance, *(frame["entry_balance"] + frame["net_pnl"]).tolist()])
    drawdown = (equity / equity.cummax() - 1) * 100
    gross_profit = frame.loc[frame["net_pnl"] > 0, "net_pnl"].sum()
    gross_loss = -frame.loc[frame["net_pnl"] < 0, "net_pnl"].sum()
    final_balance = float(frame.iloc[-1]["entry_balance"] + frame.iloc[-1]["net_pnl"])
    return {
        "total_return_pct": round((final_balance / initial_balance - 1) * 100, 4),
        "max_drawdown_pct": round(float(drawdown.min()), 4),
        "trades": len(frame),
        "win_rate_pct": round(float((frame["net_pnl"] > 0).mean() * 100), 4),
        "profit_factor": round(float(gross_profit / gross_loss), 4) if gross_loss else None,
        "long_trades": int((frame["type"] == "LONG").sum()),
        "short_trades": int((frame["type"] == "SHORT").sum()),
    }


def run(label: str, strategy, cfg: StrategyConfig) -> dict:
    started = time.time()
    backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_dir=str(DATA_DIR), strategy=strategy)
    trades, missed = backtester.run_strategy(replace(cfg, mode="NONE"))
    result = {
        "label": label,
        "data_start": str(backtester.df_1h.index.min()),
        "data_end": str(backtester.df_1h.index.max()),
        "runtime_seconds": round(time.time() - started, 2),
        "metrics": metrics(trades, cfg.initial_balance, cfg.maker_fee),
        "missed_setups": len(missed),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(REPORT_DIR / f"{label}_trades.csv", index=False)
    (REPORT_DIR / f"{label}_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    cfg = config()
    baseline = run(
        "baseline_nfe_v4",
        NFEV4Strategy(
            htf="1h",
            htf_n=5,
            ltf_n=3,
            ob_range_type="full",
            min_rr=3.0,
            sl_padding=20.0,
            defensive_atr_mult=0.6,
        ),
        cfg,
    )
    candidate = run("candidate_bears", BearSStrategy(), cfg)
    baseline_metrics = baseline["metrics"]
    candidate_metrics = candidate["metrics"]
    drawdown_worsening = abs(candidate_metrics["max_drawdown_pct"]) - abs(baseline_metrics["max_drawdown_pct"])
    profit_factor_change = candidate_metrics["profit_factor"] / baseline_metrics["profit_factor"] - 1
    trade_count_change = candidate_metrics["trades"] / baseline_metrics["trades"] - 1
    alerts = []
    if drawdown_worsening >= 2:
        alerts.append("MAX_DRAWDOWN_WORSE_BY_2PP")
    if profit_factor_change <= -0.10:
        alerts.append("PROFIT_FACTOR_DOWN_10PCT")
    if abs(trade_count_change) >= 0.20:
        alerts.append("TRADE_COUNT_CHANGED_20PCT")
    comparison = {
        "command": "python3 run_bears_backtest.py",
        "config": asdict(cfg),
        "baseline": baseline,
        "candidate": candidate,
        "deltas": {
            "return_pct_points": round(candidate_metrics["total_return_pct"] - baseline_metrics["total_return_pct"], 4),
            "max_drawdown_worsening_pct_points": round(drawdown_worsening, 4),
            "profit_factor_relative_pct": round(profit_factor_change * 100, 2),
            "trade_count_relative_pct": round(trade_count_change * 100, 2),
        },
        "regression_alerts": alerts,
    }
    (REPORT_DIR / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
