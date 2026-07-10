from __future__ import annotations

from coinmarketcap_market_data import CoinMarketCapMarketDataFeed
from multi_timeframe_backtest import build_default_strategy
from strategy_engine import MultiTimeframeBacktester


def main() -> None:
    strategy = build_default_strategy()
    feed = CoinMarketCapMarketDataFeed()
    try:
        backtester = MultiTimeframeBacktester(
            config=strategy.to_backtest_config(),
            data_feed=feed,
        )
        trades, missed = backtester.run_strategy(strategy)
    except RuntimeError as exc:
        print(f"❌ CoinMarketCap backtest unavailable: {exc}")
        return

    backtester.generate_and_print_report("CoinMarketCap BTC breakout_only", trades, missed)
    backtester.save_results_to_files(trades, missed, "cmc_btc_backtest_report")


if __name__ == "__main__":
    main()
