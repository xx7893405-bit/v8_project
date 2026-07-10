from __future__ import annotations

from typing import Tuple

from nfe_strategy import NFEDoubleLevelStrategy
from strategy_base import BacktestStrategy, StrategyDecision
from v8_strategy import V8FvgOverlapStrategy


def build_default_strategy_components() -> Tuple[BacktestStrategy, ...]:
    return (V8FvgOverlapStrategy(), NFEDoubleLevelStrategy())
