import os
import sys
from dataclasses import replace

# 確保引入當前目錄下的回測引擎與四代策略
sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from nfe_strategy import NFEDoubleLevelStrategy
from nfe_v2_strategy import NFEV2Strategy
from nfe_v3_strategy import NFEV3Strategy
from nfe_v4_strategy import NFEV4Strategy


def run_single_test(folder_name, version, label):
    original_cwd = os.getcwd()
    if not os.path.exists(folder_name):
        print(f"❌ 找不到資料夾 {folder_name}")
        return None
    os.chdir(folder_name)
    
    try:
        base_strategy_cfg = StrategyConfig(
            initial_balance=10000.0,
            risk_pct=0.01,
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
            enable_be=True,
            tp1_close_pct=0.5,
            be_trigger_ratio=1.5,
        )
        
        # 實例化不同版本的策略
        if version == "V1":
            strategy = NFEDoubleLevelStrategy(
                htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0
            )
        elif version == "V2":
            strategy = NFEV2Strategy(
                htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0,
                use_dynamic_sl=True, sl_padding_atr_mult=0.5, use_trailing_stop=True
            )
        elif version == "V3":
            strategy = NFEV3Strategy(
                htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0,
                use_dynamic_sl_short=True, sl_padding_atr_mult_short=0.5, use_trailing_stop_short=True
            )
        elif version == "V4":
            strategy = NFEV4Strategy(
                htf="1h", htf_n=5, ltf_n=3, ob_range_type="full", min_rr=3.0, sl_padding=20.0,
                defensive_atr_mult=0.6
            )
        else:
            raise ValueError(f"未知版本: {version}")
        
        backtester = MultiTimeframeBacktester(
            config=base_strategy_cfg.to_backtest_config(),
            data_dir=".",
            strategy=strategy
        )

        run_cfg = replace(base_strategy_cfg, mode="NONE")
        trades, missed = backtester.run_strategy(run_cfg)
        
        stats = backtester.analyze_results(trades)
        profit_pct = stats["profit_pct"]
        
        long_trades = [t for t in trades if t["type"] == "LONG"]
        short_trades = [t for t in trades if t["type"] == "SHORT"]
        
        long_stats = backtester.analyze_results(long_trades)
        short_stats = backtester.analyze_results(short_trades)
        
        return {
            "label": label,
            "total_trades": stats['trades'],
            "win_rate": stats['win_rate'],
            "profit": profit_pct,
            "long_trades": long_stats['trades'],
            "long_win_rate": long_stats['win_rate'],
            "long_profit": long_stats['profit_pct'],
            "short_trades": short_stats['trades'],
            "short_win_rate": short_stats['win_rate'],
            "short_profit": short_stats['profit_pct']
        }
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    folder_name = "202101-202607_merged"
    
    print("\n" + "="*100)
    print(f"🚀 正在針對 5.5年超長一體化數據 【{folder_name}】 執行 V1 vs V2 vs V3 vs V4 綜合對照回測...")
    print("="*100)
    
    results = []
    results.append(run_single_test(folder_name, "V1", "V1 (基準對照組)"))
    results.append(run_single_test(folder_name, "V2", "V2 (全防守優化組)"))
    results.append(run_single_test(folder_name, "V3", "V3 (多空非對稱組)"))
    results.append(run_single_test(folder_name, "V4", "V4 (自適應優化組)"))
    
    print(f"\n🏆 【{folder_name}】 2021-2026 五年半一體化策略最終對照表")
    print("-" * 100)
    for r in results:
        if r is None:
            continue
        print(f"{r['label']:<20} | 總損益: {r['profit']:>+6.2f}% (勝率: {r['win_rate']:>5.2f}%, 筆數: {r['total_trades']:>2}) | 多單: {r['long_profit']:>+6.2f}% (勝率: {r['long_win_rate']:>5.2f}%) | 空單: {r['short_profit']:>+6.2f}% (勝率: {r['short_win_rate']:>5.2f}%)")
    print("="*100)
