from __future__ import annotations

from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision
from nfe_strategy import NFEDoubleLevelStrategy


class NFEV4Strategy(NFEDoubleLevelStrategy):
    """
    NFE V4 策略（市場狀態自適應版）：
    依據進場當下的 4H 大級別趨勢方向 (bias_4h) 自動切換進攻與防守模式。
    
    1. 順勢單 (多單且 4H==LONG / 空單且 4H==SHORT) ➔ 切換至【V1 進攻型模式】
       - 止損緩衝：固定 20.0 價格點數，博取極窄止損與大下單量。
       - 止盈：固定高盈虧比 TP2，觸及全平，最大化牛市主升浪獲利。
       - 移動防守：不啟用結構性移動止損。
       
    2. 逆勢/震盪單 (多單且 4H!=LONG / 空單且 4H!=SHORT) ➔ 切換至【V2 防守型模式】
       - 止損緩衝：動態 0.6 × ATR_14 寬防守，防插針。
       - 止盈：取消 TP2 限制 (多單 9999999 / 空單 0.01)，交給結構移損。
       - 移動防守：啟用結構性移動止損，隨 15m 新形成的結構低/高點動態移防，見好就收。
    """
    def __init__(
        self,
        *args,
        defensive_atr_mult: float = 0.6,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.defensive_atr_mult = defensive_atr_mult

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

        bias_4h = prev.get("bias_4h", "NONE")
        atr = float(prev.get("ATR_14", 0.0))

        long_ob_high = htf_state["htf_long_ob_high"]
        long_ob_low = htf_state["htf_long_ob_low"]
        target_high = htf_state["htf_target_high"]

        # 多單部分 (LONG)
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
                        
                        # 判斷是否為多單順勢 (4H 為 LONG)
                        is_long_trend = (bias_4h == "LONG")
                        
                        scale = getattr(backtester, "price_scale", 1.0)
                        if is_long_trend:
                            # 順勢 ➔ V1 進攻型
                            padding = self.sl_padding * scale
                            tp1 = target_high
                            tp2 = target_high + (target_high - entry_price) * 0.5
                            is_defensive = False
                        else:
                            # 逆勢/震盪 ➔ V2 防守型
                            padding = atr * self.defensive_atr_mult if atr > 0 else self.sl_padding * scale
                            tp1 = target_high
                            tp2 = 9999999.0  # 移除 TP2 限制
                            is_defensive = True

                        entry_price *= execution_ratio
                        sl = (latest_ltf_sl["ob_low"] - padding) * execution_ratio
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
                                    order["is_defensive"] = is_defensive
                                    return StrategyDecision(retrace_order=order)
                                if miss is not None:
                                    return StrategyDecision(missed=[miss])

        short_ob_high = htf_state["htf_short_ob_high"]
        short_ob_low = htf_state["htf_short_ob_low"]
        target_low = htf_state["htf_target_low"]

        # 空單部分 (SHORT)
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
                        
                        # 判斷是否為空單順勢 (4H 為 SHORT)
                        is_short_trend = (bias_4h == "SHORT")
                        
                        scale = getattr(backtester, "price_scale", 1.0)
                        if is_short_trend:
                            # 順勢 ➔ V1 進攻型
                            padding = self.sl_padding * scale
                            tp1 = target_low
                            tp2 = target_low - (entry_price - target_low) * 0.5
                            is_defensive = False
                        else:
                            # 逆勢/震盪 ➔ V2 防守型
                            padding = atr * self.defensive_atr_mult if atr > 0 else self.sl_padding * scale
                            tp1 = target_low
                            tp2 = 0.01  # 移除 TP2 限制
                            is_defensive = True

                        entry_price *= execution_ratio
                        sl = (latest_ltf_sh["ob_high"] + padding) * execution_ratio
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
                                    order["is_defensive"] = is_defensive
                                    return StrategyDecision(retrace_order=order)
                                if miss is not None:
                                    return StrategyDecision(missed=[miss])

        return StrategyDecision()

    def after_manage_position(self, active_position, backtester, curr_time):
        if active_position.get("is_defensive", False):
            self._update_adaptive_trailing_stop(active_position, backtester, curr_time)

    def _update_adaptive_trailing_stop(self, active_position: dict, backtester, curr_time: pd.Timestamp):
        """
        防守型持倉的結構性移動止損更新邏輯
        """
        try:
            df_ltf = backtester.get_timeframe_df(self.ltf)
            df_ltf_slice = df_ltf.loc[:curr_time]
            if len(df_ltf_slice) < 50:
                return

            prev_row = df_ltf_slice.iloc[-2]
            atr = float(prev_row.get("ATR_14", 0.0))
            scale = getattr(backtester, "price_scale", 1.0)
            padding = atr * self.defensive_atr_mult if atr > 0 else self.sl_padding * scale

            pos_type = active_position["type"]
            current_sl = active_position["sl"]

            ltf_shs, ltf_sls = self._find_recent_swings_from_slice(
                df_ltf_slice,
                n=self.ltf_n,
                ob_range_type=self.ob_range_type
            )

            if pos_type == "LONG" and ltf_sls:
                latest_sl_point = ltf_sls[-1]
                new_sl = latest_sl_point["low"] - padding
                if new_sl > current_sl:
                    active_position["sl"] = new_sl

            elif pos_type == "SHORT" and ltf_shs:
                latest_sh_point = ltf_shs[-1]
                new_sl = latest_sh_point["high"] + padding
                if new_sl < current_sl:
                    active_position["sl"] = new_sl
        except Exception:
            pass
