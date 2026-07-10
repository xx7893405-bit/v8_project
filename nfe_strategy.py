from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision


class NFEDoubleLevelStrategy:
    def __init__(
        self,
        htf: str = "1h",
        ltf: str = "15m",
        htf_n: int = 5,
        ltf_n: int = 3,
        ob_range_type: str = "full",
        min_rr: float = 5.0,
        sl_padding: float = 20.0,
    ):
        self.htf = htf
        self.ltf = ltf
        self.htf_n = htf_n
        self.ltf_n = ltf_n
        self.ob_range_type = ob_range_type
        self.min_rr = min_rr
        self.sl_padding = sl_padding
        self.precomputed_htf_df = None

    def signal_timeframe(self) -> str:
        return self.ltf

    def _precompute_htf_structures(self, df_htf: pd.DataFrame) -> pd.DataFrame:
        n = self.htf_n
        ob_range_type = self.ob_range_type

        highs = df_htf["high"].values
        lows = df_htf["low"].values
        opens = df_htf["open"].values
        closes = df_htf["close"].values
        times = df_htf.index

        swing_highs = []
        swing_lows = []

        for j in range(n, len(df_htf) - n):
            is_sh = True
            val_h = highs[j]
            for r in range(j - n, j):
                if highs[r] >= val_h:
                    is_sh = False
                    break
            if is_sh:
                for r in range(j + 1, j + n + 1):
                    if highs[r] >= val_h:
                        is_sh = False
                        break
            if is_sh:
                confirmed_time = times[j + n]
                if ob_range_type == "full":
                    ob_high = val_h
                    ob_low = lows[j]
                else:
                    ob_high = val_h
                    ob_low = min(opens[j], closes[j])
                swing_highs.append(
                    {
                        "idx": j,
                        "time": times[j],
                        "high": val_h,
                        "low": lows[j],
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                        "confirmed_time": confirmed_time,
                    }
                )

            is_sl = True
            val_l = lows[j]
            for r in range(j - n, j):
                if lows[r] <= val_l:
                    is_sl = False
                    break
            if is_sl:
                for r in range(j + 1, j + n + 1):
                    if lows[r] <= val_l:
                        is_sl = False
                        break
            if is_sl:
                confirmed_time = times[j + n]
                if ob_range_type == "full":
                    ob_high = highs[j]
                    ob_low = val_l
                else:
                    ob_high = max(opens[j], closes[j])
                    ob_low = val_l
                swing_lows.append(
                    {
                        "idx": j,
                        "time": times[j],
                        "high": highs[j],
                        "low": val_l,
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                        "confirmed_time": confirmed_time,
                    }
                )

        sh_by_confirmed = {}
        for sh in swing_highs:
            sh_by_confirmed.setdefault(sh["confirmed_time"], []).append(sh)

        sl_by_confirmed = {}
        for sl in swing_lows:
            sl_by_confirmed.setdefault(sl["confirmed_time"], []).append(sl)

        htf_long_ob_high = [np.nan] * len(df_htf)
        htf_long_ob_low = [np.nan] * len(df_htf)
        htf_target_high = [np.nan] * len(df_htf)

        htf_short_ob_high = [np.nan] * len(df_htf)
        htf_short_ob_low = [np.nan] * len(df_htf)
        htf_target_low = [np.nan] * len(df_htf)

        confirmed_shs = []
        confirmed_sls = []

        active_long_ob = None
        active_short_ob = None

        for idx in range(len(df_htf)):
            t = times[idx]
            c = closes[idx]
            h = highs[idx]
            l = lows[idx]

            if t in sh_by_confirmed:
                confirmed_shs.extend(sh_by_confirmed[t])
            if t in sl_by_confirmed:
                confirmed_sls.extend(sl_by_confirmed[t])

            if confirmed_shs:
                latest_sh = confirmed_shs[-1]
                if c > latest_sh["high"] and confirmed_sls:
                    latest_sl = confirmed_sls[-1]
                    active_long_ob = {
                        "ob_high": latest_sl["ob_high"],
                        "ob_low": latest_sl["ob_low"],
                        "target_high": latest_sh["high"],
                    }
            if confirmed_sls:
                latest_sl = confirmed_sls[-1]
                if c < latest_sl["low"] and confirmed_shs:
                    latest_sh = confirmed_shs[-1]
                    active_short_ob = {
                        "ob_high": latest_sh["ob_high"],
                        "ob_low": latest_sh["ob_low"],
                        "target_low": latest_sl["low"],
                    }

            if active_long_ob is not None and l < active_long_ob["ob_low"]:
                active_long_ob = None
            if active_short_ob is not None and h > active_short_ob["ob_high"]:
                active_short_ob = None

            if active_long_ob is not None:
                htf_long_ob_high[idx] = active_long_ob["ob_high"]
                htf_long_ob_low[idx] = active_long_ob["ob_low"]
                htf_target_high[idx] = active_long_ob["target_high"]

            if active_short_ob is not None:
                htf_short_ob_high[idx] = active_short_ob["ob_high"]
                htf_short_ob_low[idx] = active_short_ob["ob_low"]
                htf_target_low[idx] = active_short_ob["target_low"]

        df_res = pd.DataFrame(index=df_htf.index)
        df_res["htf_long_ob_high"] = htf_long_ob_high
        df_res["htf_long_ob_low"] = htf_long_ob_low
        df_res["htf_target_high"] = htf_target_high
        df_res["htf_short_ob_high"] = htf_short_ob_high
        df_res["htf_short_ob_low"] = htf_short_ob_low
        df_res["htf_target_low"] = htf_target_low

        return df_res

    def _find_recent_swings_from_slice(
        self,
        df_slice: pd.DataFrame,
        n: int = 3,
        ob_range_type: str = "full",
    ) -> Tuple[List[dict], List[dict]]:
        window_df = df_slice.tail(200)
        highs = window_df["high"].values
        lows = window_df["low"].values
        opens = window_df["open"].values
        closes = window_df["close"].values
        times = window_df.index

        swing_highs = []
        swing_lows = []

        limit = len(window_df) - n
        for i in range(n, limit):
            is_sh = True
            val_h = highs[i]
            for r in range(i - n, i):
                if highs[r] >= val_h:
                    is_sh = False
                    break
            if is_sh:
                for r in range(i + 1, i + n + 1):
                    if highs[r] >= val_h:
                        is_sh = False
                        break
            if is_sh:
                if ob_range_type == "full":
                    ob_high = val_h
                    ob_low = lows[i]
                else:
                    ob_high = val_h
                    ob_low = min(opens[i], closes[i])
                swing_highs.append(
                    {
                        "time": times[i],
                        "high": val_h,
                        "low": lows[i],
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                    }
                )

            is_sl = True
            val_l = lows[i]
            for r in range(i - n, i):
                if lows[r] <= val_l:
                    is_sl = False
                    break
            if is_sl:
                for r in range(i + 1, i + n + 1):
                    if lows[r] <= val_l:
                        is_sl = False
                        break
            if is_sl:
                if ob_range_type == "full":
                    ob_high = highs[i]
                    ob_low = val_l
                else:
                    ob_high = max(opens[i], closes[i])
                    ob_low = val_l
                swing_lows.append(
                    {
                        "time": times[i],
                        "high": highs[i],
                        "low": val_l,
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                    }
                )
        return swing_highs, swing_lows

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
            if self.htf == "1h":
                df_htf = backtester.df_1h
            elif self.htf == "4h":
                df_htf = backtester.df_4h
            else:
                raise ValueError(f"不支援的大級別: {self.htf}")
            self.precomputed_htf_df = self._precompute_htf_structures(df_htf)

        htf_idx = self.precomputed_htf_df.index.asof(curr_time)
        if pd.isna(htf_idx):
            return StrategyDecision()

        htf_state = self.precomputed_htf_df.loc[htf_idx]

        allowed_long, allowed_short = backtester._allow_directions(
            cfg.mode,
            prev.get("bias_1d", "NONE"),
            prev.get("bias_4h", "NONE"),
            cfg.allow_long_entries,
            cfg.allow_short_entries,
        )

        df_ltf = backtester.get_timeframe_df(self.ltf)
        df_ltf_slice = df_ltf.loc[:curr_time]
        if len(df_ltf_slice) < 50:
            return StrategyDecision()

        ltf_close = curr["close"]
        execution_close = curr.get("execution_close", ltf_close)
        execution_ratio = (
            float(execution_close) / float(ltf_close)
            if pd.notna(execution_close) and pd.notna(ltf_close) and float(ltf_close) > 0
            else 1.0
        )

        long_ob_high = htf_state["htf_long_ob_high"]
        long_ob_low = htf_state["htf_long_ob_low"]
        target_high = htf_state["htf_target_high"]

        if allowed_long and pd.notna(long_ob_high) and pd.notna(long_ob_low):
            if curr["low"] <= long_ob_high and curr["close"] >= long_ob_low:
                ltf_shs, ltf_sls = self._find_recent_swings_from_slice(
                    df_ltf_slice,
                    n=self.ltf_n,
                    ob_range_type=self.ob_range_type,
                )
                if ltf_shs and ltf_sls:
                    latest_ltf_sh = ltf_shs[-1]
                    if ltf_close > latest_ltf_sh["high"]:
                        latest_ltf_sl = ltf_sls[-1]

                        entry_price = latest_ltf_sl["ob_high"]
                        sl = latest_ltf_sl["ob_low"] - self.sl_padding
                        tp1 = target_high
                        tp2 = target_high + (target_high - entry_price) * 0.5

                        # Signal structures are measured on spot. Shift executable
                        # price levels by the current perp/spot basis when dual data
                        # is present, while preserving their relative geometry.
                        entry_price *= execution_ratio
                        sl *= execution_ratio
                        tp1 *= execution_ratio
                        tp2 *= execution_ratio

                        expected_fee_drag = (entry_price * backtester.config.maker_fee) + (
                            sl * backtester.config.taker_fee
                        )
                        net_sl_dist = (entry_price - sl) + expected_fee_drag

                        if net_sl_dist > 0:
                            r_ratio = (tp1 - entry_price) / net_sl_dist
                            if r_ratio >= self.min_rr:
                                order, miss = backtester._build_retrace_order(
                                    "LONG",
                                    prev,
                                    curr_time,
                                    balance,
                                    cfg.tp1_close_pct,
                                    entry_price,
                                    sl,
                                    tp1,
                                    tp2,
                                    net_sl_dist,
                                )
                                if order is not None:
                                    order["entry_mode"] = "NFE_DL_LONG"
                                    return StrategyDecision(retrace_order=order)
                                if miss is not None:
                                    return StrategyDecision(missed=[miss])

        short_ob_high = htf_state["htf_short_ob_high"]
        short_ob_low = htf_state["htf_short_ob_low"]
        target_low = htf_state["htf_target_low"]

        if allowed_short and pd.notna(short_ob_high) and pd.notna(short_ob_low):
            if curr["high"] >= short_ob_low and curr["close"] <= short_ob_high:
                ltf_shs, ltf_sls = self._find_recent_swings_from_slice(
                    df_ltf_slice,
                    n=self.ltf_n,
                    ob_range_type=self.ob_range_type,
                )
                if ltf_shs and ltf_sls:
                    latest_ltf_sl = ltf_sls[-1]
                    if ltf_close < latest_ltf_sl["low"]:
                        latest_ltf_sh = ltf_shs[-1]

                        entry_price = latest_ltf_sh["ob_low"]
                        sl = latest_ltf_sh["ob_high"] + self.sl_padding
                        tp1 = target_low
                        tp2 = target_low - (entry_price - target_low) * 0.5

                        entry_price *= execution_ratio
                        sl *= execution_ratio
                        tp1 *= execution_ratio
                        tp2 *= execution_ratio

                        expected_fee_drag = (entry_price * backtester.config.maker_fee) + (
                            sl * backtester.config.taker_fee
                        )
                        net_sl_dist = (sl - entry_price) + expected_fee_drag

                        if net_sl_dist > 0:
                            r_ratio = (entry_price - tp1) / net_sl_dist
                            if r_ratio >= self.min_rr:
                                order, miss = backtester._build_retrace_order(
                                    "SHORT",
                                    prev,
                                    curr_time,
                                    balance,
                                    cfg.tp1_close_pct,
                                    entry_price,
                                    sl,
                                    tp1,
                                    tp2,
                                    net_sl_dist,
                                )
                                if order is not None:
                                    order["entry_mode"] = "NFE_DL_SHORT"
                                    return StrategyDecision(retrace_order=order)
                                if miss is not None:
                                    return StrategyDecision(missed=[miss])

        return StrategyDecision()
