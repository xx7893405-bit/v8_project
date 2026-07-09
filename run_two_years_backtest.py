import os
import sys
from dataclasses import replace

# 確保能正確引入當前目錄下的 multi_timeframe_backtest
sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig

def run_folder_backtest(folder_name):
    print("\n" + "="*95)
    print(f"🚀 開始執行資料夾 【{folder_name}】 V8 核心抗回撤防禦策略回測...")
    print("="*95)
    
    original_cwd = os.getcwd()
    if not os.path.exists(folder_name):
        print(f"❌ 錯誤：找不到資料夾 {folder_name}，請檢查路徑。")
        return
    
    os.chdir(folder_name)
    
    try:
        base_strategy = StrategyConfig(
            initial_balance=10000.0,
            risk_pct=0.01,
            slippage_usd=15.0,
            maker_fee=0.0001,
            taker_fee=0.00025,
            max_vol_pct=0.05,
            funding_rate_8h=0.0001,
            max_holding_bars=48,
            min_net_profit_r=1.3,
            enable_be=True,
            tp1_close_pct=0.0,
            be_trigger_ratio=1.5,
        )
        backtester = MultiTimeframeBacktester(
            config=base_strategy.to_backtest_config(),
            data_dir=".",
        )

        base_mode_strategy = replace(base_strategy, mode="NONE")
        resonance_strategy = replace(base_strategy, mode="4H")
        
        # 1. 執行 15m+1H 基礎版 (開啟 1.5R 護航)
        print("\n👉 正在運行：15m+1H 基礎版 (台階保本 + 利潤奔跑)...")
        trades_a, missed_a = backtester.run_strategy(base_mode_strategy)
        backtester.generate_and_print_report(f"{folder_name} - 15m+1H 基礎防禦版", trades_a, missed_a)
        
        # 2. 執行 15m+1H+4H 三重共振版 (開啟 1.5R 護航) -> 🔧 BUG FIXED 同步啟用真正的 4H 共振
        print("\n👉 正在運行：15m+1H+4H 三重共振版 (大時區過濾開啟)...")
        trades_b, missed_b = backtester.run_strategy(resonance_strategy)
        backtester.generate_and_print_report(f"{folder_name} - 15m+1H+4H 三重共振防禦版", trades_b, missed_b)
        
    except Exception as e:
        print(f"❌ 在處理 {folder_name} 時發生非預期錯誤: {e}")
    finally:
        os.chdir(original_cwd)

if __name__ == "__main__":
    # 定義歷史資料夾名稱
    folders = ["202407-2507", "202507-2607"]
    
    for folder in folders:
        run_folder_backtest(folder)
        
    print("\n" + "═"*95)
    print("✨ 全知之眼跨越 24-26 兩年大數據【防禦基因改造】任務執行完畢！請檢視上方最終戰報。")
    print("═"*95)
