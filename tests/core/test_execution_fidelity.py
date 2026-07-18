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
            {"open": [100.0, 110.0], "high": [111.0, 112.0], "low": [100.0, 89.0]},
            index=pd.date_range("2026-01-01 00:00:00", periods=2, freq="1min"),
        )
        future = pd.DataFrame(
            {"open": [90.0], "high": [130.0], "low": [80.0]},
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


if __name__ == "__main__":
    unittest.main()
