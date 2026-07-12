import os
import sys
from dataclasses import replace
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from market_data import CSVMarketDataFeed
from nfe_v2_strategy import NFEV2Strategy
from nfe_v4_strategy import NFEV4Strategy

DATA_DIR = Path("202101-202607_merged")
STARTING_BALANCE = 10_000.0

def get_strategy(version: str, coin: str):
    common = dict(htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0)
    if version == "V2":
        return NFEV2Strategy(**common, use_dynamic_sl=True, sl_padding_atr_mult=0.5, use_trailing_stop=True)
    return NFEV4Strategy(**common, defensive_atr_mult=0.6)

def run_backtest(coin: str, version: str, risk_pct: float, leverage: float):
    # 建立自訂的資料餵入器
    timeframe_files = {
        "5m": f"{coin}_5m.csv",
        "15m": f"{coin}_15m.csv",
        "1h": f"{coin}_1h.csv",
        "4h": f"{coin}_4h.csv",
        "1d": f"{coin}_1d.csv"
    }
    
    feed = CSVMarketDataFeed(
        data_dir=DATA_DIR,
        timeframe_files=timeframe_files,
        micro_filename=f"{coin}_1m.csv" # 沒有的話會自動降級
    )
    
    cfg = StrategyConfig(
        initial_balance=STARTING_BALANCE,
        risk_pct=risk_pct,
        position_sizing_mode="risk_based",
        leverage=leverage,
        fixed_margin_usd=1000.0,
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
    
    strategy = get_strategy(version, coin)
    
    backtester = MultiTimeframeBacktester(
        config=cfg.to_backtest_config(),
        data_dir=DATA_DIR,
        data_feed=feed,
        strategy=strategy
    )
    
    run_cfg = replace(cfg, mode="NONE")
    
    # 執行回測，捕獲可能的異常（例如資料未下載齊全）
    try:
        trades, _ = backtester.run_strategy(run_cfg)
        stats = backtester.analyze_results(trades)
        return trades, stats, backtester.config.maker_fee
    except Exception as e:
        print(f"❌ 回測 {coin} {version} (risk={risk_pct}) 失敗: {e}")
        return None, None, None

def calculate_metrics(trades, starting_balance, maker_fee):
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "final_balance": starting_balance
        }
    
    exits = pd.DataFrame(trades)
    exits["exit_time"] = pd.to_datetime(exits["exit_time"])
    exits["equity"] = exits["entry_balance"] + exits["pnl"] - (exits["size"] * exits["entry_price"] * maker_fee)
    exits = exits.sort_values("exit_time")
    
    eq_values = [starting_balance] + list(exits["equity"].values)
    eq_series = pd.Series(eq_values)
    roll_max = eq_series.cummax()
    drawdowns = (eq_series - roll_max) / roll_max
    max_dd = drawdowns.min() * 100
    
    total_trades = len(exits)
    win_trades = (exits["pnl"] > 0).sum()
    win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    
    final_balance = exits["equity"].iloc[-1]
    total_return = ((final_balance - starting_balance) / starting_balance) * 100
    
    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(final_balance, 2)
    }

def main():
    coins = ["btc", "eth", "sol"]
    versions = ["V2", "V4"]
    risks = [0.01, 0.05]
    leverage = 20.0
    
    results = []
    
    for coin in coins:
        for version in versions:
            for risk in risks:
                print(f"🔄 正在回測 {coin.upper()} {version} (Risk: {int(risk*100)}%, Leverage: {leverage}x)...")
                trades, stats, fee = run_backtest(coin, version, risk, leverage)
                if stats is not None:
                    metrics = calculate_metrics(trades, STARTING_BALANCE, fee)
                    metrics.update({
                        "coin": coin.upper(),
                        "strategy": version,
                        "risk_pct": f"{int(risk*100)}%"
                    })
                    results.append(metrics)
                    
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        cols = ["coin", "strategy", "risk_pct", "total_trades", "win_rate", "total_return_pct", "max_drawdown_pct", "final_balance"]
        df_res = df_res[cols]
        print("\n📊 === 跨幣種回測結果彙總 ===")
        print(df_res.to_string(index=False))
        df_res.to_csv(DATA_DIR / "alt_coins_backtest_metrics.csv", index=False, encoding="utf-8-sig")
        print(f"\n💾 數據已儲存至 {DATA_DIR / 'alt_coins_backtest_metrics.csv'}")
    else:
        print("❌ 沒有生成任何有效回測數據。")

if __name__ == "__main__":
    main()
