from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision


class FelisaConfluenceStrategy:
    """4H 趨勢線與斐波那契重合，1H 收線確認後回踩進場。"""

    def __init__(
        self,
        htf: str = "4h",
        ltf: str = "1h",
        swing_n: int = 2,
        confluence_atr_mult: float = 0.25,
        zone_buffer_atr_mult: float = 0.10,
        wick_body_ratio: float = 1.5,
    ) -> None:
        self.htf = htf
        self.ltf = ltf
        self.swing_n = swing_n
        self.confluence_atr_mult = confluence_atr_mult
        self.zone_buffer_atr_mult = zone_buffer_atr_mult
        self.wick_body_ratio = wick_body_ratio
        self.precomputed_htf_df: Optional[pd.DataFrame] = None

    def signal_timeframe(self) -> str:
        return self.ltf

    def _precompute_htf_states(self, df: pd.DataFrame) -> pd.DataFrame:
        n = self.swing_n
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        index = df.index
        prev_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(14, min_periods=1).mean().to_numpy()

        swing_highs: list[dict] = []
        swing_lows: list[dict] = []
        rows: list[dict] = []

        for i in range(len(df)):
            pivot_i = i - n
            if pivot_i >= n:
                high_window = highs[pivot_i - n : pivot_i + n + 1]
                low_window = lows[pivot_i - n : pivot_i + n + 1]
                if highs[pivot_i] == high_window.max() and (high_window == highs[pivot_i]).sum() == 1:
                    swing_highs.append({"i": pivot_i, "time": index[pivot_i], "price": float(highs[pivot_i])})
                if lows[pivot_i] == low_window.min() and (low_window == lows[pivot_i]).sum() == 1:
                    swing_lows.append({"i": pivot_i, "time": index[pivot_i], "price": float(lows[pivot_i])})

            state = {
                "trend": "NONE",
                "line_time": pd.NaT,
                "line_price": np.nan,
                "line_slope_hour": np.nan,
                "impulse_low": np.nan,
                "impulse_high": np.nan,
                "atr": float(atr[i]),
                "sr_levels": (),
            }
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                last_highs = swing_highs[-2:]
                last_lows = swing_lows[-2:]
                uptrend = last_highs[1]["price"] > last_highs[0]["price"] and last_lows[1]["price"] > last_lows[0]["price"]
                downtrend = last_highs[1]["price"] < last_highs[0]["price"] and last_lows[1]["price"] < last_lows[0]["price"]

                if uptrend:
                    impulse_high = swing_highs[-1]
                    prior_lows = [point for point in swing_lows if point["i"] < impulse_high["i"]]
                    if prior_lows:
                        state.update(self._trend_state("LONG", last_lows, prior_lows[-1]["price"], impulse_high["price"]))
                elif downtrend:
                    impulse_low = swing_lows[-1]
                    prior_highs = [point for point in swing_highs if point["i"] < impulse_low["i"]]
                    if prior_highs:
                        state.update(self._trend_state("SHORT", last_highs, impulse_low["price"], prior_highs[-1]["price"]))

                state["sr_levels"] = tuple(point["price"] for point in (swing_highs[-4:] + swing_lows[-4:]))
            rows.append(state)

        result = pd.DataFrame(rows, index=index + pd.Timedelta(self.htf))
        return result

    @staticmethod
    def _trend_state(trend: str, anchors: list[dict], impulse_low: float, impulse_high: float) -> dict:
        hours = (anchors[1]["time"] - anchors[0]["time"]).total_seconds() / 3600
        return {
            "trend": trend,
            "line_time": anchors[1]["time"],
            "line_price": anchors[1]["price"],
            "line_slope_hour": (anchors[1]["price"] - anchors[0]["price"]) / hours,
            "impulse_low": impulse_low,
            "impulse_high": impulse_high,
        }

    def _confluence(self, state: pd.Series, at_time: pd.Timestamp) -> Optional[dict]:
        if state["trend"] not in ("LONG", "SHORT") or not state["atr"] > 0:
            return None
        elapsed_hours = (at_time - state["line_time"]).total_seconds() / 3600
        trendline = float(state["line_price"] + state["line_slope_hour"] * elapsed_hours)
        impulse_low = float(state["impulse_low"])
        impulse_high = float(state["impulse_high"])
        if not impulse_low < trendline < impulse_high:
            return None

        span = impulse_high - impulse_low
        ratios = (0.5, 0.618, 0.786)
        if state["trend"] == "LONG":
            fibs = [(ratio, impulse_high - span * ratio) for ratio in ratios]
        else:
            fibs = [(ratio, impulse_low + span * ratio) for ratio in ratios]
        ratio, fib_price = min(fibs, key=lambda item: abs(item[1] - trendline))
        tolerance = float(state["atr"]) * self.confluence_atr_mult
        if abs(fib_price - trendline) > tolerance:
            return None

        buffer = float(state["atr"]) * self.zone_buffer_atr_mult
        center = (fib_price + trendline) / 2
        return {
            "ratio": ratio,
            "center": center,
            "low": min(fib_price, trendline) - buffer,
            "high": max(fib_price, trendline) + buffer,
            "triple": any(abs(float(level) - center) <= tolerance for level in state["sr_levels"]),
        }

    def _confirmed_rejection(self, side: str, prev: pd.Series, curr: pd.Series) -> bool:
        body = max(abs(float(curr["close"]) - float(curr["open"])), 1e-12)
        if side == "LONG":
            wick = min(float(curr["open"]), float(curr["close"])) - float(curr["low"])
            engulfing = (
                curr["close"] > curr["open"]
                and curr["open"] <= prev["close"]
                and curr["close"] >= prev["open"]
                and curr["volume"] > prev["volume"]
            )
            return (curr["close"] > curr["open"] and wick >= body * self.wick_body_ratio) or engulfing

        wick = float(curr["high"]) - max(float(curr["open"]), float(curr["close"]))
        engulfing = (
            curr["close"] < curr["open"]
            and curr["open"] >= prev["close"]
            and curr["close"] <= prev["open"]
            and curr["volume"] > prev["volume"]
        )
        return (curr["close"] < curr["open"] and wick >= body * self.wick_body_ratio) or engulfing

    def scan_entry_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> StrategyDecision:
        if self.precomputed_htf_df is None:
            self.precomputed_htf_df = self._precompute_htf_states(backtester.get_timeframe_df(self.htf))

        state_time = self.precomputed_htf_df.index.asof(curr_time)
        if pd.isna(state_time):
            return StrategyDecision()
        state = self.precomputed_htf_df.loc[state_time]
        setup = self._confluence(state, curr_time + pd.Timedelta(self.ltf))
        if setup is None:
            return StrategyDecision()

        allowed_long, allowed_short = backtester._allow_directions(
            cfg.mode,
            prev.get("bias_1d", "NONE"),
            prev.get("bias_4h", "NONE"),
            cfg.allow_long_entries,
            cfg.allow_short_entries,
        )
        side = state["trend"]
        touched = curr["low"] <= setup["high"] and curr["high"] >= setup["low"]
        confirmed = self._confirmed_rejection(side, prev, curr)
        directional_close = curr["close"] > setup["center"] if side == "LONG" else curr["close"] < setup["center"]
        if not touched or not confirmed or not directional_close:
            return StrategyDecision()
        if (side == "LONG" and not allowed_long) or (side == "SHORT" and not allowed_short):
            return StrategyDecision()

        atr = float(state["atr"])
        entry = float(setup["center"])
        if side == "LONG":
            sl = float(setup["low"]) - atr * self.zone_buffer_atr_mult
            tp1 = float(state["impulse_high"])
            tp2 = float(state["impulse_low"] + 1.272 * (state["impulse_high"] - state["impulse_low"]))
            net_sl_dist = entry - sl
        else:
            sl = float(setup["high"]) + atr * self.zone_buffer_atr_mult
            tp1 = float(state["impulse_low"])
            tp2 = float(state["impulse_high"] - 1.272 * (state["impulse_high"] - state["impulse_low"]))
            net_sl_dist = sl - entry

        execution_close = float(curr.get("execution_close", curr["close"]))
        execution_ratio = execution_close / float(curr["close"]) if curr["close"] > 0 else 1.0
        entry *= execution_ratio
        sl *= execution_ratio
        tp1 *= execution_ratio
        tp2 *= execution_ratio
        net_sl_dist = net_sl_dist * execution_ratio + (entry * backtester.config.maker_fee) + (sl * backtester.config.taker_fee)

        order, miss = backtester._build_retrace_order(
            side,
            prev,
            curr_time,
            balance,
            cfg.tp1_close_pct,
            entry,
            sl,
            tp1,
            tp2,
            net_sl_dist,
        )
        if order is not None:
            strength = "TRIPLE" if setup["triple"] else "DOUBLE"
            fib = str(setup["ratio"]).replace(".", "")
            order["entry_mode"] = f"FELISA_{side}_FIB_{fib}_{strength}"
            order["fib_ratio"] = setup["ratio"]
            order["triple_confluence"] = setup["triple"]
            return StrategyDecision(retrace_order=order)
        return StrategyDecision(missed=[miss] if miss is not None else [])
