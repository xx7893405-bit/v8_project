import os
import sys
import pandas as pd
from dataclasses import replace

# 確保引入當前目錄下的回測引擎與兩代策略
sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from nfe_strategy import NFEDoubleLevelStrategy
from nfe_v2_strategy import NFEV2Strategy


def run_segmented_test(folder_name, start_date, end_date, use_v2, label):
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
        
        if use_v2:
            strategy = NFEV2Strategy(
                htf="1h",
                htf_n=5,
                ltf_n=3,
                ob_range_type="full",
                min_rr=3.0,
                sl_padding=20.0,
                use_dynamic_sl=True,
                sl_padding_atr_mult=0.5,
                use_trailing_stop=True
            )
        else:
            strategy = NFEDoubleLevelStrategy(
                htf="1h",
                htf_n=5,
                ltf_n=3,
                ob_range_type="full",
                min_rr=3.0,
                sl_padding=20.0
            )
        
        backtester = MultiTimeframeBacktester(
            config=base_strategy_cfg.to_backtest_config(),
            data_dir=".",
            strategy=strategy
        )
        
        # 【分段測試核心】：在計算指標前，對原始歷史 K 線數據進行時間過濾
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        
        # 由於有些 Swing 需要回看歷史，我們讓大時區 DataFrame 保留前置 10 天的資料以進行預熱，但 15m (回測主時間軸) 嚴格過濾
        backtester.df_15m = backtester.df_15m.loc[start_ts:end_ts]
        if not backtester.df_5m.empty:
            backtester.df_5m = backtester.df_5m.loc[start_ts:end_ts]
            
        backtester.df_1h = backtester.df_1h.loc[start_ts - pd.Timedelta(days=10):end_ts]
        backtester.df_4h = backtester.df_4h.loc[start_ts - pd.Timedelta(days=15):end_ts]
        backtester.df_1d = backtester.df_1d.loc[start_ts - pd.Timedelta(days=30):end_ts]

        if len(backtester.df_15m) < 100:
            return None

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
    segments = [
        ("2024-07-01", "2024-12-31", "【區塊一】2024下半年 (牛市初期與高波動震盪)"),
        ("2025-01-01", "2025-06-30", "【區塊二】2025上半年 (強烈單邊牛市主升浪)"),
        ("2025-07-01", "2025-12-31", "【區塊三】2025下半年 (高位劇烈洗盤與中期熊回調)"),
        ("2026-01-01", "2026-06-30", "【區塊四】2026上半年 (牛尾牛熊交替期)"),
    ]
    
    folder = "202407-2607_continuous"
    
    print("\n" + "="*100)
    print(f"📊 開始執行 2024-2026 連續數據之 【區間分段測試 (Walk-Forward Segmented Test)】")
    print("="*100)
    
    for start, end, name in segments:
        print(f"\n⏳ 正在分析：{name} ({start} ~ {end})...")
        v1_res = run_segmented_test(folder, start, end, use_v2=False, label="V1 (對照組)")
        v2_res = run_segmented_test(folder, start, end, use_v2=True, label="V2 (優化組)")
        
        print(f"\n📊 {name} 對照總結：")
        print("-" * 100)
        for r in [v1_res, v2_res]:
            if r is None:
                continue
            print(f"{r['label']:<15} | 總損益: {r['profit']:>+6.2f}% (筆數: {r['total_trades']:>2}) | 多單: {r['long_profit']:>+6.2f}% | 空單: {r['short_profit']:>+6.2f}%")
        print("=" * 100)
