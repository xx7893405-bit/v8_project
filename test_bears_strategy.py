import unittest

import numpy as np
import pandas as pd

from bears_strategy import BearSStrategy


class BearSStrategyTest(unittest.TestCase):
    def test_htf_state_is_delayed_and_unchanged_by_future_bars(self):
        index = pd.date_range("2026-01-01", periods=40, freq="4h")
        close = 100 + np.sin(np.arange(40) * np.pi / 3) * 10 + np.arange(40) * 0.2
        frame = pd.DataFrame(
            {
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100,
            },
            index=index,
        )
        strategy = BearSStrategy(swing_n=2)
        prefix = strategy._precompute_htf_states(frame.iloc[:30])
        full = strategy._precompute_htf_states(frame)

        self.assertEqual(prefix.index[0], index[0] + pd.Timedelta("4h"))
        pd.testing.assert_series_equal(prefix.iloc[-1], full.loc[prefix.index[-1]], check_names=False)

    def test_confluence_selects_nearest_fibonacci_level(self):
        strategy = BearSStrategy()
        state = pd.Series(
            {
                "trend": "LONG",
                "line_time": pd.Timestamp("2026-01-01"),
                "line_price": 38.2,
                "line_slope_hour": 0.0,
                "impulse_low": 0.0,
                "impulse_high": 100.0,
                "atr": 10.0,
                "sr_levels": (38.0,),
            }
        )

        setup = strategy._confluence(state, pd.Timestamp("2026-01-02"))

        self.assertIsNotNone(setup)
        self.assertEqual(setup["ratio"], 0.618)
        self.assertTrue(setup["triple"])

    def test_long_rejection_requires_bullish_close(self):
        strategy = BearSStrategy(wick_body_ratio=1.5)
        prev = pd.Series({"open": 100, "close": 101, "volume": 100})
        bullish = pd.Series({"open": 100, "high": 103, "low": 96, "close": 102, "volume": 90})
        bearish = pd.Series({"open": 102, "high": 103, "low": 96, "close": 100, "volume": 90})

        self.assertTrue(strategy._confirmed_rejection("LONG", prev, bullish))
        self.assertFalse(strategy._confirmed_rejection("LONG", prev, bearish))


if __name__ == "__main__":
    unittest.main()
