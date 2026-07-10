import os

from backtest_config import BacktestConfig, RunConfig, StrategyConfig
from coinmarketcap_market_data import CoinMarketCapMarketDataFeed
from hybrid_market_data import HybridMarketDataFeed
from market_data import CSVMarketDataFeed, MarketDataFeed
from nfe_strategy import NFEDoubleLevelStrategy
from strategy_base import BacktestStrategy, StrategyDecision
from v8_strategy import V8FvgOverlapStrategy
from strategy_engine import BacktestSessionResult, MultiTimeframeBacktester

__all__ = [
    "BacktestConfig",
    "RunConfig",
    "StrategyConfig",
    "MarketDataFeed",
    "CSVMarketDataFeed",
    "CoinMarketCapMarketDataFeed",
    "HybridMarketDataFeed",
    "BacktestStrategy",
    "StrategyDecision",
    "NFEDoubleLevelStrategy",
    "V8FvgOverlapStrategy",
    "BacktestSessionResult",
    "MultiTimeframeBacktester",
    "build_default_backtester",
    "build_default_strategy",
    "build_default_nfe_strategy",
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
        limit_order_slippage_usd=5.0,
        stop_loss_slippage_usd=10.0,
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


def build_default_nfe_strategy() -> StrategyConfig:
    return StrategyConfig(
        initial_balance=10000.0,
        risk_pct=5,
        # NFE 預設改回 risk_based；fixed_margin 僅保留給對照實驗手動切換。
        position_sizing_mode="risk_based",
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
        mode="NONE",
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
        enable_breakout_entry=True,
        entry_policy="hybrid",
    )


def _run_folder_backtests(folder_name: str) -> None:
    print("\n" + "=" * 95)
    print(f"🚀 開始執行資料夾 【{folder_name}】 V8 + NFE 雙策略回測...")
    print("=" * 95)

    original_cwd = os.getcwd()
    if not os.path.exists(folder_name):
        print(f"❌ 錯誤：找不到資料夾 {folder_name}，請檢查路徑。")
        return

    os.chdir(folder_name)
    try:
        v8_backtester = build_default_backtester()
        v8_strategy = build_default_strategy()
        trades_a, missed_a = v8_backtester.run_strategy(v8_strategy)
        v8_backtester.generate_and_print_report(
            f"{folder_name} - 15m+1H+4H 右側突破獨立版 v9.9",
            trades_a,
            missed_a,
        )
        v8_backtester.save_results_to_files(
            trades_a,
            missed_a,
            f"v8_backtest_report_4H_breakout_only_{folder_name}",
        )

        print("\n" + "-" * 95)
        print(f"🚀 開始執行資料夾 【{folder_name}】 NFE 雙級別交易戰法回測...")
        print("-" * 95)

        nfe_strategy = NFEDoubleLevelStrategy(
            htf="1h",
            htf_n=5,
            ltf_n=3,
            ob_range_type="full",
            min_rr=3.0,
            sl_padding=20.0,
        )
        nfe_cfg = build_default_nfe_strategy()
        nfe_backtester = MultiTimeframeBacktester(
            config=nfe_cfg.to_backtest_config(),
            strategy=nfe_strategy,
        )
        trades_b, missed_b = nfe_backtester.run_strategy(nfe_cfg)
        nfe_backtester.generate_and_print_report(
            f"{folder_name} - NFE 1H/15m 雙級別戰法",
            trades_b,
            missed_b,
        )
        nfe_backtester.save_results_to_files(
            trades_b,
            missed_b,
            f"nfe_backtest_report_{folder_name}",
        )
    finally:
        os.chdir(original_cwd)


def main() -> None:
    try:
        folders = ["202407-2507", "202507-2607"]
        for folder_name in folders:
            _run_folder_backtests(folder_name)
    except FileNotFoundError as e:
        print(f"❌ 錯誤: {e}")


if __name__ == "__main__":
    main()
