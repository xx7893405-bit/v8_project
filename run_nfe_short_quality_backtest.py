from run_nfe_backtest import run_nfe_folder_backtest


if __name__ == "__main__":
    run_nfe_folder_backtest(
        "202407-2607_continuous",
        max_short_rr=6.0,
        max_short_stop_atr=1.5,
        report_prefix="nfe_short_quality_report",
    )
