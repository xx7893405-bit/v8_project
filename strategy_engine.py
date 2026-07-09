from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backtest_config import BacktestConfig, M1_COLUMNS, RunConfig, StrategyConfig
from market_data import CSVMarketDataFeed, MarketDataFeed


@dataclass
class BacktestSessionResult:
    trades: List[dict]
    missed_trades: List[dict]
    balance: float
    active_position: Optional[dict]
    pending_retest_order: Optional[dict]
    pending_breakout_order: Optional[dict]


class V8OmniscientEye:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.calculate_v8_indicators()

    def calculate_v8_indicators(self) -> None:
        df_dt = self.df.copy()
        df_dt["date"] = df_dt.index.date
        df_dt["pv"] = df_dt["close"] * df_dt["volume"]

        cum_pv = df_dt.groupby("date")["pv"].cumsum()
        cum_v = df_dt.groupby("date")["volume"].cumsum()
        self.df["VWAP"] = cum_pv / cum_v

        df_dt["bar_idx"] = df_dt.groupby("date").cumcount()
        vwap_deviation = self.df["close"] - self.df["VWAP"]
        rolling_std = vwap_deviation.rolling(96, min_periods=1).std()
        rolling_std = np.where(df_dt["bar_idx"] < 16, np.nan, rolling_std)

        self.df["VWAP_SD"] = rolling_std
        self.df["VWAP_1.0_SD_Upper"] = self.df["VWAP"] + rolling_std
        self.df["VWAP_1.0_SD_Lower"] = self.df["VWAP"] - rolling_std
        self.df["VWAP_2.0_SD_Upper"] = self.df["VWAP"] + (rolling_std * 2.0)
        self.df["VWAP_2.0_SD_Lower"] = self.df["VWAP"] - (rolling_std * 2.0)
        self.df["VWAP_SD_MA"] = self.df["VWAP_SD"].rolling(32, min_periods=1).mean()
        self.df["VWAP_SD_EXPANSION"] = self.df["VWAP_SD"] / self.df["VWAP_SD_MA"]

        prev_close = self.df["close"].shift(1)
        true_range = pd.concat(
            [
                self.df["high"] - self.df["low"],
                (self.df["high"] - prev_close).abs(),
                (self.df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        self.df["ATR_14"] = true_range.rolling(14, min_periods=1).mean()

        self.df["MA5"] = self.df["close"].rolling(5).mean()
        self.df["MA10"] = self.df["close"].rolling(10).mean()
        self.df["MA20"] = self.df["close"].rolling(20).mean()
        self.df["MA20_Ref"] = self.df["close"].shift(20)
        self.df["local_bias"] = np.where(
            (self.df["close"] > self.df["MA20"]) & (self.df["close"] > self.df["MA20_Ref"]),
            "LONG",
            np.where(
                (self.df["close"] < self.df["MA20"]) & (self.df["close"] < self.df["MA20_Ref"]),
                "SHORT",
                "NONE",
            ),
        )


def calculate_realtime_fvg(df: pd.DataFrame, max_lifecycle_bars: int = 192) -> pd.DataFrame:
    df = df.copy()
    fvg_type = [None] * len(df)
    fvg_top = [np.nan] * len(df)
    fvg_bottom = [np.nan] * len(df)

    active_bullish_fvgs = []
    active_bearish_fvgs = []

    for i in range(2, len(df)):
        p_prev = df.iloc[i - 2]
        p_next = df.iloc[i]

        if p_next["low"] > p_prev["high"]:
            active_bullish_fvgs.append({"top": p_next["low"], "bottom": p_prev["high"], "created_at": i})
        elif p_next["high"] < p_prev["low"]:
            active_bearish_fvgs.append({"top": p_prev["low"], "bottom": p_next["high"], "created_at": i})

        current_low = p_next["low"]
        current_high = p_next["high"]

        active_bullish_fvgs = [
            f for f in active_bullish_fvgs if current_low >= f["bottom"] and (i - f["created_at"]) <= max_lifecycle_bars
        ]
        active_bearish_fvgs = [
            f for f in active_bearish_fvgs if current_high <= f["top"] and (i - f["created_at"]) <= max_lifecycle_bars
        ]

        if active_bullish_fvgs:
            latest = active_bullish_fvgs[-1]
            fvg_type[i] = "BULLISH"
            fvg_top[i] = latest["top"]
            fvg_bottom[i] = latest["bottom"]
        elif active_bearish_fvgs:
            latest = active_bearish_fvgs[-1]
            fvg_type[i] = "BEARISH"
            fvg_top[i] = latest["top"]
            fvg_bottom[i] = latest["bottom"]

    df["fvg_type"] = fvg_type
    df["fvg_top"] = fvg_top
    df["fvg_bottom"] = fvg_bottom
    return df[["fvg_type", "fvg_top", "fvg_bottom"]]


class MultiTimeframeBacktester:
    def __init__(self, config: Optional[BacktestConfig] = None, data_feed: Optional[MarketDataFeed] = None, data_dir: str = "."):
        self.config = config or BacktestConfig()
        self.data_feed = data_feed or CSVMarketDataFeed(data_dir=data_dir)
        self.load_all_data()

    @property
    def initial_balance(self) -> float:
        return self.config.initial_balance

    def run_strategy(self, strategy: StrategyConfig) -> Tuple[List[dict], List[dict]]:
        self.config = strategy.to_backtest_config()
        return self.run_backtest(**strategy.to_run_config().__dict__)

    @staticmethod
    def _inject_bias(df: pd.DataFrame) -> pd.DataFrame:
        df["MA20"] = df["close"].rolling(20).mean()
        df["MA20_Ref"] = df["close"].shift(20)
        prev_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        df["ATR_14"] = true_range.rolling(14, min_periods=1).mean()
        df["trend_strength"] = (df["close"] - df["MA20"]).abs() / df["ATR_14"]
        df["bias"] = np.where(
            (df["close"] > df["MA20"]) & (df["close"] > df["MA20_Ref"]),
            "LONG",
            np.where(
                (df["close"] < df["MA20"]) & (df["close"] < df["MA20_Ref"]),
                "SHORT",
                "NONE",
            ),
        )
        return df

    def _load_primary_timeframes(self) -> None:
        self.df_15m = self.data_feed.load_timeframe("15m")
        self.df_1h = self.data_feed.load_timeframe("1h")
        self.df_4h = self.data_feed.load_timeframe("4h")
        self.df_1d = self.data_feed.load_timeframe("1d")

    def _load_micro_feed(self) -> None:
        try:
            empty = self.data_feed.load_micro_window(
                pd.Timestamp("1970-01-01 00:00:00"),
                pd.Timestamp("1970-01-01 00:00:00"),
                M1_COLUMNS,
            )
            self.has_micro_data = list(empty.columns) == M1_COLUMNS
        except FileNotFoundError:
            self.has_micro_data = False
            print("⚠️ 未檢測到 btc_1m.csv，系統將自動降級至保守高壓實盤模式。")

    def _build_indicator_matrix(self) -> pd.DataFrame:
        print("正在計算機構失衡區 (FVG)...")
        df_1h_fvg = calculate_realtime_fvg(self.df_1h, max_lifecycle_bars=48)
        df_15m_fvg = calculate_realtime_fvg(self.df_15m, max_lifecycle_bars=192)

        print("正在建構 15m 全知指標矩陣...")
        v8_15m = V8OmniscientEye(self.df_15m)
        df_res = v8_15m.df

        df_res["m15_fvg_type"] = df_15m_fvg["fvg_type"].shift(1)
        df_res["m15_fvg_top"] = df_15m_fvg["fvg_top"].shift(1)
        df_res["m15_fvg_bottom"] = df_15m_fvg["fvg_bottom"].shift(1)

        df_1d_aligned = self.df_1d[["bias"]].copy()
        df_1d_aligned.index = df_1d_aligned.index + pd.Timedelta(days=1)
        df_4h_aligned = self.df_4h[["bias", "trend_strength"]].copy()
        df_4h_aligned.index = df_4h_aligned.index + pd.Timedelta(hours=4)
        df_1h_fvg_aligned = df_1h_fvg.copy()
        df_1h_fvg_aligned.index = df_1h_fvg_aligned.index + pd.Timedelta(hours=1)

        print("正在執行多時區時間軸【嚴格實盤收盤對齊】...")
        df_res["bias_1d"] = df_1d_aligned["bias"].reindex(df_res.index, method="ffill")
        df_res["bias_4h"] = df_4h_aligned["bias"].reindex(df_res.index, method="ffill")
        df_res["trend_strength_4h"] = df_4h_aligned["trend_strength"].reindex(df_res.index, method="ffill")
        df_res["h1_fvg_type"] = df_1h_fvg_aligned["fvg_type"].reindex(df_res.index, method="ffill")
        df_res["h1_fvg_top"] = df_1h_fvg_aligned["fvg_top"].reindex(df_res.index, method="ffill")
        df_res["h1_fvg_bottom"] = df_1h_fvg_aligned["fvg_bottom"].reindex(df_res.index, method="ffill")

        df_res["is_fvg_overlap_long"] = (
            (df_res["m15_fvg_type"] == "BULLISH")
            & (df_res["h1_fvg_type"] == "BULLISH")
            & ((df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]) & (df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]))
        )
        df_res["is_fvg_overlap_short"] = (
            (df_res["m15_fvg_type"] == "BEARISH")
            & (df_res["h1_fvg_type"] == "BEARISH")
            & ((df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]) & (df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]))
        )
        df_res["long_overlap_top"] = np.where(
            df_res["is_fvg_overlap_long"],
            np.minimum(df_res["m15_fvg_top"], df_res["h1_fvg_top"]),
            np.nan,
        )
        df_res["long_overlap_bottom"] = np.where(
            df_res["is_fvg_overlap_long"],
            np.maximum(df_res["m15_fvg_bottom"], df_res["h1_fvg_bottom"]),
            np.nan,
        )
        df_res["short_overlap_top"] = np.where(
            df_res["is_fvg_overlap_short"],
            np.minimum(df_res["m15_fvg_top"], df_res["h1_fvg_top"]),
            np.nan,
        )
        df_res["short_overlap_bottom"] = np.where(
            df_res["is_fvg_overlap_short"],
            np.maximum(df_res["m15_fvg_bottom"], df_res["h1_fvg_bottom"]),
            np.nan,
        )
        return df_res

    def load_all_data(self) -> None:
        print("正在載入多時段歷史數據...")
        self._load_primary_timeframes()
        self._load_micro_feed()

        print("正在注入大時區 V6 燃料扣抵...")
        for df in [self.df_1d, self.df_4h]:
            self._inject_bias(df)

        self.df_15m_indicators = self._build_indicator_matrix()
        print("💡 V8 頂級交易員抗噪重疊引擎封裝完畢。")

    def _record_trade(self, active_pos: dict, exit_time: pd.Timestamp, pnl: float, result: str, exit_price: Optional[float] = None, fee: float = 0.0) -> dict:
        if exit_price is None:
            exit_price = active_pos["entry_price"]
        return {
            "type": active_pos["type"],
            "entry_time": active_pos["entry_time"],
            "exit_time": exit_time,
            "pnl": pnl,
            "pnl_pct": (pnl / active_pos["entry_balance"]) * 100 if active_pos["entry_balance"] != 0 else 0.0,
            "result": result,
            "rr_potential": active_pos["rr_potential"],
            "rr_realized": pnl / active_pos["actual_risk_usd"] if active_pos["actual_risk_usd"] != 0 else 0.0,
            "entry_price": active_pos["entry_price"],
            "exit_price": exit_price,
            "sl": active_pos["sl"],
            "tp1": active_pos["tp1"],
            "tp2": active_pos["tp2"],
            "size": active_pos["size"],
            "entry_balance": active_pos["entry_balance"],
            "fee": fee,
            "accumulated_funding": active_pos["accumulated_funding"],
            "be_active": active_pos.get("be_active", False),
            "tp1_hit": active_pos.get("tp1_hit", False),
            "entry_mode": active_pos.get("entry_mode", "UNKNOWN"),
            "exit_model": active_pos.get("exit_model", "UNKNOWN"),
        }

    @staticmethod
    def _record_missed(trade_type: str, event_time: pd.Timestamp, reason: str, **extra: object) -> dict:
        missed = {"time": event_time, "type": trade_type, "reason": reason}
        missed.update(extra)
        return missed

    @staticmethod
    def _json_ready(record: dict) -> dict:
        converted = record.copy()
        for key in ("entry_time", "exit_time", "time", "signal_time"):
            if key in converted:
                converted[key] = str(converted[key])
        return converted

    @staticmethod
    def _directional_pnl(pos_type: str, quantity: float, entry_price: float, exit_price: float) -> float:
        if pos_type == "LONG":
            return quantity * (exit_price - entry_price)
        return quantity * (entry_price - exit_price)

    def _realize_tp1_partial(self, active_pos: dict, balance: float) -> float:
        if active_pos.get("tp1_realized", False) or active_pos["tp1_close_pct"] <= 0:
            return balance

        partial_qty = active_pos["size"] * active_pos["tp1_close_pct"]
        partial_fee = (partial_qty * active_pos["tp1"]) * self.config.maker_fee
        partial_pnl = self._directional_pnl(
            active_pos["type"],
            partial_qty,
            active_pos["entry_price"],
            active_pos["tp1"],
        ) - partial_fee

        active_pos["realized_pnl"] += partial_pnl
        active_pos["realized_fee"] += partial_fee
        active_pos["remaining_size"] = active_pos["size"] - partial_qty
        active_pos["tp1_realized"] = True
        return balance + partial_pnl

    def _calculate_market_exit(self, active_pos: dict, exit_price: float, fee_rate: float) -> Tuple[float, float, float]:
        remaining_qty = active_pos.get("remaining_size", active_pos["size"])
        exit_fee = (remaining_qty * exit_price) * fee_rate
        incremental_pnl = self._directional_pnl(
            active_pos["type"],
            remaining_qty,
            active_pos["entry_price"],
            exit_price,
        ) - exit_fee - active_pos["accumulated_funding"]
        total_pnl = active_pos.get("realized_pnl", 0.0) + incremental_pnl
        total_fee = active_pos.get("realized_fee", 0.0) + exit_fee
        return total_pnl, incremental_pnl, total_fee

    def _calculate_take_profit_all(self, active_pos: dict) -> Tuple[float, float, float]:
        remaining_qty = active_pos.get("remaining_size", active_pos["size"])
        remaining_fee = (remaining_qty * active_pos["tp2"]) * self.config.maker_fee
        remaining_pnl = self._directional_pnl(
            active_pos["type"],
            remaining_qty,
            active_pos["entry_price"],
            active_pos["tp2"],
        )

        if active_pos.get("tp1_realized", False):
            incremental_pnl = remaining_pnl - remaining_fee - active_pos["accumulated_funding"]
            total_pnl = active_pos["realized_pnl"] + incremental_pnl
            total_fee = active_pos["realized_fee"] + remaining_fee
            return total_pnl, incremental_pnl, total_fee

        partial_qty = active_pos["size"] * active_pos["tp1_close_pct"]
        partial_fee = (partial_qty * active_pos["tp1"]) * self.config.maker_fee
        partial_pnl = self._directional_pnl(
            active_pos["type"],
            partial_qty,
            active_pos["entry_price"],
            active_pos["tp1"],
        )
        total_fee = partial_fee + remaining_fee
        total_pnl = partial_pnl + remaining_pnl - total_fee - active_pos["accumulated_funding"]
        return total_pnl, total_pnl, total_fee

    def save_results_to_files(self, trades: Sequence[dict], missed_trades: Sequence[dict], prefix: str = "backtest_result") -> None:
        trades_json_path = Path(f"{prefix}_trades.json")
        missed_json_path = Path(f"{prefix}_missed.json")

        serializable_trades = [self._json_ready(t) for t in trades]
        serializable_missed = [self._json_ready(m) for m in missed_trades]

        with open(trades_json_path, "w", encoding="utf-8") as f:
            json.dump(serializable_trades, f, indent=4, ensure_ascii=False)
        with open(missed_json_path, "w", encoding="utf-8") as f:
            json.dump(serializable_missed, f, indent=4, ensure_ascii=False)

        df_trades = pd.DataFrame(trades)
        if not df_trades.empty:
            df_trades.to_csv(f"{prefix}_trades.csv", encoding="utf-8-sig")

        df_missed = pd.DataFrame(missed_trades)
        if not df_missed.empty:
            df_missed.to_csv(f"{prefix}_missed.csv", encoding="utf-8-sig")

        print(f"📊 成功將回測結果匯出：\n - 交易明細: {prefix}_trades.json / csv\n - 未觸發明細: {prefix}_missed.json / csv")

    def _check_1m_sequence(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        target_a: float,
        target_b: float,
        a_is_low: bool,
        b_is_high: bool,
    ) -> str:
        if not getattr(self, "has_micro_data", False):
            return "NONE"

        m1_slice = self.data_feed.load_micro_window(start_time, end_time, M1_COLUMNS)
        if m1_slice.empty:
            return "NONE"
        for _, row in m1_slice.iterrows():
            hit_a = (row["low"] <= target_a) if a_is_low else (row["high"] >= target_a)
            hit_b = (row["high"] >= target_b) if b_is_high else (row["low"] <= target_b)
            if hit_a and hit_b:
                return "A"
            if hit_a:
                return "A"
            if hit_b:
                return "B"
        return "NONE"

    @staticmethod
    def _validate_run_config(cfg: RunConfig) -> None:
        if cfg.entry_policy not in {"hybrid", "breakout_only", "retrace_only"}:
            raise ValueError("entry_policy must be one of: hybrid, breakout_only, retrace_only")
        if cfg.exit_model not in {"vwap", "structure_atr", "regime"}:
            raise ValueError("exit_model must be one of: vwap, structure_atr, regime")
        if cfg.regime_fallback not in {"structure_atr", "skip"}:
            raise ValueError("regime_fallback must be one of: structure_atr, skip")
        if not cfg.allow_long_entries and not cfg.allow_short_entries:
            raise ValueError("At least one of allow_long_entries or allow_short_entries must be True")

    @staticmethod
    def _allow_directions(mode: str, bias_1d: str, bias_4h: str, allow_long_entries: bool, allow_short_entries: bool) -> Tuple[bool, bool]:
        allowed_long, allowed_short = allow_long_entries, allow_short_entries
        if mode == "4H":
            if bias_4h != "LONG":
                allowed_long = False
            if bias_4h != "SHORT":
                allowed_short = False
        elif mode == "4H_1D":
            if bias_4h != "LONG" or bias_1d != "LONG":
                allowed_long = False
            if bias_4h != "SHORT" or bias_1d != "SHORT":
                allowed_short = False
        return allowed_long, allowed_short

    def _select_exit_model(self, prev: pd.Series, cfg: RunConfig) -> Optional[str]:
        if cfg.exit_model in {"vwap", "regime"} and pd.isna(prev["VWAP_SD"]):
            return None
        if cfg.exit_model in {"structure_atr", "regime"} and pd.isna(prev["ATR_14"]):
            return None

        use_regime_vwap = (
            cfg.exit_model == "regime"
            and pd.notna(prev["trend_strength_4h"])
            and pd.notna(prev["VWAP_SD_EXPANSION"])
            and prev["trend_strength_4h"] >= cfg.regime_trend_min
            and prev["VWAP_SD_EXPANSION"] >= cfg.regime_vwap_expansion_min
        )
        if use_regime_vwap:
            return "vwap"
        if cfg.exit_model == "regime":
            return cfg.regime_fallback
        return cfg.exit_model

    @staticmethod
    def _dynamic_tp2_extension_sd_mult(prev: pd.Series) -> float:
        trend_strength = float(prev["trend_strength_4h"]) if pd.notna(prev["trend_strength_4h"]) else 1.0
        vwap_expansion = float(prev["VWAP_SD_EXPANSION"]) if pd.notna(prev["VWAP_SD_EXPANSION"]) else 1.0

        trend_component = max(0.0, trend_strength - 1.0) * 0.35
        expansion_component = max(0.0, vwap_expansion - 1.0) * 0.45
        dynamic_mult = 0.9 + trend_component + expansion_component
        return min(2.4, max(0.8, dynamic_mult))

    @staticmethod
    def _breakout_min_rr_for_side(cfg: RunConfig, side: str) -> float:
        if side == "LONG" and cfg.breakout_min_rr_long is not None:
            return cfg.breakout_min_rr_long
        if side == "SHORT" and cfg.breakout_min_rr_short is not None:
            return cfg.breakout_min_rr_short
        return cfg.breakout_min_rr

    def _build_breakout_position(self, order: dict, curr: pd.Series, curr_time: pd.Timestamp, balance: float, cfg: RunConfig) -> Tuple[Optional[dict], Optional[dict]]:
        order_type = order["type"]

        if order_type == "LONG":
            market_entry_p = curr["open"] + self.config.slippage_usd
            if order["exit_model"] == "skip":
                return None, None
            if order["exit_model"] == "vwap":
                vwap_sd_padding = order["vwap_sd_padding"]
                sl = round(market_entry_p - (vwap_sd_padding * self.config.sl_sd_mult), 2)
                tp1 = order["tp1"]
                tp2 = order["tp2"]
            else:
                atr_buffer = order["atr"] * cfg.atr_buffer_mult
                sl = round(order["structure_sl"] - atr_buffer, 2)
                raw_risk = market_entry_p - sl
                tp1 = round(market_entry_p + raw_risk, 2)
                tp2 = round(market_entry_p + raw_risk * cfg.fixed_rr, 2)
            expected_fee_drag = (market_entry_p * self.config.taker_fee) + (sl * self.config.taker_fee)
            net_sl_dist = (market_entry_p - sl) + expected_fee_drag
            is_valid_target = tp2 > market_entry_p
            math_rr = ((tp1 - market_entry_p) * cfg.tp1_close_pct + (tp2 - market_entry_p) * (1.0 - cfg.tp1_close_pct)) / net_sl_dist if net_sl_dist > 0 else 0.0
        else:
            market_entry_p = curr["open"] - self.config.slippage_usd
            if order["exit_model"] == "skip":
                return None, None
            if order["exit_model"] == "vwap":
                vwap_sd_padding = order["vwap_sd_padding"]
                sl = round(market_entry_p + (vwap_sd_padding * self.config.sl_sd_mult), 2)
                tp1 = order["tp1"]
                tp2 = order["tp2"]
            else:
                atr_buffer = order["atr"] * cfg.atr_buffer_mult
                sl = round(order["structure_sl"] + atr_buffer, 2)
                raw_risk = sl - market_entry_p
                tp1 = round(market_entry_p - raw_risk, 2)
                tp2 = round(market_entry_p - raw_risk * cfg.fixed_rr, 2)
            expected_fee_drag = (market_entry_p * self.config.taker_fee) + (sl * self.config.taker_fee)
            net_sl_dist = (sl - market_entry_p) + expected_fee_drag
            is_valid_target = market_entry_p > tp2
            math_rr = ((market_entry_p - tp1) * cfg.tp1_close_pct + (market_entry_p - tp2) * (1.0 - cfg.tp1_close_pct)) / net_sl_dist if net_sl_dist > 0 else 0.0

        min_rr = self._breakout_min_rr_for_side(cfg, order_type)
        if net_sl_dist > 0 and is_valid_target and math_rr >= min_rr:
            initial_risk_usd = balance * self.config.risk_pct
            size = min(initial_risk_usd / net_sl_dist, order["volume_cap"])
            return {
                "type": order_type,
                "entry_idx": order["created_idx"] + 1,
                "entry_time": curr_time,
                "entry_price": market_entry_p,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "size": size,
                "entry_balance": balance,
                "rr_potential": math_rr,
                "actual_risk_usd": size * net_sl_dist,
                "tp1_hit": False,
                "be_active": False,
                "accumulated_funding": 0.0,
                "tp1_close_pct": cfg.tp1_close_pct,
                "remaining_size": size,
                "realized_pnl": 0.0,
                "realized_fee": 0.0,
                "tp1_realized": False,
                "entry_mode": "BREAKOUT",
                "exit_model": order["exit_model"],
            }, None

        missed = self._record_missed(
            order_type,
            curr_time,
            "BREAKOUT_RR_FILTERED",
            signal_time=order["signal_time"],
            entry_price=market_entry_p,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            rr=math_rr,
            min_rr=min_rr,
            exit_model=order["exit_model"],
        )
        return None, missed

    def _resolve_position_event(
        self,
        active_position: dict,
        curr_time: pd.Timestamp,
        prev_time: pd.Timestamp,
        balance: float,
        trades: List[dict],
        is_sl_hit: bool,
        is_tp1_hit_now: bool,
        is_tp2_hit_now: bool,
        current_sl: float,
        be_active: bool,
        a_is_low: bool,
        b_is_high: bool,
    ) -> Tuple[Optional[dict], float]:
        tp1 = active_position["tp1"]
        tp2 = active_position["tp2"]

        if is_sl_hit and is_tp1_hit_now:
            seq = self._check_1m_sequence(prev_time, curr_time, current_sl, tp1, a_is_low=a_is_low, b_is_high=b_is_high)
            if seq == "B":
                active_position["tp1_hit"] = True
                if is_tp2_hit_now:
                    net_pnl, balance_delta, fee = self._calculate_take_profit_all(active_position)
                    balance += balance_delta
                    trades.append(self._record_trade(active_position, curr_time, net_pnl, "TAKE_PROFIT_ALL", exit_price=tp2, fee=fee))
                    return None, balance
                balance = self._realize_tp1_partial(active_position, balance)
                return active_position, balance

            net_pnl, balance_delta, fee = self._calculate_market_exit(active_position, current_sl, self.config.taker_fee)
            balance += balance_delta
            result = "BREAKEVEN" if be_active else "STOP_LOSS"
            trades.append(self._record_trade(active_position, curr_time, net_pnl, result, exit_price=current_sl, fee=fee))
            return None, balance

        if is_sl_hit:
            net_pnl, balance_delta, fee = self._calculate_market_exit(active_position, current_sl, self.config.taker_fee)
            balance += balance_delta
            result = "BREAKEVEN" if be_active else "STOP_LOSS"
            trades.append(self._record_trade(active_position, curr_time, net_pnl, result, exit_price=current_sl, fee=fee))
            return None, balance

        if is_tp1_hit_now:
            active_position["tp1_hit"] = True
            if is_tp2_hit_now:
                net_pnl, balance_delta, fee = self._calculate_take_profit_all(active_position)
                balance += balance_delta
                trades.append(self._record_trade(active_position, curr_time, net_pnl, "TAKE_PROFIT_ALL", exit_price=tp2, fee=fee))
                return None, balance
            balance = self._realize_tp1_partial(active_position, balance)
            return active_position, balance

        if active_position.get("tp1_hit", False) and is_tp2_hit_now:
            net_pnl, balance_delta, fee = self._calculate_take_profit_all(active_position)
            balance += balance_delta
            trades.append(self._record_trade(active_position, curr_time, net_pnl, "TAKE_PROFIT_ALL", exit_price=tp2, fee=fee))
            return None, balance

        return active_position, balance

    def _manage_active_position(
        self,
        active_position: dict,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        prev_time: pd.Timestamp,
        loop_index: int,
        balance: float,
        trades: List[dict],
        cfg: RunConfig,
    ) -> Tuple[Optional[dict], float]:
        current_max_holding = self.config.max_holding_bars * 3 if active_position.get("be_active", False) else self.config.max_holding_bars
        bars_held = loop_index - active_position["entry_idx"]

        if bars_held >= current_max_holding:
            net_pnl, balance_delta, fee = self._calculate_market_exit(active_position, curr["close"], self.config.taker_fee)
            balance += balance_delta
            trades.append(self._record_trade(active_position, curr_time, net_pnl, "TIME_STOP", exit_price=curr["close"], fee=fee))
            return None, balance

        if curr_time.hour % 8 == 0 and curr_time.minute == 0:
            active_position["accumulated_funding"] += active_position["size"] * curr["open"] * self.config.funding_rate_8h

        pos_type = active_position["type"]
        entry_price = active_position["entry_price"]
        current_sl = active_position["sl"]
        tp1 = active_position["tp1"]
        tp2 = active_position["tp2"]
        tp1_hit = active_position.get("tp1_hit", False)
        be_active = active_position.get("be_active", False)

        be_trigger_p = entry_price + (tp1 - entry_price) * cfg.be_trigger_ratio if pos_type == "LONG" else entry_price - (entry_price - tp1) * cfg.be_trigger_ratio
        is_be_trigger_hit = (curr["high"] >= be_trigger_p) if pos_type == "LONG" else (curr["low"] <= be_trigger_p)
        if cfg.enable_be and is_be_trigger_hit and not be_active:
            active_position["be_active"] = True
            active_position["sl"] = entry_price
            current_sl = entry_price

        if pos_type == "LONG":
            is_sl_hit = curr["low"] <= current_sl
            is_tp1_hit_now = (not tp1_hit) and (curr["high"] >= tp1)
            is_tp2_hit_now = curr["high"] >= tp2
            return self._resolve_position_event(
                active_position,
                curr_time,
                prev_time,
                balance,
                trades,
                is_sl_hit,
                is_tp1_hit_now,
                is_tp2_hit_now,
                current_sl,
                be_active,
                a_is_low=True,
                b_is_high=True,
            )

        is_sl_hit = curr["high"] >= current_sl
        is_tp1_hit_now = (not tp1_hit) and (curr["low"] <= tp1)
        is_tp2_hit_now = curr["low"] <= tp2
        return self._resolve_position_event(
            active_position,
            curr_time,
            prev_time,
            balance,
            trades,
            is_sl_hit,
            is_tp1_hit_now,
            is_tp2_hit_now,
            current_sl,
            be_active,
            a_is_low=False,
            b_is_high=True,
        )

    def _handle_pending_retest_order(
        self,
        pending_retest_order: Optional[dict],
        active_position: Optional[dict],
        curr: pd.Series,
        curr_time: pd.Timestamp,
        loop_index: int,
        balance: float,
        missed_trades: List[dict],
    ) -> Tuple[Optional[dict], Optional[dict], float]:
        if active_position is not None or pending_retest_order is None:
            return pending_retest_order, active_position, balance

        o_type = pending_retest_order["type"]
        limit_price = pending_retest_order["entry_price"]
        sl_p = pending_retest_order["sl"]

        if (loop_index - pending_retest_order["created_idx"]) > 72:
            missed_trades.append(
                self._record_missed(
                    o_type,
                    curr_time,
                    "ORDER_EXPIRED",
                    entry_price=limit_price,
                    sl=sl_p,
                    tp1=pending_retest_order["tp1"],
                    tp2=pending_retest_order["tp2"],
                    rr=pending_retest_order["rr_potential"],
                )
            )
            return None, active_position, balance

        if loop_index <= pending_retest_order["created_idx"]:
            return pending_retest_order, active_position, balance

        if o_type == "LONG":
            # 保守處理同棒穿越 entry 與 stop 的情況，避免回測高估掛單品質。
            if curr["low"] <= sl_p:
                missed_trades.append(
                    self._record_missed(
                        "LONG",
                        curr_time,
                        "SETUP_INVALIDATED_BEFORE_FILL",
                        entry_price=limit_price,
                        sl=sl_p,
                        tp1=pending_retest_order["tp1"],
                        tp2=pending_retest_order["tp2"],
                        rr=pending_retest_order["rr_potential"],
                    )
                )
                return None, active_position, balance
            if curr["low"] <= limit_price:
                active_position = pending_retest_order
                active_position["entry_idx"] = loop_index
                active_position["entry_time"] = curr_time
                balance -= (active_position["size"] * limit_price) * self.config.maker_fee
                return None, active_position, balance
            return pending_retest_order, active_position, balance

        # 對空單採相同保守規則，避免同棒先碰停損卻被算成成交。
        if curr["high"] >= sl_p:
            missed_trades.append(
                self._record_missed(
                    "SHORT",
                    curr_time,
                    "SETUP_INVALIDATED_BEFORE_FILL",
                    entry_price=limit_price,
                    sl=sl_p,
                    tp1=pending_retest_order["tp1"],
                    tp2=pending_retest_order["tp2"],
                    rr=pending_retest_order["rr_potential"],
                )
            )
            return None, active_position, balance
        if curr["high"] >= limit_price:
            active_position = pending_retest_order
            active_position["entry_idx"] = loop_index
            active_position["entry_time"] = curr_time
            balance -= (active_position["size"] * limit_price) * self.config.maker_fee
            return None, active_position, balance
        return pending_retest_order, active_position, balance

    @staticmethod
    def _profit_pct_from_equity_curve(trades: Sequence[dict]) -> float:
        if len(trades) == 0:
            return 0.0

        df_trades = pd.DataFrame(trades).sort_values("entry_time")
        start_balance = float(df_trades.iloc[0]["entry_balance"])
        end_balance = float(df_trades.iloc[-1]["entry_balance"] + df_trades.iloc[-1]["pnl"])
        if start_balance == 0:
            return 0.0
        return ((end_balance - start_balance) / start_balance) * 100

    def _build_retrace_order(
        self,
        side: str,
        prev: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        tp1_close_pct: float,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        net_sl_dist: float,
    ) -> Tuple[Optional[dict], Optional[dict]]:
        valid_target = tp2 > entry_price if side == "LONG" else entry_price > tp2
        if net_sl_dist <= 0 or not valid_target:
            return None, None

        if side == "LONG":
            math_rr = ((tp1 - entry_price) * tp1_close_pct + (tp2 - entry_price) * (1.0 - tp1_close_pct)) / net_sl_dist
        else:
            math_rr = ((entry_price - tp1) * tp1_close_pct + (entry_price - tp2) * (1.0 - tp1_close_pct)) / net_sl_dist

        if math_rr >= self.config.min_net_profit_r:
            initial_risk_usd = balance * self.config.risk_pct
            size = min(initial_risk_usd / net_sl_dist, prev["volume"] * self.config.max_vol_pct)
            return {
                "type": side,
                "created_idx": None,
                "entry_price": entry_price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "size": size,
                "entry_balance": balance,
                "rr_potential": math_rr,
                "actual_risk_usd": size * net_sl_dist,
                "tp1_hit": False,
                "be_active": False,
                "accumulated_funding": 0.0,
                "tp1_close_pct": tp1_close_pct,
                "remaining_size": size,
                "realized_pnl": 0.0,
                "realized_fee": 0.0,
                "tp1_realized": False,
                "entry_mode": "RETRACE",
            }, None

        return None, self._record_missed(
            side,
            curr_time,
            "RETRACE_FILLED_BUT_RR_FILTERED",
            entry_price=entry_price,
            limit_price=entry_price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            rr=math_rr,
        )

    def _scan_entry_signal(
        self,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> Tuple[Optional[dict], Optional[dict], List[dict]]:
        missed: List[dict] = []
        selected_exit_model = self._select_exit_model(prev, cfg)
        if selected_exit_model is None:
            return None, None, missed

        allowed_long, allowed_short = self._allow_directions(
            cfg.mode,
            prev["bias_1d"],
            prev["bias_4h"],
            cfg.allow_long_entries,
            cfg.allow_short_entries,
        )
        allow_retrace_entry = cfg.entry_policy in {"hybrid", "retrace_only"}
        allow_breakout_entry = cfg.enable_breakout_entry and cfg.entry_policy in {"hybrid", "breakout_only"}

        if allowed_long and prev["is_fvg_overlap_long"] and pd.notna(prev["long_overlap_top"]) and pd.notna(prev["long_overlap_bottom"]):
            vwap_long_ok = (not cfg.use_vwap_direction_filter) or (prev["close"] > prev["VWAP"])
            if vwap_long_ok and prev["local_bias"] == "LONG":
                overlap_height = prev["long_overlap_top"] - prev["long_overlap_bottom"]
                limit_p = prev["long_overlap_top"] - (overlap_height * self.config.entry_buffer_pct)
                vwap_sd_padding = max(prev["VWAP_SD"], 80.0) if pd.notna(prev["VWAP_SD"]) else 80.0
                tp2_extension_sd_mult = self._dynamic_tp2_extension_sd_mult(prev)

                if allow_retrace_entry:
                    entry_price = limit_p
                    sl = round(entry_price - (vwap_sd_padding * self.config.sl_sd_mult), 2)
                    tp1 = round(prev["VWAP_1.0_SD_Upper"], 2)
                    tp2 = round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * tp2_extension_sd_mult, 2)
                    expected_fee_drag = (entry_price * self.config.maker_fee) + (sl * self.config.taker_fee)
                    net_sl_dist = (entry_price - sl) + expected_fee_drag
                    order, miss = self._build_retrace_order("LONG", prev, curr_time, balance, cfg.tp1_close_pct, entry_price, sl, tp1, tp2, net_sl_dist)
                    if order is not None:
                        return order, None, missed
                    if miss is not None:
                        missed.append(miss)
                    return None, None, missed

                if allow_breakout_entry and curr["close"] > prev["high"]:
                    return None, {
                        "type": "LONG",
                        "created_idx": None,
                        "signal_time": curr_time,
                        "exit_model": selected_exit_model,
                        "vwap_sd_padding": vwap_sd_padding,
                        "tp1": round(prev["VWAP_1.0_SD_Upper"], 2),
                        "tp2": round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * tp2_extension_sd_mult, 2),
                        "structure_sl": prev["long_overlap_bottom"],
                        "atr": prev["ATR_14"],
                        "volume_cap": curr["volume"] * self.config.max_vol_pct,
                    }, missed

        if allowed_short and prev["is_fvg_overlap_short"] and pd.notna(prev["short_overlap_bottom"]) and pd.notna(prev["short_overlap_top"]):
            vwap_short_ok = (not cfg.use_vwap_direction_filter) or (prev["close"] < prev["VWAP"])
            if vwap_short_ok and prev["local_bias"] == "SHORT":
                overlap_height = prev["short_overlap_top"] - prev["short_overlap_bottom"]
                limit_p = prev["short_overlap_bottom"] + (overlap_height * self.config.entry_buffer_pct)
                vwap_sd_padding = max(prev["VWAP_SD"], 80.0) if pd.notna(prev["VWAP_SD"]) else 80.0
                tp2_extension_sd_mult = self._dynamic_tp2_extension_sd_mult(prev)

                if allow_retrace_entry:
                    entry_price = limit_p
                    sl = round(entry_price + (vwap_sd_padding * self.config.sl_sd_mult), 2)
                    tp1 = round(prev["VWAP_1.0_SD_Lower"], 2)
                    tp2 = round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * tp2_extension_sd_mult, 2)
                    expected_fee_drag = (entry_price * self.config.maker_fee) + (sl * self.config.taker_fee)
                    net_sl_dist = (sl - entry_price) + expected_fee_drag
                    order, miss = self._build_retrace_order("SHORT", prev, curr_time, balance, cfg.tp1_close_pct, entry_price, sl, tp1, tp2, net_sl_dist)
                    if order is not None:
                        return order, None, missed
                    if miss is not None:
                        missed.append(miss)
                    return None, None, missed

                if allow_breakout_entry and curr["close"] < prev["low"]:
                    return None, {
                        "type": "SHORT",
                        "created_idx": None,
                        "signal_time": curr_time,
                        "exit_model": selected_exit_model,
                        "vwap_sd_padding": vwap_sd_padding,
                        "tp1": round(prev["VWAP_1.0_SD_Lower"], 2),
                        "tp2": round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * tp2_extension_sd_mult, 2),
                        "structure_sl": prev["short_overlap_top"],
                        "atr": prev["ATR_14"],
                        "volume_cap": curr["volume"] * self.config.max_vol_pct,
                    }, missed

        return None, None, missed

    def run_session(self, force_close_at_end: bool = True, **kwargs: object) -> BacktestSessionResult:
        cfg = RunConfig(**kwargs)
        self._validate_run_config(cfg)

        balance = self.initial_balance
        trades: List[dict] = []
        missed_trades: List[dict] = []
        df = self.df_15m_indicators.copy()
        active_position: Optional[dict] = None
        pending_retest_order: Optional[dict] = None
        pending_breakout_order: Optional[dict] = None
        lookback = 96

        for i in range(lookback, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]
            curr_time = df.index[i]
            prev_time = df.index[i - 1]

            if active_position is None and pending_breakout_order is not None and i > pending_breakout_order["created_idx"]:
                position, missed = self._build_breakout_position(pending_breakout_order, curr, curr_time, balance, cfg)
                if position is not None:
                    active_position = position
                    balance -= (position["size"] * position["entry_price"]) * self.config.taker_fee
                elif missed is not None:
                    missed_trades.append(missed)
                pending_breakout_order = None

            if active_position is not None:
                active_position, balance = self._manage_active_position(active_position, curr, curr_time, prev_time, i, balance, trades, cfg)
                if active_position is None:
                    continue

            pending_retest_order, active_position, balance = self._handle_pending_retest_order(
                pending_retest_order,
                active_position,
                curr,
                curr_time,
                i,
                balance,
                missed_trades,
            )

            if active_position is None and pending_retest_order is None and pending_breakout_order is None:
                retrace_order, breakout_order, missed = self._scan_entry_signal(prev, curr, curr_time, balance, cfg)
                missed_trades.extend(missed)
                if retrace_order is not None:
                    retrace_order["created_idx"] = i
                    pending_retest_order = retrace_order
                elif breakout_order is not None:
                    breakout_order["created_idx"] = i
                    pending_breakout_order = breakout_order

        if force_close_at_end and active_position is not None:
            last_bar = df.iloc[-1]
            net_pnl, balance_delta, fee = self._calculate_market_exit(active_position, last_bar["close"], self.config.taker_fee)
            balance += balance_delta
            trades.append(self._record_trade(active_position, df.index[-1], net_pnl, "FORCE_CLOSE", exit_price=last_bar["close"], fee=fee))
            active_position = None

        return BacktestSessionResult(
            trades=trades,
            missed_trades=missed_trades,
            balance=balance,
            active_position=active_position,
            pending_retest_order=pending_retest_order,
            pending_breakout_order=pending_breakout_order,
        )

    def run_backtest(self, **kwargs: object) -> Tuple[List[dict], List[dict]]:
        session = self.run_session(force_close_at_end=True, **kwargs)
        return session.trades, session.missed_trades

    def build_runtime_snapshot(self, strategy: StrategyConfig) -> dict:
        self.config = strategy.to_backtest_config()
        session = self.run_session(force_close_at_end=False, **strategy.to_run_config().__dict__)
        latest_time = None
        if not self.df_15m_indicators.empty:
            latest_time = self.df_15m_indicators.index[-1]
        latest_trade = session.trades[-1] if session.trades else None
        latest_missed = session.missed_trades[-1] if session.missed_trades else None
        return {
            "as_of": str(latest_time) if latest_time is not None else None,
            "balance": session.balance,
            "active_position": self._json_ready(session.active_position) if session.active_position is not None else None,
            "pending_retest_order": self._json_ready(session.pending_retest_order) if session.pending_retest_order is not None else None,
            "pending_breakout_order": self._json_ready(session.pending_breakout_order) if session.pending_breakout_order is not None else None,
            "latest_trade": self._json_ready(latest_trade) if latest_trade is not None else None,
            "latest_missed": self._json_ready(latest_missed) if latest_missed is not None else None,
            "trade_count": len(session.trades),
            "missed_count": len(session.missed_trades),
        }

    def analyze_results(self, trades: Sequence[dict]) -> dict:
        total_trades = len(trades)
        if total_trades == 0:
            return {"trades": 0, "win_rate": 0.0, "profit_pct": 0.0, "tp_all": 0, "be": 0, "sl": 0, "time_stop": 0, "avg_potential_rr": 0.0, "avg_realized_rr": 0.0, "avg_trade_r": 0.0}

        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]
        avg_potential_rr = df_trades["rr_potential"].mean()
        df_profitable = df_trades[df_trades["rr_realized"] > 0]
        df_losing = df_trades[df_trades["rr_realized"] < 0]
        avg_win_r = df_profitable["rr_realized"].mean() if len(df_profitable) > 0 else 0.0
        avg_loss_r = abs(df_losing["rr_realized"].mean()) if len(df_losing) > 0 else 1.0
        return {
            "trades": total_trades,
            "win_rate": (len(wins) / total_trades) * 100,
            "profit_pct": self._profit_pct_from_equity_curve(trades),
            "tp_all": len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]) + len(df_trades[(df_trades["result"] == "FORCE_CLOSE") & (df_trades["pnl"] > 0)]),
            "be": len(df_trades[df_trades["result"] == "BREAKEVEN"]),
            "sl": len(df_trades[df_trades["result"] == "STOP_LOSS"]) + len(df_trades[(df_trades["result"] == "FORCE_CLOSE") & (df_trades["pnl"] <= 0)]),
            "time_stop": len(df_trades[df_trades["result"] == "TIME_STOP"]),
            "avg_potential_rr": avg_potential_rr,
            "avg_realized_rr": avg_win_r / avg_loss_r if avg_loss_r > 0 else 0.0,
            "avg_trade_r": df_trades["rr_realized"].mean(),
        }

    def _build_direction_report_row(self, label: str, trades: Sequence[dict], missed_count: int) -> dict:
        res = self.analyze_results(trades)
        direction_pnl = sum(float(trade["pnl"]) for trade in trades)
        direction_profit_pct = (direction_pnl / self.initial_balance) * 100 if self.initial_balance != 0 else 0.0
        total_events = res["trades"] + missed_count
        miss_rate = (missed_count / total_events) * 100 if total_events > 0 else 0.0
        return {
            "SIDE": label,
            "TRADES": int(res["trades"]),
            "P_RR": f"1:{res['avg_potential_rr']:.2f}",
            "R_RR": f"1:{res['avg_realized_rr']:.2f}",
            "E_R": f"{res['avg_trade_r']:+.2f}",
            "WIN%": f"{res['win_rate']:.2f}%",
            "TP2": int(res["tp_all"]),
            "BE": int(res["be"]),
            "TS": int(res["time_stop"]),
            "SL": int(res["sl"]),
            "PROFIT": f"{direction_profit_pct:+.2f}%",
            "MISSED": missed_count,
            "M_RATE": f"{miss_rate:.1f}%",
        }

    def generate_and_print_report(self, strategy_name: str, trades: Sequence[dict], missed_list: Sequence[dict]) -> None:
        df_trades = pd.DataFrame(trades) if len(trades) > 0 else pd.DataFrame()
        df_missed = pd.DataFrame(missed_list) if len(missed_list) > 0 else pd.DataFrame(columns=["time", "type"])
        if not df_missed.empty:
            df_missed["month"] = df_missed["time"].dt.to_period("M")
        if not df_trades.empty:
            df_trades["month"] = df_trades["entry_time"].dt.to_period("M")
        all_months = sorted(
            list(
                set(
                    ([str(m) for m in df_trades["month"].unique()] if not df_trades.empty else [])
                    + ([str(m) for m in df_missed["month"].unique()] if not df_missed.empty else [])
                )
            )
        )

        reports = []
        overall_res = self.analyze_results(trades)
        overall_m_rate = (len(df_missed) / (overall_res["trades"] + len(df_missed)) * 100) if (overall_res["trades"] + len(df_missed)) > 0 else 0.0
        reports.append({"PERIOD": "TOTAL", "TRADES": int(overall_res["trades"]), "P_RR": f"1:{overall_res['avg_potential_rr']:.2f}", "R_RR": f"1:{overall_res['avg_realized_rr']:.2f}", "E_R": f"{overall_res['avg_trade_r']:+.2f}", "WIN%": f"{overall_res['win_rate']:.2f}%", "TP2": int(overall_res["tp_all"]), "BE": int(overall_res["be"]), "TS": int(overall_res["time_stop"]), "SL": int(overall_res["sl"]), "PROFIT": f"{overall_res['profit_pct']:+.2f}%", "MISSED": len(df_missed), "M_RATE": f"{overall_m_rate:.1f}%"})

        for m_str in all_months:
            m_period = pd.Period(m_str, freq="M")
            m_trades_sub = df_trades[df_trades["month"] == m_period].to_dict("records") if not df_trades.empty else []
            m_missed_cnt = len(df_missed[df_missed["month"] == m_period]) if not df_missed.empty else 0
            m_res = self.analyze_results(m_trades_sub)
            m_rate_val = (m_missed_cnt / (m_res["trades"] + m_missed_cnt) * 100) if (m_res["trades"] + m_missed_cnt) > 0 else 0.0
            reports.append({"PERIOD": m_str, "TRADES": int(m_res["trades"]), "P_RR": f"1:{m_res['avg_potential_rr']:.2f}", "R_RR": f"1:{m_res['avg_realized_rr']:.2f}", "E_R": f"{m_res['avg_trade_r']:+.2f}", "WIN%": f"{m_res['win_rate']:.2f}%", "TP2": int(m_res["tp_all"]), "BE": int(m_res["be"]), "TS": int(m_res["time_stop"]), "SL": int(m_res["sl"]), "PROFIT": f"{m_res['profit_pct']:+.2f}%", "MISSED": m_missed_cnt, "M_RATE": f"{m_rate_val:.1f}%"})

        def pad_cjk(text: object, width: int) -> str:
            text = str(text)
            cjk_count = sum(1 for char in text if ord(char) > 127)
            actual_pad = max(0, width - len(text) - cjk_count)
            return text + " " * actual_pad

        print("\n" + "=" * 125)
        print(f" V8 Omniscient Eye Report (策略分流版 v9.9) - {strategy_name}")
        print("=" * 125)
        header = f"{pad_cjk('PERIOD', 12)} | {'TRADES':<6} | {'P_RR':<8} | {'RE_RR':<8} | {'E_R':<6} | {'WIN%':<8} | {'TP2':<5} | {'BE':<5} | {'TS':<5} | {'SL':<5} | {'PROFIT':<9} | {'MISSED':<6} | {'M_RATE':<6}"
        print(header)
        print("-" * 125)
        for r in reports:
            print(f"{pad_cjk(r['PERIOD'], 12)} | {r['TRADES']:<6} | {r['P_RR']:<8} | {r['R_RR']:<8} | {r['E_R']:<6} | {r['WIN%']:<8} | {r['TP2']:<5} | {r['BE']:<5} | {r['TS']:<5} | {r['SL']:<5} | {r['PROFIT']:<9} | {r['MISSED']:<6} | {r['M_RATE']:<6}")
        print("=" * 125 + "\n")

        long_trades = df_trades[df_trades["type"] == "LONG"].to_dict("records") if not df_trades.empty and "type" in df_trades.columns else []
        short_trades = df_trades[df_trades["type"] == "SHORT"].to_dict("records") if not df_trades.empty and "type" in df_trades.columns else []
        long_missed = int((df_missed["type"] == "LONG").sum()) if not df_missed.empty and "type" in df_missed.columns else 0
        short_missed = int((df_missed["type"] == "SHORT").sum()) if not df_missed.empty and "type" in df_missed.columns else 0

        direction_reports = [
            self._build_direction_report_row("LONG", long_trades, long_missed),
            self._build_direction_report_row("SHORT", short_trades, short_missed),
        ]

        print("Direction Breakdown:")
        print("-" * 125)
        print(f"{'SIDE':<12} | {'TRADES':<6} | {'P_RR':<8} | {'RE_RR':<8} | {'E_R':<6} | {'WIN%':<8} | {'TP2':<5} | {'BE':<5} | {'TS':<5} | {'SL':<5} | {'PROFIT':<9} | {'MISSED':<6} | {'M_RATE':<6}")
        print("-" * 125)
        for r in direction_reports:
            print(f"{r['SIDE']:<12} | {r['TRADES']:<6} | {r['P_RR']:<8} | {r['R_RR']:<8} | {r['E_R']:<6} | {r['WIN%']:<8} | {r['TP2']:<5} | {r['BE']:<5} | {r['TS']:<5} | {r['SL']:<5} | {r['PROFIT']:<9} | {r['MISSED']:<6} | {r['M_RATE']:<6}")
        print()

        if not df_missed.empty and "reason" in df_missed.columns:
            reason_counts = df_missed["reason"].value_counts()
            print("Miss Reason Breakdown:")
            for reason, count in reason_counts.items():
                print(f" - {reason}: {count}")
            print()
