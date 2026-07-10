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
    parser.add_argument(
        "--symbol",
        help="Legacy single-market symbol override; prefer --spot-symbol/--perp-symbol.",
    )
    parser.add_argument(
        "--market-type",
        choices=["spot", "swap"],
        help="Legacy single-market type override for spot_only/perp_only.",
    )
    parser.add_argument(
        "--market-mode",
        choices=["spot_only", "perp_only"],
        default="perp_only",
    )
    parser.add_argument("--spot-symbol", default="BTC/USDT")
    parser.add_argument("--perp-symbol", default="BTC/USDT:USDT")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument(
        "--position-sizing-mode",
        choices=["risk_based", "fixed_margin"],
        default="risk_based",
    )
    parser.add_argument("--fixed-margin-usd", type=float, default=1000.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.leverage < 1.0:
        raise ValueError("leverage must be at least 1.0")

    def local_feed(market_type: str, symbol: str) -> DuckDBMarketDataFeed:
        return DuckDBMarketDataFeed(
            database_path=args.database,
            exchange=args.exchange,
            market_type=market_type,
            symbol=symbol,
            start=args.start,
            end=args.end,
        )

    if args.market_mode == "spot_only":
        feed = local_feed(args.market_type or "spot", args.symbol or args.spot_symbol)
    else:
        feed = local_feed(args.market_type or "swap", args.symbol or args.perp_symbol)
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
        position_sizing_mode=args.position_sizing_mode,
        fixed_margin_usd=args.fixed_margin_usd,
        leverage=args.leverage,
        maker_fee=0.0002,
        taker_fee=0.0005,
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
    name = (
        f"CCXT local {args.exchange} {args.market_mode} NFE {args.htf}/{args.ltf} "
        f"{args.leverage:g}x {args.position_sizing_mode}"
    )
    backtester.generate_and_print_report(name, trades, missed)
    prefix = f"ccxt_{args.market_mode}_{args.leverage:g}x_{args.position_sizing_mode}"
    backtester.save_results_to_files(trades, missed, prefix)


if __name__ == "__main__":
    main()
