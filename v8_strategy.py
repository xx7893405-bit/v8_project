from __future__ import annotations

from typing import List, Optional

import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision


class V8FvgOverlapStrategy:
    def scan_entry_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> StrategyDecision:
        missed: List[dict] = []
        selected_exit_model = backtester._select_exit_model(prev, cfg)
        if selected_exit_model is None:
            return StrategyDecision(missed=missed)

        allowed_long, allowed_short = backtester._allow_directions(
            cfg.mode,
            prev["bias_1d"],
            prev["bias_4h"],
            cfg.allow_long_entries,
            cfg.allow_short_entries,
        )
        allow_retrace_entry = cfg.entry_policy in {"hybrid", "retrace_only"}
        allow_breakout_entry = cfg.enable_breakout_entry and cfg.entry_policy in {"hybrid", "breakout_only"}

        long_decision = self._scan_long_signal(
            backtester,
            prev,
            curr,
            curr_time,
            balance,
            cfg,
            selected_exit_model,
            allowed_long,
            allow_retrace_entry,
            allow_breakout_entry,
        )
        if long_decision is not None:
            return long_decision

        short_decision = self._scan_short_signal(
            backtester,
            prev,
            curr,
            curr_time,
            balance,
            cfg,
            selected_exit_model,
            allowed_short,
            allow_retrace_entry,
            allow_breakout_entry,
        )
        if short_decision is not None:
            return short_decision

        return StrategyDecision(missed=missed)

    def _scan_long_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
        selected_exit_model: str,
        allowed_long: bool,
        allow_retrace_entry: bool,
        allow_breakout_entry: bool,
    ) -> Optional[StrategyDecision]:
        if not allowed_long:
            return None
        if not prev["is_fvg_overlap_long"] or pd.isna(prev["long_overlap_top"]) or pd.isna(prev["long_overlap_bottom"]):
            return None

        vwap_long_ok = (not cfg.use_vwap_direction_filter) or (prev["close"] > prev["VWAP"])
        if not vwap_long_ok or prev["local_bias"] != "LONG":
            return None

        overlap_height = prev["long_overlap_top"] - prev["long_overlap_bottom"]
        limit_p = prev["long_overlap_top"] - (overlap_height * backtester.config.entry_buffer_pct)
        vwap_sd_padding = max(prev["VWAP_SD"], 80.0) if pd.notna(prev["VWAP_SD"]) else 80.0
        tp2_extension_sd_mult = backtester._dynamic_tp2_extension_sd_mult(prev)

        if allow_retrace_entry:
            entry_price = limit_p
            sl = round(entry_price - (vwap_sd_padding * backtester.config.sl_sd_mult), 2)
            tp1 = round(prev["VWAP_1.0_SD_Upper"], 2)
            tp2 = round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * tp2_extension_sd_mult, 2)
            expected_fee_drag = (entry_price * backtester.config.maker_fee) + (sl * backtester.config.taker_fee)
            net_sl_dist = (entry_price - sl) + expected_fee_drag
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
            decision = StrategyDecision(missed=[miss] if miss is not None else [])
            if order is not None:
                decision.retrace_order = order
            return decision

        if allow_breakout_entry and curr["close"] > prev["high"]:
            return StrategyDecision(
                breakout_order={
                    "type": "LONG",
                    "created_idx": None,
                    "signal_time": curr_time,
                    "exit_model": selected_exit_model,
                    "vwap_sd_padding": vwap_sd_padding,
                    "tp1": round(prev["VWAP_1.0_SD_Upper"], 2),
                    "tp2": round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * tp2_extension_sd_mult, 2),
                    "structure_sl": prev["long_overlap_bottom"],
                    "atr": prev["ATR_14"],
                    "volume_cap": curr["volume"] * backtester.config.max_vol_pct,
                }
            )
        return None

    def _scan_short_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
        selected_exit_model: str,
        allowed_short: bool,
        allow_retrace_entry: bool,
        allow_breakout_entry: bool,
    ) -> Optional[StrategyDecision]:
        if not allowed_short:
            return None
        if not prev["is_fvg_overlap_short"] or pd.isna(prev["short_overlap_bottom"]) or pd.isna(prev["short_overlap_top"]):
            return None

        vwap_short_ok = (not cfg.use_vwap_direction_filter) or (prev["close"] < prev["VWAP"])
        if not vwap_short_ok or prev["local_bias"] != "SHORT":
            return None

        overlap_height = prev["short_overlap_top"] - prev["short_overlap_bottom"]
        limit_p = prev["short_overlap_bottom"] + (overlap_height * backtester.config.entry_buffer_pct)
        vwap_sd_padding = max(prev["VWAP_SD"], 80.0) if pd.notna(prev["VWAP_SD"]) else 80.0
        tp2_extension_sd_mult = backtester._dynamic_tp2_extension_sd_mult(prev)

        if allow_retrace_entry:
            entry_price = limit_p
            sl = round(entry_price + (vwap_sd_padding * backtester.config.sl_sd_mult), 2)
            tp1 = round(prev["VWAP_1.0_SD_Lower"], 2)
            tp2 = round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * tp2_extension_sd_mult, 2)
            expected_fee_drag = (entry_price * backtester.config.maker_fee) + (sl * backtester.config.taker_fee)
            net_sl_dist = (sl - entry_price) + expected_fee_drag
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
            decision = StrategyDecision(missed=[miss] if miss is not None else [])
            if order is not None:
                decision.retrace_order = order
            return decision

        if allow_breakout_entry and curr["close"] < prev["low"]:
            return StrategyDecision(
                breakout_order={
                    "type": "SHORT",
                    "created_idx": None,
                    "signal_time": curr_time,
                    "exit_model": selected_exit_model,
                    "vwap_sd_padding": vwap_sd_padding,
                    "tp1": round(prev["VWAP_1.0_SD_Lower"], 2),
                    "tp2": round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * tp2_extension_sd_mult, 2),
                    "structure_sl": prev["short_overlap_top"],
                    "atr": prev["ATR_14"],
                    "volume_cap": curr["volume"] * backtester.config.max_vol_pct,
                }
            )
        return None
