from backtest_config import BacktestConfig, RunConfig, StrategyConfig
from coinmarketcap_market_data import CoinMarketCapMarketDataFeed
from hybrid_market_data import HybridMarketDataFeed
from market_data import CSVMarketDataFeed, MarketDataFeed
from strategy_engine import BacktestSessionResult, MultiTimeframeBacktester

__all__ = [
    "BacktestConfig",
    "RunConfig",
    "StrategyConfig",
    "MarketDataFeed",
    "CSVMarketDataFeed",
    "CoinMarketCapMarketDataFeed",
    "HybridMarketDataFeed",
    "BacktestSessionResult",
    "MultiTimeframeBacktester",
    "build_default_backtester",
    "build_default_strategy",
    "main",
]


def build_default_backtester() -> MultiTimeframeBacktester:
    return MultiTimeframeBacktester(config=build_default_strategy().to_backtest_config())


def build_default_strategy() -> StrategyConfig:
    return StrategyConfig(
        # Core risk / cost assumptions
        initial_balance=10000.0,
        risk_pct=0.01,
        slippage_usd=15.0,
        maker_fee=0.0002,
        taker_fee=0.0005,
        max_vol_pct=0.05,
        funding_rate_8h=0.0001,

        # Active breakout-only strategy inputs
        max_holding_bars=96,
        sl_sd_mult=1.4,
        mode="4H",
        enable_breakout_entry=True,
        breakout_min_rr=1.3,
        entry_policy="breakout_only",
    )


def main() -> None:
    try:
        backtester = build_default_backtester()
        strategy = build_default_strategy()
        trades_a, missed_a = backtester.run_strategy(strategy)
        backtester.generate_and_print_report("15m+1H+4H 右側突破獨立版 v9.9", trades_a, missed_a)
        backtester.save_results_to_files(trades_a, missed_a, "v8_backtest_report_4H_breakout_only")
    except FileNotFoundError as e:
        print(f"❌ 錯誤: {e}")


if __name__ == "__main__":
    main()
