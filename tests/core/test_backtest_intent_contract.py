import unittest

import pandas as pd

from backtest_config import BacktestConfig
from strategy_base import StrategyDecision
from strategy_engine import BACKTEST_ENGINE_CONTRACT_ID, MultiTimeframeBacktester


class RetraceIntentStrategy:
    def __init__(self):
        self.calls = []

    def signal_timeframe(self):
        return "15m"

    def scan_entry_signal(self, _backtester, _prev, _curr, curr_time, _balance, _cfg):
        self.calls.append(curr_time)
        return StrategyDecision(
            retrace_order={
                "type": "LONG",
                "entry_time": curr_time,
                "entry_price": 100.0,
                "limit_price": 100.0,
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
        )


class BacktestIntentContractTest(unittest.TestCase):
    def test_run_session_preserves_entry_intent_fill_cost_and_contract_identity(self):
        index = pd.date_range("2026-01-01", periods=98, freq="15min")
        frame = pd.DataFrame(
            {
                "open": 105.0,
                "high": 106.0,
                "low": 104.0,
                "close": 105.0,
                "volume": 1.0,
            },
            index=index,
        )
        frame.loc[index[-1], ["low", "close"]] = [89.0, 95.0]
        strategy = RetraceIntentStrategy()
        engine = object.__new__(MultiTimeframeBacktester)
        engine.config = BacktestConfig(
            initial_balance=1000.0,
            maker_fee=0.001,
            taker_fee=0.0,
            stop_loss_slippage_usd=0.0,
        )
        engine.price_scale = 1.0
        engine.has_micro_data = False
        engine.strategy = strategy
        engine._get_signal_frame = lambda: frame

        session = engine.run_session()

        self.assertEqual(session.engine_contract_id, BACKTEST_ENGINE_CONTRACT_ID)
        self.assertEqual(strategy.calls, [index[-2]])
        self.assertEqual(len(session.trades), 1)
        self.assertEqual(session.trades[0]["result"], "STOP_LOSS")
        self.assertEqual(session.trades[0]["entry_time"], index[-1])
        self.assertAlmostEqual(session.trades[0]["pnl"], -10.1)
        self.assertAlmostEqual(session.trades[0]["fee"], 0.1)
        self.assertAlmostEqual(session.balance, 989.9)


if __name__ == "__main__":
    unittest.main()
