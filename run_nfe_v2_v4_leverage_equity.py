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
STARTING_BALANCE = 10_000.0

# 測試的五種組合
RUN_CONFIGS = [
    {"name": "V2 (1%)", "version": "V2", "risk": 0.01, "color": "#3b82f6"}, # 經典藍
    {"name": "V2 (5%)", "version": "V2", "risk": 0.05, "color": "#1d4ed8"}, # 深藍
    {"name": "V4 (1%)", "version": "V4", "risk": 0.01, "color": "#10b981"}, # 翡翠綠
    {"name": "V4 (5%)", "version": "V4", "risk": 0.05, "color": "#047857"}, # 深綠
]

def strategy_for(version):
    common = dict(htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0)
    if version == "V2":
        return NFEV2Strategy(**common, use_dynamic_sl=True, sl_padding_atr_mult=0.5, use_trailing_stop=True)
    return NFEV4Strategy(**common, defensive_atr_mult=0.6)

def base_config(risk_pct):
    return StrategyConfig(
        initial_balance=STARTING_BALANCE, risk_pct=risk_pct, position_sizing_mode="risk_based",
        fixed_margin_usd=1000.0, slippage_usd=15.0, limit_order_slippage_usd=5.0,
        stop_loss_slippage_usd=10.0, maker_fee=0.0002, taker_fee=0.0005, max_vol_pct=0.05,
        funding_rate_8h=0.0001, max_holding_bars=96, min_net_profit_r=3.0,
        enable_be=True, tp1_close_pct=0.5, be_trigger_ratio=1.5,
    )

def monthly_equity(trades, months, maker_fee):
    if not trades:
        # 如果無交易，全段保持起始資金
        return pd.Series(STARTING_BALANCE, index=months)
    exits = pd.DataFrame(trades)
    exits["exit_time"] = pd.to_datetime(exits["exit_time"])
    exits["equity"] = exits["entry_balance"] + exits["pnl"] - (exits["size"] * exits["entry_price"] * maker_fee)
    exits = exits.sort_values("exit_time").set_index("exit_time")
    equity = exits["equity"].resample("ME").last().reindex(months).ffill().fillna(STARTING_BALANCE)
    return equity.round(2)

def buy_and_hold(source, date_column, months):
    prices = source.assign(**{date_column: pd.to_datetime(source[date_column])}).set_index(date_column)["close"]
    return (STARTING_BALANCE * prices.resample("ME").last().reindex(months).ffill() / prices.iloc[0]).round(2)

def svg_chart(months, curves, destination):
    width, height, left, right, top, bottom = 1200, 620, 82, 32, 30, 75
    values = [value for curve in curves.values() for value in curve]
    low, high = min(values), max(values)
    padding = max((high - low) * 0.08, 100)
    low, high = low - padding, high + padding
    plot_w, plot_h = width - left - right, height - top - bottom
    x = lambda i: left + plot_w * i / max(len(months) - 1, 1)
    y = lambda value: top + (high - value) * plot_h / (high - low)
    
    colors = {
        "V2 (1%)": "#60a5fa", 
        "V2 (5%)": "#1d4ed8", 
        "V4 (1%)": "#34d399", 
        "V4 (5%)": "#047857", 
        "BTC 長抱": "#9333ea"
    }
    
    ticks = [low + (high - low) * i / 5 for i in range(6)]
    grid = "".join(
        f'<line x1="{left}" y1="{y(t):.1f}" x2="{width-right}" y2="{y(t):.1f}" class="grid"/><text x="{left-12}" y="{y(t)+5:.1f}" text-anchor="end">${t:,.0f}</text>'
        for t in ticks
    )
    labels = "".join(
        f'<text x="{x(i):.1f}" y="{height-bottom+28}" text-anchor="middle">{month.strftime("%Y-%m")}</text>'
        for i, month in enumerate(months) if i == 0 or i == len(months) - 1 or month.month == 1
    )
    lines = "".join(
        f'<polyline points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(curve))}" stroke="{colors[name]}"/>'
        for name, curve in curves.items()
    )
    legend = "".join(
        f'<g transform="translate({left + i * 200}, {height - 22})"><line x1="0" y1="0" x2="30" y2="0" stroke="{colors[name]}"/><text x="40" y="5">{name}: ${list(curve)[-1]:,.0f}</text></g>'
        for i, (name, curve) in enumerate(curves.items())
    )
    destination.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="NFE V2 and V4 monthly leverage equity curves">
<style>text{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#334155}} .grid{{stroke:#e2e8f0;stroke-width:1}} polyline{{fill:none;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}}</style>
<rect width="100%" height="100%" fill="white"/><text x="{left}" y="18" font-size="18" font-weight="600">NFE V2 / V4 不同風險比例與 BTC 長抱對比（月末資金；起始 $10,000）</text>{grid}{labels}{lines}{legend}</svg>''', encoding="utf-8")

def main():
    if not DATA_DIR.exists():
        raise FileNotFoundError(DATA_DIR)
    source = pd.read_csv(DATA_DIR / "btc_15m.csv")
    date_column = next(column for column in source if column.lower() in {"timestamp", "time", "date", "datetime"})
    months = pd.date_range(pd.to_datetime(source[date_column]).min(), pd.to_datetime(source[date_column]).max(), freq="ME")
    
    curves = {}
    original_cwd = os.getcwd()
    os.chdir(DATA_DIR)
    
    try:
        for cfg_item in RUN_CONFIGS:
            name = cfg_item["name"]
            version = cfg_item["version"]
            risk = cfg_item["risk"]
            
            print(f"Running {name}...")
            cfg = base_config(risk)
            backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_dir=".", strategy=strategy_for(version))
            trades, _ = backtester.run_strategy(replace(cfg, mode="NONE"))
            curves[name] = monthly_equity(trades, months, backtester.config.maker_fee)
    finally:
        os.chdir(original_cwd)
        
    curves["BTC 長抱"] = buy_and_hold(source, date_column, months)
    
    report = pd.DataFrame({"month": months.strftime("%Y-%m"), **{name: curve.values for name, curve in curves.items()}})
    report.to_csv(DATA_DIR / "nfe_v2_v4_leverage_equity.csv", index=False, encoding="utf-8-sig")
    
    svg_chart(months, curves, DATA_DIR / "nfe_v2_v4_leverage_curve.svg")
    print(report.to_string(index=False))
    print(f"\nWrote {DATA_DIR / 'nfe_v2_v4_leverage_equity.csv'}")
    print(f"Wrote {DATA_DIR / 'nfe_v2_v4_leverage_curve.svg'}")

if __name__ == "__main__":
    main()
