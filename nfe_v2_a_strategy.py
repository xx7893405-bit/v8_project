from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from backtest_config import RunConfig
from nfe_v2_strategy import NFEV2Strategy
from strategy_base import StrategyDecision


class NFEV2AStrategy(NFEV2Strategy):
    """NFE V2 using 5m signals released 90 minutes after signal-bar close."""

    def __init__(
        self,
        *args,
        ltf: str = "5m",
        entry_delay: str = "90m",
        min_stop_pct: float = 0.0,
        invalidate_target_during_delay: bool = False,
        **kwargs,
    ):
        super().__init__(*args, ltf=ltf, **kwargs)
        self.entry_delay = pd.Timedelta(entry_delay)
        if self.entry_delay < pd.Timedelta(0):
            raise ValueError("entry_delay cannot be negative")
        if min_stop_pct < 0:
            raise ValueError("min_stop_pct cannot be negative")
        self.min_stop_pct = float(min_stop_pct)
        self.invalidate_target_during_delay = invalidate_target_during_delay
        self.stop_too_tight_count = 0
        self.delay_target_invalidated_count = 0
        self._delayed_setup: Optional[dict] = None

    @staticmethod
    def _execution_extreme(curr: pd.Series, column: str) -> float:
        execution_value = curr.get(f"execution_{column}")
        return float(execution_value) if pd.notna(execution_value) else float(curr[column])

    def scan_entry_signal(
        self,
        backtester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> StrategyDecision:
        if self._delayed_setup is not None:
            order = self._delayed_setup["order"]
            high = self._execution_extreme(curr, "high")
            low = self._execution_extreme(curr, "low")
            invalidated = low <= order["sl"] if order["type"] == "LONG" else high >= order["sl"]
            if invalidated:
                self._delayed_setup = None
                return StrategyDecision(
                    missed=[
                        backtester._record_missed(
                            order["type"],
                            curr_time,
                            "A_DELAY_STOP_INVALIDATED",
                            signal_time=order["signal_time"],
                            entry_price=order["entry_price"],
                            sl=order["sl"],
                        )
                    ]
                )
            if self.invalidate_target_during_delay and (
                high >= order["tp1"] if order["type"] == "LONG" else low <= order["tp1"]
            ):
                self._delayed_setup = None
                self.delay_target_invalidated_count += 1
                return StrategyDecision(
                    missed=[
                        backtester._record_missed(
                            order["type"],
                            curr_time,
                            "A_DELAY_TARGET_PASSED",
                            signal_time=order["signal_time"],
                            entry_price=order["entry_price"],
                            tp1=order["tp1"],
                        )
                    ]
                )
            if curr_time >= self._delayed_setup["release_at"]:
                self._delayed_setup = None
                return StrategyDecision(retrace_order=order)
            return StrategyDecision()

        decision = super().scan_entry_signal(backtester, prev, curr, curr_time, balance, cfg)
        if decision.retrace_order is None:
            return decision

        decision.retrace_order.setdefault("signal_time", curr_time)
        order = decision.retrace_order
        stop_pct = abs(order["entry_price"] - order["sl"]) / order["entry_price"]
        if stop_pct < self.min_stop_pct and not math.isclose(
            stop_pct, self.min_stop_pct, rel_tol=1e-12, abs_tol=1e-15
        ):
            self.stop_too_tight_count += 1
            return StrategyDecision(
                missed=decision.missed
                + [
                    backtester._record_missed(
                        order["type"],
                        curr_time,
                        "A_STOP_TOO_TIGHT",
                        signal_time=order["signal_time"],
                        entry_price=order["entry_price"],
                        sl=order["sl"],
                        stop_pct=stop_pct,
                    )
                ]
            )
        self._delayed_setup = {
            "order": order,
            "release_at": curr_time + pd.Timedelta(self.ltf) + self.entry_delay,
        }
        return StrategyDecision(missed=decision.missed)
