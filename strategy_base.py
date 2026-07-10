from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Protocol

import pandas as pd

from backtest_config import RunConfig

if TYPE_CHECKING:
    from strategy_engine import MultiTimeframeBacktester


@dataclass
class StrategyDecision:
    retrace_order: Optional[dict] = None
    breakout_order: Optional[dict] = None
    missed: List[dict] = field(default_factory=list)


class BacktestStrategy(Protocol):
    def scan_entry_signal(
        self,
        backtester: MultiTimeframeBacktester,
        prev: pd.Series,
        curr: pd.Series,
        curr_time: pd.Timestamp,
        balance: float,
        cfg: RunConfig,
    ) -> StrategyDecision:
        ...
