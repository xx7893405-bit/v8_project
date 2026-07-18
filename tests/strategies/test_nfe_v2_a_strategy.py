import unittest
from unittest.mock import patch

import pandas as pd

from nfe_v2_a_strategy import NFEV2AStrategy
from nfe_v2_strategy import NFEV2Strategy
from strategy_base import StrategyDecision


class BacktesterStub:
    @staticmethod
    def _record_missed(trade_type, event_time, reason, **extra):
        return {"type": trade_type, "time": event_time, "reason": reason, **extra}


class NFEV2AStrategyTest(unittest.TestCase):
    def setUp(self):
        self.strategy = NFEV2AStrategy()
        self.backtester = BacktesterStub()
        self.signal_time = pd.Timestamp("2026-01-01 00:00:00")
        self.order = {
            "type": "LONG",
            "entry_price": 100.0,
            "sl": 90.0,
            "size": 1.0,
            "live_tp2": None,
        }
        self.bar = pd.Series({"high": 110.0, "low": 95.0})

    def scan(self, curr_time, bar=None, strategy=None, backtester=None):
        return (strategy or self.strategy).scan_entry_signal(
            backtester or self.backtester,
            pd.Series(dtype=float),
            self.bar if bar is None else bar,
            curr_time,
            10_000.0,
            object(),
        )

    def create_delayed_setup(self, strategy=None, backtester=None):
        with patch.object(
            NFEV2Strategy,
            "scan_entry_signal",
            return_value=StrategyDecision(retrace_order=self.order.copy()),
        ):
            return self.scan(self.signal_time, strategy=strategy, backtester=backtester)

    def test_release_is_90_minutes_after_signal_bar_close(self):
        self.create_delayed_setup()

        self.assertIsNone(self.scan(self.signal_time + pd.Timedelta("94m")).retrace_order)
        decision = self.scan(self.signal_time + pd.Timedelta("95m"))

        self.assertEqual(decision.retrace_order["signal_time"], self.signal_time)
        self.assertIsNone(self.strategy._delayed_setup)

    def test_stop_cross_during_wait_cancels_setup(self):
        self.create_delayed_setup()

        decision = self.scan(
            self.signal_time + pd.Timedelta("30m"),
            pd.Series({"high": 100.0, "low": 89.0}),
        )

        self.assertIsNone(decision.retrace_order)
        self.assertEqual(decision.missed[0]["reason"], "A_DELAY_STOP_INVALIDATED")

    def test_stop_cross_on_release_bar_invalidates_before_release(self):
        self.create_delayed_setup()

        decision = self.scan(
            self.signal_time + pd.Timedelta("95m"),
            pd.Series({"high": 100.0, "low": 89.0}),
        )

        self.assertIsNone(decision.retrace_order)
        self.assertEqual(decision.missed[0]["reason"], "A_DELAY_STOP_INVALIDATED")

    def test_nan_execution_extreme_falls_back_to_signal_market(self):
        self.create_delayed_setup()

        decision = self.scan(
            self.signal_time + pd.Timedelta("30m"),
            pd.Series({"high": 100.0, "low": 89.0, "execution_high": float("nan"), "execution_low": float("nan")}),
        )

        self.assertEqual(decision.missed[0]["reason"], "A_DELAY_STOP_INVALIDATED")

    def test_future_rows_do_not_change_historical_release(self):
        first = NFEV2AStrategy()
        second = NFEV2AStrategy()
        first_feed = BacktesterStub()
        second_feed = BacktesterStub()
        second_feed.future_rows = pd.DataFrame({"high": [999.0], "low": [1.0]}, index=[self.signal_time + pd.Timedelta("1d")])
        self.create_delayed_setup(first, first_feed)
        self.create_delayed_setup(second, second_feed)

        first_decision = self.scan(self.signal_time + pd.Timedelta("95m"), strategy=first, backtester=first_feed)
        second_decision = self.scan(self.signal_time + pd.Timedelta("95m"), strategy=second, backtester=second_feed)

        self.assertEqual(first_decision.retrace_order, second_decision.retrace_order)

    def test_defaults_and_current_strategy_contract_are_preserved(self):
        self.assertEqual(self.strategy.signal_timeframe(), "5m")
        self.assertEqual(self.strategy.entry_delay, pd.Timedelta("90m"))
        self.assertEqual(self.strategy.min_stop_pct, 0.0)
        self.assertFalse(self.strategy.invalidate_target_during_delay)
        self.assertEqual(self.strategy.stop_too_tight_count, 0)
        self.assertEqual(self.strategy.delay_target_invalidated_count, 0)
        self.create_delayed_setup()
        decision = self.scan(self.signal_time + pd.Timedelta("95m"))
        self.assertIsNone(decision.retrace_order["live_tp2"])
        self.assertTrue(callable(self.strategy.after_manage_position))

    def test_stop_gate_rejects_tight_long_and_accepts_threshold_boundary(self):
        strategy = NFEV2AStrategy(min_stop_pct=0.001)
        self.order.update(sl=99.91)

        decision = self.create_delayed_setup(strategy)

        self.assertEqual(decision.missed[0]["reason"], "A_STOP_TOO_TIGHT")
        self.assertEqual(strategy.stop_too_tight_count, 1)
        self.assertIsNone(strategy._delayed_setup)

        self.order.update(sl=99.9)
        decision = self.create_delayed_setup(strategy)
        self.assertEqual(decision.missed, [])
        self.assertIsNotNone(strategy._delayed_setup)

    def test_stop_gate_rejects_tight_short_and_accepts_threshold_boundary(self):
        strategy = NFEV2AStrategy(min_stop_pct=0.001)
        self.order.update(type="SHORT", sl=100.09)

        decision = self.create_delayed_setup(strategy)

        self.assertEqual(decision.missed[0]["reason"], "A_STOP_TOO_TIGHT")
        self.assertEqual(strategy.stop_too_tight_count, 1)

        self.order.update(sl=100.1)
        decision = self.create_delayed_setup(strategy)
        self.assertEqual(decision.missed, [])
        self.assertIsNotNone(strategy._delayed_setup)

    def test_target_revalidation_cancels_long_and_short_setups(self):
        for trade_type, bar in (
            ("LONG", pd.Series({"high": 120.0, "low": 95.0})),
            ("SHORT", pd.Series({"high": 105.0, "low": 80.0})),
        ):
            with self.subTest(trade_type=trade_type):
                strategy = NFEV2AStrategy(invalidate_target_during_delay=True)
                self.order.update(
                    type=trade_type,
                    sl=90.0 if trade_type == "LONG" else 110.0,
                    tp1=120.0 if trade_type == "LONG" else 80.0,
                )
                self.create_delayed_setup(strategy)

                decision = self.scan(self.signal_time + pd.Timedelta("30m"), bar, strategy)

                self.assertEqual(decision.missed[0]["reason"], "A_DELAY_TARGET_PASSED")
                self.assertEqual(strategy.delay_target_invalidated_count, 1)
                self.assertIsNone(strategy._delayed_setup)

    def test_stop_invalidation_has_priority_when_stop_and_target_touch_same_bar(self):
        strategy = NFEV2AStrategy(invalidate_target_during_delay=True)
        self.order["tp1"] = 110.0
        self.create_delayed_setup(strategy)

        decision = self.scan(
            self.signal_time + pd.Timedelta("30m"),
            pd.Series({"high": 110.0, "low": 89.0}),
            strategy,
        )

        self.assertEqual(decision.missed[0]["reason"], "A_DELAY_STOP_INVALIDATED")
        self.assertEqual(strategy.delay_target_invalidated_count, 0)

    def test_target_revalidation_is_independent_and_preserves_release_timing(self):
        strategy = NFEV2AStrategy(invalidate_target_during_delay=True)
        self.order["tp1"] = 120.0
        self.create_delayed_setup(strategy)

        self.assertIsNone(
            self.scan(self.signal_time + pd.Timedelta("94m"), strategy=strategy).retrace_order
        )
        decision = self.scan(self.signal_time + pd.Timedelta("95m"), strategy=strategy)

        self.assertEqual(decision.retrace_order["signal_time"], self.signal_time)


if __name__ == "__main__":
    unittest.main()
