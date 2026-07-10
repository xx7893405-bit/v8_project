from __future__ import annotations

from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision
from nfe_strategy import NFEDoubleLevelStrategy


class NFEV3Strategy(NFEDoubleLevelStrategy):
    """
    NFE V3 策略（多空非對稱優化版）：
    1. 多單 (LONG)：維持 V1 原版（進攻型）。
       - 採用固定 sl_padding = 20.0 價格緩衝。
       - TP2 為固定高盈虧比點位，觸及後全平。
       - 不啟用結構性移動止損。
    2. 空單 (SHORT)：採用 V2 優化版（防守型）。
       - 採用動態 ATR 止損緩衝 (0.5 × ATR_14)。
       - 取消 TP2 限制 (設為 0.01)，由結構移動止損動態追蹤。
       - 啟用結構移動止損：隨 15m 新形成的 Swing High 下移止損鎖利。
    """
    def __init__(
        self,
        *args,
        use_dynamic_sl_short: bool = True,
        sl_padding_atr_mult_short: float = 0.5,
        use_trailing_stop_short: bool = True,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.use_dynamic_sl_short = use_dynamic_sl_short
        self.sl_padding_atr_mult_short = sl_padding_atr_mult_short
        self.use_trailing_stop_short = use_trailing_stop_short

    def scan_entry_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> StrategyDecision:
        # 在初次呼叫時，為 backtester 進行猴子補丁，插入空單的結構性移動止損邏輯
        if self.use_trailing_stop_short and not hasattr(backtester, "_manage_active_position_patched"):
            original_manage = backtester._manage_active_position
            
            def patched_manage(active_position, curr_series, curr_time_val, prev_time_val, loop_index, current_balance, trades_list, run_cfg):
                # 只有空單 (SHORT) 時，才執行 V2 的結構性移動止損更新
                if active_position is not None and active_position["type"] == "SHORT":
                    self._update_short_trailing_stop(active_position, backtester, curr_time_val)
                return original_manage(active_position, curr_series, curr_time_val, prev_time_val, loop_index, current_balance, trades_list, run_cfg)
                
            backtester._manage_active_position = patched_manage
            backtester._manage_active_position_patched = True

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

        # 1. 多單部分 (LONG) - 100% 維持 V1 原版
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
                        sl = latest_ltf_sl["ob_low"] - self.sl_padding  # 固定 20.0
                        tp1 = target_high
                        tp2 = target_high + (target_high - entry_price) * 0.5  # 固定 TP2

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

        # 2. 空單部分 (SHORT) - 套用 V2 優化版
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

                        # 取得進場時的 ATR 14 用於空單動態止損
                        atr = float(prev.get("ATR_14", 0.0))
                        if self.use_dynamic_sl_short and atr > 0:
                            padding = atr * self.sl_padding_mult_for_short(atr)
                        else:
                            padding = self.sl_padding

                        entry_price = latest_ltf_sh["ob_low"]
                        sl = latest_ltf_sh["ob_high"] + padding
                        tp1 = target_low
                        tp2 = 0.01  # 移除 TP2 限制

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
                                    stop_atr = abs(order["sl"] - order["entry_price"]) / atr if atr > 0 else float("inf")
                                    if (
                                        (self.max_short_rr is not None and order["rr_potential"] > self.max_short_rr)
                                        or (self.max_short_stop_atr is not None and stop_atr > self.max_short_stop_atr)
                                    ):
                                        return StrategyDecision(
                                            missed=[
                                                backtester._record_missed(
                                                    "SHORT",
                                                    curr_time,
                                                    "SHORT_QUALITY_FILTER",
                                                    rr=order["rr_potential"],
                                                    stop_atr=stop_atr,
                                                )
                                            ]
                                        )
                                    order["entry_mode"] = "NFE_DL_SHORT"
                                    return StrategyDecision(retrace_order=order)
                                if miss is not None:
                                    return StrategyDecision(missed=[miss])

        return StrategyDecision()

    def sl_padding_mult_for_short(self, atr: float) -> float:
        return self.sl_padding_atr_mult_short

    def _update_short_trailing_stop(self, active_position: dict, backtester, curr_time: pd.Timestamp):
        """
        空單結構性移動止損：
        隨著價格下跌，若 15m 形成新的 Swing High，將止損下移至：
        new_sl = latest_ltf_sh["high"] + padding
        """
        try:
            df_ltf = backtester.get_timeframe_df(self.ltf)
            df_ltf_slice = df_ltf.loc[:curr_time]
            if len(df_ltf_slice) < 50:
                return

            prev_row = df_ltf_slice.iloc[-2]
            atr = float(prev_row.get("ATR_14", 0.0))
            if self.use_dynamic_sl_short and atr > 0:
                padding = atr * self.sl_padding_atr_mult_short
            else:
                padding = self.sl_padding

            current_sl = active_position["sl"]

            ltf_shs, ltf_sls = self._find_recent_swings_from_slice(
                df_ltf_slice,
                n=self.ltf_n,
                ob_range_type=self.ob_range_type
            )

            if ltf_shs:
                latest_sh_point = ltf_shs[-1]
                new_sl = latest_sh_point["high"] + padding
                # 止損只能往下移
                if new_sl < current_sl:
                    active_position["sl"] = new_sl
        except Exception:
            pass
