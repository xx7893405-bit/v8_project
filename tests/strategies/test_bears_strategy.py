import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest_config import RunConfig
from bears_strategy import BearSStrategy


class BacktesterStub:
    def __init__(self, curr_time):
        self.config = SimpleNamespace(maker_fee=0.0, taker_fee=0.0)
        self.htf = pd.DataFrame(index=[curr_time])
        self.build_calls = 0

    def get_timeframe_df(self, timeframe):
        return self.htf

    @staticmethod
    def _allow_directions(*args):
        return True, True

    def _build_retrace_order(self, side, prev, curr_time, balance, close_pct, entry, sl, tp1, tp2, risk):
        self.build_calls += 1
        return ({"type": side, "entry_price": entry, "sl": sl, "tp1": tp1, "tp2": tp2}, None)


class BearSStrategyTest(unittest.TestCase):
    def _scan_setup(self, strategy, ratio=0.5, triple=True, curr=None):
        now = pd.Timestamp("2026-01-02 12:00:00")
        backtester = BacktesterStub(now)
        strategy.precomputed_htf_df = pd.DataFrame(
            {
                "trend": ["LONG"],
                "atr": [10.0],
                "impulse_low": [80.0],
                "impulse_high": [120.0],
            },
            index=[now],
        )
        strategy._confluence = lambda state, at_time: {
            "ratio": ratio,
            "center": 100.0,
            "low": 98.0,
            "high": 102.0,
            "triple": triple,
        }
        strategy._confirmed_rejection = lambda side, prev, bar: True
        prev = pd.Series({"bias_1d": "NONE", "bias_4h": "NONE"})
        bar = curr if curr is not None else pd.Series({"open": 99.0, "high": 103.0, "low": 97.0, "close": 101.0})
        decision = strategy.scan_entry_signal(backtester, prev, bar, now, 10_000.0, RunConfig())
        return decision, backtester

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

    def test_default_filters_preserve_all_fib_and_confirmation_setups(self):
        strategy = BearSStrategy()

        for ratio, triple in ((0.5, True), (0.618, False), (0.786, False)):
            decision, backtester = self._scan_setup(strategy, ratio=ratio, triple=triple)
            self.assertIsNotNone(decision.retrace_order)
            self.assertEqual(backtester.build_calls, 1)

        self.assertEqual(strategy.fib_filtered_setups, 0)
        self.assertEqual(strategy.triple_filtered_setups, 0)

    def test_fib_filter_passes_05_and_rejects_other_ratios(self):
        strategy = BearSStrategy(allowed_fib_ratios=(0.5,))

        passed, _ = self._scan_setup(strategy, ratio=0.5000000001)
        filtered_618, backtester_618 = self._scan_setup(strategy, ratio=0.618)
        filtered_786, backtester_786 = self._scan_setup(strategy, ratio=0.786)

        self.assertIsNotNone(passed.retrace_order)
        self.assertIsNone(filtered_618.retrace_order)
        self.assertIsNone(filtered_786.retrace_order)
        self.assertEqual(backtester_618.build_calls, 0)
        self.assertEqual(backtester_786.build_calls, 0)
        self.assertEqual(strategy.fib_filtered_setups, 2)

    def test_triple_filter_passes_triple_and_rejects_double(self):
        strategy = BearSStrategy(require_triple=True)

        passed, _ = self._scan_setup(strategy, triple=True)
        filtered, backtester = self._scan_setup(strategy, triple=False)

        self.assertIsNotNone(passed.retrace_order)
        self.assertIsNone(filtered.retrace_order)
        self.assertEqual(backtester.build_calls, 0)
        self.assertEqual(strategy.triple_filtered_setups, 1)

    def test_combined_filters_count_each_failed_quality_condition(self):
        strategy = BearSStrategy(allowed_fib_ratios=(0.5,), require_triple=True)

        passed, _ = self._scan_setup(strategy, ratio=0.5, triple=True)
        filtered, backtester = self._scan_setup(strategy, ratio=0.618, triple=False)

        self.assertIsNotNone(passed.retrace_order)
        self.assertIsNone(filtered.retrace_order)
        self.assertEqual(backtester.build_calls, 0)
        self.assertEqual(strategy.fib_filtered_setups, 1)
        self.assertEqual(strategy.triple_filtered_setups, 1)

    def test_filters_only_count_otherwise_valid_setups(self):
        strategy = BearSStrategy(allowed_fib_ratios=(0.5,), require_triple=True)
        invalid_bar = pd.Series({"open": 99.0, "high": 97.0, "low": 95.0, "close": 96.0})

        decision, backtester = self._scan_setup(strategy, ratio=0.618, triple=False, curr=invalid_bar)

        self.assertIsNone(decision.retrace_order)
        self.assertEqual(backtester.build_calls, 0)
        self.assertEqual(strategy.fib_filtered_setups, 0)
        self.assertEqual(strategy.triple_filtered_setups, 0)


if __name__ == "__main__":
    unittest.main()
