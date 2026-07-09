from __future__ import annotations

import argparse

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from execution_engine import DryRunExecutionClient, LiveExecutionEngine
from multi_timeframe_backtest import build_default_strategy
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare live-trading actions from the latest strategy snapshot.")
    parser.add_argument("--exchange", choices=["binance", "okx"], default="binance")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--okx-symbol", default="BTC-USDT")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--micro-lookback-days", type=int, default=45)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    strategy = build_default_strategy()
    try:
        feed = ExchangeApiMarketDataFeed(
            ApiFeedConfig(
                exchange=args.exchange,
                symbol=args.symbol,
                okx_symbol=args.okx_symbol,
                lookback_days=args.lookback_days,
                micro_lookback_days=args.micro_lookback_days,
            )
        )
        backtester = MultiTimeframeBacktester(config=strategy.to_backtest_config(), data_feed=feed)
        snapshot = backtester.build_runtime_snapshot(strategy)
    except Exception as exc:
        print(f"live trading prep failed: {exc}")
        return

    active_position = snapshot["active_position"]
    if active_position is None:
        print("No active simulated position to mirror into live execution.")
        return

    engine = LiveExecutionEngine(DryRunExecutionClient())
    entry_result = engine.submit_entry_from_position(active_position)
    exit_results = engine.submit_exit_orders(active_position)

    print(f"entry: {entry_result.status} {entry_result.message}")
    for result in exit_results:
        print(f"exit: {result.status} {result.message}")


if __name__ == "__main__":
    main()
