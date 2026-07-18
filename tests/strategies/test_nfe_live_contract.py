import unittest
from types import SimpleNamespace

import pandas as pd

from backtest_config import RunConfig
from nfe_strategy import NFEDoubleLevelStrategy
from nfe_v2_strategy import NFEV2Strategy
from nfe_v3_strategy import NFEV3Strategy


class Backtester:
    def __init__(self, curr_time):
        index = pd.date_range(end=curr_time, periods=60, freq="15min")
        self.df_1h = pd.DataFrame(index=[curr_time])
        self.frame = pd.DataFrame({"open": 90.0, "high": 105.0, "low": 80.0, "close": 100.0}, index=index)
        self.config = SimpleNamespace(maker_fee=0.0, taker_fee=0.0)
        self.price_scale = 1.0
        self.entry_price = None

    def get_timeframe_df(self, timeframe):
        return self.frame

    def _allow_directions(self, *args):
        return True, False

    def _build_retrace_order(self, side, prev, curr_time, balance, close_pct, entry_price, sl, tp1, tp2, risk):
        self.entry_price = entry_price
        return ({"type": side, "entry_price": entry_price, "sl": sl, "tp1": tp1, "tp2": tp2}, None)


class NFELiveContractTest(unittest.TestCase):
    def _prepare(self, strategy):
        now = pd.Timestamp("2026-01-02 12:00:00")
        strategy.precomputed_htf_df = pd.DataFrame(
            {
                "htf_long_ob_high": [90.0],
                "htf_long_ob_low": [70.0],
                "htf_target_high": [130.0],
                "htf_short_ob_high": [float("nan")],
                "htf_short_ob_low": [float("nan")],
                "htf_target_low": [float("nan")],
            },
            index=[now],
        )
        strategy._find_recent_swings_from_slice = lambda *args, **kwargs: (
            [{"high": 95.0, "ob_low": 90.0, "ob_high": 95.0}],
            [{"low": 75.0, "ob_low": 70.0, "ob_high": 80.0}],
        )
        return now, Backtester(now)

    def test_v1_defines_entry_price_before_target_math(self):
        strategy = NFEDoubleLevelStrategy(min_rr=0.1)
        now, backtester = self._prepare(strategy)
        decision = strategy.scan_entry_signal(
            backtester,
            pd.Series({"bias_1d": "NONE", "bias_4h": "NONE"}),
            pd.Series({"open": 90.0, "high": 105.0, "low": 80.0, "close": 100.0}),
            now,
            10_000.0,
            RunConfig(tp1_close_pct=0.5),
        )
        self.assertIsNotNone(decision.retrace_order)
        self.assertEqual(backtester.entry_price, 80.0)

    def test_v2_marks_sentinel_tp2_as_backtest_only(self):
        strategy = NFEV2Strategy(min_rr=0.1)
        now, backtester = self._prepare(strategy)
        decision = strategy.scan_entry_signal(
            backtester,
            pd.Series({"bias_1d": "NONE", "bias_4h": "NONE", "ATR_14": 10.0}),
            pd.Series({"open": 90.0, "high": 105.0, "low": 80.0, "close": 100.0}),
            now,
            10_000.0,
            RunConfig(tp1_close_pct=0.5),
        )
        self.assertIsNone(decision.retrace_order["live_tp2"])

    def test_v3_trailing_uses_post_manage_hook_without_engine_monkey_patch(self):
        strategy = NFEV3Strategy()
        calls = []
        strategy._update_short_trailing_stop = lambda position, backtester, curr_time: calls.append(curr_time)
        now = pd.Timestamp("2026-01-02 12:00:00")
        strategy.after_manage_position({"type": "SHORT"}, object(), now)
        strategy.after_manage_position({"type": "LONG"}, object(), now)
        self.assertEqual(calls, [now])


if __name__ == "__main__":
    unittest.main()
