from __future__ import annotations

import argparse
import os

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from execution_engine import CcxtExecutionClient, DryRunExecutionClient, LiveExecutionEngine
from multi_timeframe_backtest import build_default_strategy
from oracle_strategy_job import build_strategy
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare live-trading actions from the latest strategy snapshot.")
    parser.add_argument("--exchange", choices=["binance", "okx"], default="binance")
    parser.add_argument("--symbol", default="BTCUSDT", help="Raw public API symbol for Binance")
    parser.add_argument("--ccxt-symbol", default="BTC/USDT:USDT", help="Unified perpetual symbol used for orders")
    parser.add_argument("--okx-symbol", default="BTC-USDT")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--micro-lookback-days", type=int, default=45)
    parser.add_argument("--strategy", choices=["nfe", "nfe-v2", "nfe-v4", "v8"], default="nfe-v2")
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    parser.add_argument("--risk-pct", type=float, default=0.01)
    parser.add_argument("--max-risk-pct", type=float, default=0.02)
    parser.add_argument("--max-leverage", type=float, default=3.0)
    parser.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--live", dest="dry_run", action="store_false")
    parser.add_argument("--sandbox", dest="sandbox", action="store_true", default=True)
    parser.add_argument("--no-sandbox", dest="sandbox", action="store_false")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 < args.risk_pct <= args.max_risk_pct <= 1:
        raise ValueError("risk-pct must be > 0, <= max-risk-pct, and max-risk-pct <= 1")
    if not 1 <= args.max_leverage <= 100:
        raise ValueError("max-leverage must be between 1 and 100")
    strategy = build_default_strategy()
    strategy = strategy.__class__(**{**strategy.__dict__, "risk_pct": args.risk_pct, "leverage": args.max_leverage})
    strategy_impl = build_strategy(args.strategy, args.htf, args.ltf)
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
        backtester = MultiTimeframeBacktester(
            config=strategy.to_backtest_config(), data_feed=feed, strategy=strategy_impl
        )
        snapshot = backtester.build_runtime_snapshot(strategy)
    except Exception as exc:
        print(f"live trading prep failed: {exc}")
        return

    active_position = snapshot["active_position"]
    if active_position is None:
        print("No active simulated position to mirror into live execution.")
        return

    if args.dry_run:
        client = DryRunExecutionClient()
    else:
        if os.getenv("ALLOW_LIVE_TRADING") != "YES":
            raise RuntimeError("Set ALLOW_LIVE_TRADING=YES explicitly before using --live")
        client = CcxtExecutionClient.from_environment(
            args.exchange, args.ccxt_symbol, sandbox=args.sandbox, margin_mode=args.margin_mode
        )
    engine = LiveExecutionEngine(client)
    entry_result = engine.submit_entry_from_position(active_position)
    exit_results = engine.submit_exit_orders(active_position)

    print(f"entry: {entry_result.status} {entry_result.message}")
    for result in exit_results:
        print(f"exit: {result.status} {result.message}")


if __name__ == "__main__":
    main()
