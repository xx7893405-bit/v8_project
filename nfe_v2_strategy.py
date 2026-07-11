from __future__ import annotations

from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest_config import RunConfig
from strategy_base import StrategyDecision
from nfe_strategy import NFEDoubleLevelStrategy


class NFEV2Strategy(NFEDoubleLevelStrategy):
    """
    NFE V2 策略：
    1. 採用動態 ATR 止損緩衝 (sl_padding_atr_mult = 0.5)。
    2. 取消 TP2 硬性全平限制，改為無限持有直到移動止損被觸發。
    3. 實作「結構性移動止損 (Trailing Stop)」：止損會隨著小級別 (15m) 新形成的 Swing 結構動態上移(多單)或下移(空單)。
    """
    def __init__(
        self,
        *args,
        use_dynamic_sl: bool = True,
        sl_padding_atr_mult: float = 0.5,
        use_trailing_stop: bool = True,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.use_dynamic_sl = use_dynamic_sl
        self.sl_padding_atr_mult = sl_padding_atr_mult
        self.use_trailing_stop = use_trailing_stop

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

        # 取得進場時的 ATR 14 用於動態止損
        atr = float(prev.get("ATR_14", 0.0))
        if self.use_dynamic_sl and atr > 0:
            padding = atr * self.sl_padding_atr_mult
        else:
            padding = self.sl_padding

        long_ob_high = htf_state["htf_long_ob_high"]
        long_ob_low = htf_state["htf_long_ob_low"]
        target_high = htf_state["htf_target_high"]

        # 多單部分
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
                        sl = latest_ltf_sl["ob_low"] - padding
                        tp1 = target_high
                        
                        # 【V2 修改】移去硬性 TP2 全平限制，設為無限延伸 (9,999,999)
                        tp2 = 9999999.0

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

        # 空單部分
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
                        sl = latest_ltf_sh["ob_high"] + padding
                        tp1 = target_low
                        
                        # 【V2 修改】移去硬性 TP2 全平限制，設為無限延伸 (0.01)
                        tp2 = 0.01

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

    def before_manage_position(self, active_position, backtester, curr_time):
        if self.use_trailing_stop:
            self._update_trailing_stop(active_position, backtester, curr_time)

    def _update_trailing_stop(self, active_position: dict, backtester, curr_time: pd.Timestamp):
        """
        結構性移動止損實作：
        多單：隨著價格上移，將止損移至最新 15m Swing Low - Padding。
        空單：隨著價格下移，將止損移至最新 15m Swing High + Padding。
        """
        try:
            df_ltf = backtester.get_timeframe_df(self.ltf)
            df_ltf_slice = df_ltf.loc[:curr_time]
            if len(df_ltf_slice) < 50:
                return

            # 取得當前 ATR 用於動態 padding
            prev_row = df_ltf_slice.iloc[-2]
            atr = float(prev_row.get("ATR_14", 0.0))
            if self.use_dynamic_sl and atr > 0:
                padding = atr * self.sl_padding_atr_mult
            else:
                padding = self.sl_padding

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
                # 止損只能往上移，不能往下移
                if new_sl > current_sl:
                    active_position["sl"] = new_sl

            elif pos_type == "SHORT" and ltf_shs:
                latest_sh_point = ltf_shs[-1]
                new_sl = latest_sh_point["high"] + padding
                # 止損只能往下移，不能往上移
                if new_sl < current_sl:
                    active_position["sl"] = new_sl
        except Exception:
            # 防禦性 try-catch，確保猴子補丁在任何數據對齊錯誤下都不會崩潰回測
            pass
