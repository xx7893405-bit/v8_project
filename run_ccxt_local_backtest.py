from __future__ import annotations

import argparse

from backtest_config import StrategyConfig
from ccxt_market_data import DuckDBMarketDataFeed
from nfe_strategy import NFEDoubleLevelStrategy
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NFE against locally synchronized CCXT candles.")
    parser.add_argument("--database", default="data/market_data.duckdb")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--market-type", default="swap")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feed = DuckDBMarketDataFeed(
        database_path=args.database,
        exchange=args.exchange,
        market_type=args.market_type,
        symbol=args.symbol,
        start=args.start,
        end=args.end,
    )
    strategy = NFEDoubleLevelStrategy(
        htf=args.htf,
        ltf=args.ltf,
        htf_n=5,
        ltf_n=3,
        ob_range_type="full",
        min_rr=3.0,
        sl_padding=20.0,
    )
    config = StrategyConfig(
        initial_balance=10000.0,
        risk_pct=0.01,
        position_sizing_mode="risk_based",
        maker_fee=0.0001,
        taker_fee=0.00025,
        max_holding_bars=96,
        min_net_profit_r=3.0,
        mode="NONE",
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
    )
    backtester = MultiTimeframeBacktester(
        config=config.to_backtest_config(),
        data_feed=feed,
        strategy=strategy,
    )
    trades, missed = backtester.run_strategy(config)
    name = f"CCXT local {args.exchange} {args.symbol} NFE {args.htf}/{args.ltf}"
    backtester.generate_and_print_report(name, trades, missed)
    backtester.save_results_to_files(trades, missed, "ccxt_local_nfe_backtest")


if __name__ == "__main__":
    main()
