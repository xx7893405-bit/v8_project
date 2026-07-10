from __future__ import annotations

from coinmarketcap_market_data import CoinMarketCapMarketDataFeed
from hybrid_market_data import HybridMarketDataFeed
from market_data import CSVMarketDataFeed
from multi_timeframe_backtest import build_default_strategy
from strategy_engine import MultiTimeframeBacktester


def main() -> None:
    strategy = build_default_strategy()
    csv_feed = CSVMarketDataFeed()
    cmc_feed = CoinMarketCapMarketDataFeed()
    feed = HybridMarketDataFeed(
        primary_feed=csv_feed,
        secondary_feed=cmc_feed,
        prefer_primary=True,
        audit=True,
    )
    backtester = MultiTimeframeBacktester(
        config=strategy.to_backtest_config(),
        data_feed=feed,
    )

    trades, missed = backtester.run_strategy(strategy)
    backtester.generate_and_print_report("Hybrid CSV+CoinMarketCap BTC breakout_only", trades, missed)
    backtester.save_results_to_files(trades, missed, "hybrid_btc_backtest_report")

    if feed.audit_log:
        print("Hybrid Feed Audit:")
        for record in feed.audit_log:
            print(
                f" - {record.timeframe}: primary_rows={record.primary_rows}, secondary_rows={record.secondary_rows}, "
                f"overlap={record.overlapping_rows}, close_mae={record.close_mae}"
            )
    else:
        print("Hybrid Feed Audit: no secondary CoinMarketCap data was available in this thread.")


if __name__ == "__main__":
    main()
