import unittest

import pandas as pd

from backtest_config import BacktestConfig, RunConfig
from strategy_engine import MultiTimeframeBacktester


def position(**overrides):
    value = {
        "type": "LONG",
        "entry_idx": 0,
        "entry_time": pd.Timestamp("2026-01-01 00:00:00"),
        "entry_price": 100.0,
        "sl": 90.0,
        "tp1": 110.0,
        "tp2": 120.0,
        "size": 1.0,
        "remaining_size": 1.0,
        "entry_balance": 1000.0,
        "rr_potential": 2.0,
        "actual_risk_usd": 10.0,
        "tp1_hit": False,
        "be_active": False,
        "accumulated_funding": 0.0,
        "tp1_close_pct": 0.5,
        "realized_pnl": 0.0,
        "realized_fee": 0.0,
        "tp1_realized": False,
        "entry_mode": "RETRACE",
        "leverage": 1.0,
    }
    value.update(overrides)
    return value


class MicroFeed:
    def __init__(self, rows):
        self.rows = rows

    def load_micro_window(self, start, end, columns):
        return self.rows.loc[start:end, columns]


class ExecutionFidelityTest(unittest.TestCase):
    def engine(self, **config):
        engine = object.__new__(MultiTimeframeBacktester)
        engine.config = BacktestConfig(**config)
        engine.price_scale = 1.0
        engine.has_micro_data = False
        return engine

    def test_retrace_touching_entry_and_stop_is_filled_then_stopped(self):
        engine = self.engine(maker_fee=0.001, taker_fee=0.0, stop_loss_slippage_usd=0.0)
        order = position(limit_price=100.0, created_idx=0)
        bar = pd.Series({"open": 105.0, "high": 106.0, "low": 89.0, "close": 95.0})
        missed = []

        pending, active, balance = engine._handle_pending_retest_order(
            order, None, bar, pd.Timestamp("2026-01-01 00:15:00"), 1, 1000.0, missed
        )
        trades = []
        active, balance = engine._manage_active_position(
            active,
            bar,
            pd.Timestamp("2026-01-01 00:15:00"),
            pd.Timestamp("2026-01-01 00:30:00"),
            1,
            balance,
            trades,
            RunConfig(),
        )

        self.assertIsNone(pending)
        self.assertIsNone(active)
        self.assertEqual(missed, [])
        self.assertEqual(trades[0]["result"], "STOP_LOSS")
        self.assertAlmostEqual(trades[0]["pnl"], -10.1)
        self.assertAlmostEqual(trades[0]["fee"], 0.1)

    def test_retrace_order_expiry_records_its_stop(self):
        engine = self.engine()
        order = position(limit_price=100.0, created_idx=0)
        missed = []

        pending, active, balance = engine._handle_pending_retest_order(
            order,
            None,
            pd.Series({"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0}),
            pd.Timestamp("2026-01-02 00:00:00"),
            73,
            1000.0,
            missed,
        )

        self.assertIsNone(pending)
        self.assertIsNone(active)
        self.assertEqual(balance, 1000.0)
        self.assertEqual(missed[0]["reason"], "ORDER_EXPIRED")
        self.assertEqual(missed[0]["sl"], 90.0)

    def test_tp2_after_stop_does_not_turn_same_bar_into_full_profit(self):
        rows = pd.DataFrame(
            {
                "open": [100.0, 110.0, 90.0],
                "high": [111.0, 112.0, 121.0],
                "low": [100.0, 89.0, 88.0],
                "close": [110.0, 90.0, 120.0],
            },
            index=pd.date_range("2026-01-01 00:00:00", periods=3, freq="1min"),
        )
        engine = self.engine(maker_fee=0.0, taker_fee=0.0, stop_loss_slippage_usd=0.0)
        engine.has_micro_data = True
        engine.data_feed = MicroFeed(rows)
        trades = []

        active, _ = engine._resolve_position_event(
            position(),
            rows.index[0],
            pd.Timestamp("2026-01-01 00:15:00"),
            1000.0,
            trades,
            False,
            True,
            True,
            True,
            0.0,
            90.0,
            False,
            True,
            True,
        )

        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "STOP_LOSS")
        self.assertTrue(trades[0]["tp1_hit"])

        trades = []
        active, _ = engine._resolve_position_event(
            position(leverage=2.0),
            rows.index[0],
            pd.Timestamp("2026-01-01 00:15:00"),
            1000.0,
            trades,
            True,
            False,
            True,
            True,
            90.0,
            80.0,
            False,
            True,
            True,
        )
        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "LIQUIDATION")

    def test_time_stop_yields_to_intrabar_stop_and_market_exit_slips(self):
        engine = self.engine(max_holding_bars=1, taker_fee=0.0, slippage_usd=2.0, stop_loss_slippage_usd=0.0)
        trades = []
        active, _ = engine._manage_active_position(
            position(),
            pd.Series({"open": 100.0, "high": 105.0, "low": 89.0, "close": 101.0}),
            pd.Timestamp("2026-01-01 01:00:00"),
            pd.Timestamp("2026-01-01 01:15:00"),
            1,
            1000.0,
            trades,
            RunConfig(),
        )
        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "STOP_LOSS")

        trades = []
        active, _ = engine._manage_active_position(
            position(sl=80.0),
            pd.Series({"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0}),
            pd.Timestamp("2026-01-01 01:00:00"),
            pd.Timestamp("2026-01-01 01:15:00"),
            1,
            1000.0,
            trades,
            RunConfig(),
        )
        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "TIME_STOP")
        self.assertEqual(trades[0]["exit_price"], 99.0)

    def test_funding_uses_direction_and_remaining_size(self):
        engine = self.engine(funding_rate_8h=0.01)
        short = position(type="SHORT", size=2.0, remaining_size=0.5, sl=110.0, tp1=90.0, tp2=80.0)
        active, _ = engine._manage_active_position(
            short,
            pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}),
            pd.Timestamp("2026-01-01 08:00:00"),
            pd.Timestamp("2026-01-01 08:15:00"),
            1,
            1000.0,
            [],
            RunConfig(),
        )
        self.assertEqual(active["accumulated_funding"], -0.5)

    def test_force_close_uses_adverse_market_slippage(self):
        engine = self.engine(slippage_usd=2.0, taker_fee=0.0)
        index = pd.date_range("2026-01-01 00:00:00", periods=97, freq="15min")
        frame = pd.DataFrame(
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 1.0},
            index=index,
        )
        engine._get_signal_frame = lambda: frame
        engine.strategy = type("Strategy", (), {"signal_timeframe": lambda self: "15m"})()

        session = engine.run_session(
            resume_snapshot={"balance": 1000.0, "active_position": position(entry_idx=95)},
        )

        self.assertEqual(session.trades[0]["result"], "FORCE_CLOSE")
        self.assertEqual(session.trades[0]["exit_price"], 99.0)

    def test_current_bar_result_is_prefix_invariant(self):
        prefix = pd.DataFrame(
            {"open": [100.0, 110.0], "high": [111.0, 112.0], "low": [100.0, 89.0], "close": [110.0, 90.0]},
            index=pd.date_range("2026-01-01 00:00:00", periods=2, freq="1min"),
        )
        future = pd.DataFrame(
            {"open": [90.0], "high": [130.0], "low": [80.0], "close": [100.0]},
            index=[pd.Timestamp("2026-01-01 00:16:00")],
        )
        engine = self.engine()
        engine.has_micro_data = True
        outcomes = []
        for rows in (prefix, pd.concat([prefix, future])):
            engine.data_feed = MicroFeed(rows)
            outcomes.append(
                engine._check_1m_sequence(
                    pd.Timestamp("2026-01-01 00:00:00"),
                    pd.Timestamp("2026-01-01 00:15:00"),
                    90.0,
                    110.0,
                    True,
                    True,
                )
            )
        self.assertEqual(outcomes, ["B", "B"])

    def _fill_and_manage_retrace(self, rows):
        engine = self.engine(maker_fee=0.0, taker_fee=0.0, stop_loss_slippage_usd=0.0)
        engine.has_micro_data = True
        engine.data_feed = MicroFeed(rows)
        order = position(limit_price=100.0, created_idx=0)
        curr_time = pd.Timestamp("2026-01-01 00:00:00")
        bar_end = pd.Timestamp("2026-01-01 00:15:00")
        bar = pd.Series({"open": 105.0, "high": rows.high.max(), "low": rows.low.min(), "close": rows.close.iloc[-1]})
        _, active, balance = engine._handle_pending_retest_order(order, None, bar, curr_time, 1, 1000.0, [])
        entry_bar, management_start = engine._entry_relative_execution_bar(active, bar, curr_time, bar_end)
        trades = []
        active, balance = engine._manage_active_position(
            active, entry_bar, management_start, bar_end, 1, balance, trades, RunConfig()
        )
        return active, balance, trades

    def test_pre_entry_tp_does_not_affect_retrace(self):
        rows = pd.DataFrame(
            {
                "open": [105.0, 101.0, 102.0],
                "high": [121.0, 103.0, 105.0],
                "low": [104.0, 99.0, 101.0],
                "close": [106.0, 102.0, 104.0],
            },
            index=pd.date_range("2026-01-01", periods=3, freq="1min"),
        )
        active, _, trades = self._fill_and_manage_retrace(rows)
        self.assertIsNotNone(active)
        self.assertFalse(active["tp1_hit"])
        self.assertEqual(trades, [])

    def test_post_entry_tp_is_managed(self):
        rows = pd.DataFrame(
            {
                "open": [105.0, 101.0, 102.0],
                "high": [121.0, 103.0, 121.0],
                "low": [104.0, 99.0, 101.0],
                "close": [106.0, 102.0, 120.0],
            },
            index=pd.date_range("2026-01-01", periods=3, freq="1min"),
        )
        active, _, trades = self._fill_and_manage_retrace(rows)
        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "TAKE_PROFIT_ALL")

    def test_entry_minute_ambiguity_is_conservative(self):
        rows = pd.DataFrame(
            {"open": [105.0], "high": [121.0], "low": [89.0], "close": [100.0]},
            index=[pd.Timestamp("2026-01-01 00:00:00")],
        )
        active, _, trades = self._fill_and_manage_retrace(rows)
        self.assertIsNone(active)
        self.assertEqual(trades[0]["result"], "STOP_LOSS")

    def test_equity_events_reconcile_after_force_close(self):
        engine = self.engine(slippage_usd=0.0, taker_fee=0.0)
        index = pd.date_range("2026-01-01 00:00:00", periods=97, freq="15min")
        frame = pd.DataFrame(
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 1.0}, index=index
        )
        micro = pd.DataFrame(
            {"open": [100.0, 101.0], "high": [102.0, 103.0], "low": [99.0, 100.0], "close": [101.0, 102.0]},
            index=[index[-1], index[-1] + pd.Timedelta(minutes=1)],
        )
        engine.has_micro_data = True
        engine.data_feed = MicroFeed(micro)
        engine._get_signal_frame = lambda: frame
        engine.strategy = type("Strategy", (), {"signal_timeframe": lambda self: "15m"})()

        session = engine.run_session(resume_snapshot={"balance": 1000.0, "active_position": position(entry_idx=95)})

        self.assertTrue(any(event["mark_source"] == "micro_close" for event in session.equity_events))
        self.assertEqual(
            set(session.equity_events[-1]),
            {"time", "balance", "equity", "position_exposure", "mark_source"},
        )
        self.assertEqual(session.equity_events[-1]["mark_source"], "realized_balance")
        self.assertAlmostEqual(session.equity_events[-1]["equity"], session.balance)
        self.assertEqual(session.equity_events[-1]["position_exposure"], 0.0)


if __name__ == "__main__":
    unittest.main()
