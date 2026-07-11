import unittest

import pandas as pd

from backtest_config import BacktestConfig
from nfe_strategy import NFEDoubleLevelStrategy
from strategy_engine import MultiTimeframeBacktester


class MicroFeed:
    def __init__(self):
        self.window = None

    def load_micro_window(self, start, end, columns):
        self.window = (start, end)
        return pd.DataFrame(columns=columns)


class BacktestTemporalSafetyTest(unittest.TestCase):
    def test_micro_sequence_uses_current_bar_only(self):
        engine = object.__new__(MultiTimeframeBacktester)
        engine.has_micro_data = True
        engine.data_feed = MicroFeed()
        start = pd.Timestamp("2026-01-01 03:00:00")
        end = pd.Timestamp("2026-01-01 03:15:00")
        engine._check_1m_sequence(start, end, 1, 2, True, True)
        self.assertEqual(engine.data_feed.window[0], start)
        self.assertLess(engine.data_feed.window[1], end)

    def test_one_x_notional_is_capped_by_balance(self):
        engine = object.__new__(MultiTimeframeBacktester)
        engine.config = BacktestConfig(leverage=1.0)
        self.assertEqual(engine._cap_size_by_leverage(2.0, 100.0, 100.0), 1.0)

    def test_effective_leverage_never_exceeds_the_cap(self):
        engine = object.__new__(MultiTimeframeBacktester)
        engine.config = BacktestConfig(leverage=1000.0)
        self.assertEqual(engine._effective_leverage(80_000.0, 10_000.0), 8.0)
        self.assertEqual(engine._effective_leverage(15_000_000.0, 10_000.0), 1000.0)

    def test_signal_bar_end_matches_strategy_timeframe(self):
        engine = object.__new__(MultiTimeframeBacktester)
        engine.strategy = NFEDoubleLevelStrategy(ltf="15m")
        self.assertEqual(
            engine._signal_bar_end_time(pd.Timestamp("2026-01-01 03:00:00")),
            pd.Timestamp("2026-01-01 03:15:00"),
        )


if __name__ == "__main__":
    unittest.main()
