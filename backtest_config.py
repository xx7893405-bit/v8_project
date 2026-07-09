from dataclasses import asdict, dataclass


M1_COLUMNS = ["open", "high", "low"]
TIMEFRAME_FILES = {
    "15m": "btc_15m.csv",
    "1h": "btc_1h.csv",
    "4h": "btc_4h.csv",
    "1d": "btc_1d.csv",
}


@dataclass(frozen=True)
class BacktestConfig:
    initial_balance: float = 10000.0
    risk_pct: float = 0.01
    slippage_usd: float = 15.0
    entry_buffer_pct: float = 0.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    max_vol_pct: float = 0.05
    funding_rate_8h: float = 0.0001
    max_holding_bars: int = 48
    min_net_profit_r: float = 1.2
    sl_sd_mult: float = 1.2
    tp2_extension_sd_mult: float = 1.2


@dataclass(frozen=True)
class RunConfig:
    mode: str = "NONE"
    enable_be: bool = False
    tp1_close_pct: float = 0.0
    be_trigger_ratio: float = 1.5
    enable_breakout_entry: bool = True
    breakout_min_rr: float = 1.3
    entry_policy: str = "hybrid"
    use_vwap_direction_filter: bool = True
    exit_model: str = "vwap"
    atr_buffer_mult: float = 0.5
    fixed_rr: float = 1.8
    regime_trend_min: float = 1.0
    regime_vwap_expansion_min: float = 1.0
    regime_fallback: str = "structure_atr"


@dataclass(frozen=True)
class StrategyConfig:
    initial_balance: float = 10000.0
    risk_pct: float = 0.01
    slippage_usd: float = 15.0
    entry_buffer_pct: float = 0.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    max_vol_pct: float = 0.05
    funding_rate_8h: float = 0.0001
    max_holding_bars: int = 48
    min_net_profit_r: float = 1.2
    sl_sd_mult: float = 1.2
    tp2_extension_sd_mult: float = 1.2
    mode: str = "NONE"
    enable_be: bool = False
    tp1_close_pct: float = 0.0
    be_trigger_ratio: float = 1.5
    enable_breakout_entry: bool = True
    breakout_min_rr: float = 1.3
    entry_policy: str = "hybrid"
    use_vwap_direction_filter: bool = True
    exit_model: str = "vwap"
    atr_buffer_mult: float = 0.5
    fixed_rr: float = 1.8
    regime_trend_min: float = 1.0
    regime_vwap_expansion_min: float = 1.0
    regime_fallback: str = "structure_atr"

    def to_backtest_config(self) -> BacktestConfig:
        backtest_fields = BacktestConfig.__dataclass_fields__.keys()
        data = asdict(self)
        return BacktestConfig(**{key: data[key] for key in backtest_fields})

    def to_run_config(self) -> RunConfig:
        run_fields = RunConfig.__dataclass_fields__.keys()
        data = asdict(self)
        return RunConfig(**{key: data[key] for key in run_fields})
