from __future__ import annotations

from typing import Optional

import pandas as pd

from backtest_config import RunConfig
from nfe_v2_strategy import NFEV2Strategy
from strategy_base import StrategyDecision


class NFEV2AStrategy(NFEV2Strategy):
    """NFE V2 using 5m signals released 90 minutes after signal-bar close."""

    def __init__(self, *args, ltf: str = "5m", entry_delay: str = "90m", **kwargs):
        super().__init__(*args, ltf=ltf, **kwargs)
        self.entry_delay = pd.Timedelta(entry_delay)
        if self.entry_delay < pd.Timedelta(0):
            raise ValueError("entry_delay cannot be negative")
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
            if curr_time >= self._delayed_setup["release_at"]:
                self._delayed_setup = None
                return StrategyDecision(retrace_order=order)
            return StrategyDecision()

        decision = super().scan_entry_signal(backtester, prev, curr, curr_time, balance, cfg)
        if decision.retrace_order is None:
            return decision

        decision.retrace_order.setdefault("signal_time", curr_time)
        self._delayed_setup = {
            "order": decision.retrace_order,
            "release_at": curr_time + pd.Timedelta(self.ltf) + self.entry_delay,
        }
        return StrategyDecision(missed=decision.missed)
