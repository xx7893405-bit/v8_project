from __future__ import annotations

import argparse

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from backtest_config import StrategyConfig
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V8 backtest with live exchange candles.")
    parser.add_argument("--exchange", choices=["binance", "okx"], default="binance")
    parser.add_argument("--symbol", default="BTCUSDT", help="Binance symbol, e.g. BTCUSDT")
    parser.add_argument("--okx-symbol", default="BTC-USDT-SWAP", help="OKX perpetual-swap instrument id")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--micro-lookback-days", type=int, default=45)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feed = ExchangeApiMarketDataFeed(
        ApiFeedConfig(
            exchange=args.exchange,
            symbol=args.symbol,
            okx_symbol=args.okx_symbol,
            lookback_days=args.lookback_days,
            micro_lookback_days=args.micro_lookback_days,
        )
    )
    strategy = StrategyConfig(
        initial_balance=10000.0,
        risk_pct=0.01,
        slippage_usd=15.0,
        entry_buffer_pct=0.50,
        maker_fee=0.0002,
        taker_fee=0.0005,
        max_vol_pct=0.05,
        funding_rate_8h=0.0001,
        max_holding_bars=96,
        min_net_profit_r=2.2,
        sl_sd_mult=1.4,
        tp2_extension_sd_mult=1.6,
        mode="4H",
        enable_be=False,
        tp1_close_pct=0.0,
        be_trigger_ratio=2.5,
        enable_breakout_entry=True,
        breakout_min_rr=1.3,
        entry_policy="breakout_only",
    )
    backtester = MultiTimeframeBacktester(
        config=strategy.to_backtest_config(),
        data_feed=feed,
    )

    trades, missed = backtester.run_strategy(strategy)
    strategy_name = f"API {args.exchange.upper()} 15m+1m breakout_only"
    backtester.generate_and_print_report(strategy_name, trades, missed)
    prefix = f"api_{args.exchange}_backtest_report"
    backtester.save_results_to_files(trades, missed, prefix)


if __name__ == "__main__":
    main()
