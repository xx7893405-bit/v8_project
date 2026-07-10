import os
import sys
from dataclasses import replace

# 確保能引入當前目錄下的策略與回測引擎
sys.path.append(os.getcwd())
from multi_timeframe_backtest import MultiTimeframeBacktester, StrategyConfig
from nfe_strategy import NFEDoubleLevelStrategy

DEFAULT_NFE_POSITION_SIZING_MODE = "risk_based"
DEFAULT_NFE_FIXED_MARGIN_USD = 1000.0


def run_nfe_folder_backtest(folder_name):
    print("\n" + "="*95)
    print(f"🚀 開始執行資料夾 【{folder_name}】 NFE 雙級別交易戰法回測...")
    print("="*95)
    
    original_cwd = os.getcwd()
    if not os.path.exists(folder_name):
        print(f"❌ 錯誤：找不到資料夾 {folder_name}，請檢查路徑。")
        return
    
    os.chdir(folder_name)
    
    try:
        # NFE 預設改回採用 risk_based。
        # fixed_margin 保留作手動對照模式，不作日常預設。
        position_sizing_mode = DEFAULT_NFE_POSITION_SIZING_MODE
        fixed_margin_usd = DEFAULT_NFE_FIXED_MARGIN_USD

        # NFE 基礎配置
        base_strategy_cfg = StrategyConfig(
            initial_balance=10000.0,
            risk_pct=0.01,
            position_sizing_mode=position_sizing_mode,
            fixed_margin_usd=fixed_margin_usd,
            slippage_usd=15.0,
            limit_order_slippage_usd=5.0,
            stop_loss_slippage_usd=10.0,
            maker_fee=0.0002,
            taker_fee=0.0005,
            max_vol_pct=0.05,
            funding_rate_8h=0.0001,
            max_holding_bars=96,  # 給予足夠的持有時間以實現波段
            min_net_profit_r=3.0, # 由 5R 下修至 3R，以貼近影片中的實際出手密度
            enable_be=True,
            tp1_close_pct=0.5,    # TP1 平倉 50%
            be_trigger_ratio=1.5,
        )
        
        # 實例化 NFEDoubleLevelStrategy
        nfe_strategy = NFEDoubleLevelStrategy(
            htf="1h",             # 大級別 1H
            htf_n=5,              # 大級別 Swing 視窗
            ltf_n=3,              # 小級別 Swing 視窗
            ob_range_type="full", # 完整 OB 區間
            min_rr=3.0,           # 最低 3R
            sl_padding=20.0,      # 停損緩衝
        )
        
        backtester = MultiTimeframeBacktester(
            config=base_strategy_cfg.to_backtest_config(),
            data_dir=".",
            strategy=nfe_strategy
        )

        # 執行 NFE 策略
        # 由於策略內建大時區對齊，mode 設為 NONE 即可 (不使用舊的 FVG Overlap 過濾)
        run_cfg = replace(base_strategy_cfg, mode="NONE")
        
        print("\n👉 正在運行：NFE 雙級別 (1H/15m) 共振戰法 (3.0R 起步)...")
        trades, missed = backtester.run_strategy(run_cfg)
        backtester.generate_and_print_report(f"{folder_name} - NFE 1H/15m 雙級別戰法", trades, missed)
        backtester.save_results_to_files(trades, missed, f"nfe_backtest_report_{folder_name}")
        
    except Exception as e:
        import traceback
        print(f"❌ 在處理 {folder_name} 時發生非預期錯誤: {e}")
        traceback.print_exc()
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    folders = sys.argv[1:] or ["202407-2507", "202507-2607"]
    
    for folder in folders:
        run_nfe_folder_backtest(folder)
        
    print("\n" + "═"*95)
    print("✨ NFE 雙級別交易戰法跨越兩年大數據回測任務執行完畢！")
    print("═"*95)
