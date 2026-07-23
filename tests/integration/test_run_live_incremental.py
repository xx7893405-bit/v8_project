import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import run_live_trading
from execution_engine import ExecutionResult, LiveExecutionEngine


class RunLiveIncrementalTest(unittest.TestCase):
    def test_first_run_only_bootstraps_latest_bar(self):
        latest = pd.Timestamp("2026-01-02 12:00:00")
        historical_position = {
            "type": "LONG",
            "size": 0.1,
            "entry_time": "2026-01-01 00:00:00",
            "entry_price": 100.0,
            "sl": 90.0,
            "tp1": 110.0,
            "tp2": 120.0,
        }

        class Backtester:
            def __init__(self, **kwargs):
                pass

            def _get_signal_frame(self):
                return pd.DataFrame({"close": [100.0]}, index=[latest])

            def build_runtime_snapshot(self, strategy, start_at=None, resume_snapshot=None):
                if start_at != latest:
                    raise AssertionError(f"bootstrap start {start_at!r} != {latest!r}")
                return {"as_of": str(latest), "active_position": historical_position}

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (
                patch.object(sys, "argv", ["run_live_trading.py", "--state-path", str(state_path)]),
                patch.object(run_live_trading, "ExchangeApiMarketDataFeed", Mock()),
                patch.object(run_live_trading, "MultiTimeframeBacktester", Backtester),
                patch.object(run_live_trading, "LiveExecutionEngine") as execution,
            ):
                run_live_trading.main()

            execution.assert_not_called()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["snapshot"]["as_of"], str(latest))

    def test_restart_resumes_snapshot_and_allows_only_new_entry(self):
        old_snapshot = {"as_of": "2026-01-02 12:00:00", "active_position": None}
        new_position = {
            "type": "LONG",
            "size": 0.1,
            "remaining_size": 0.1,
            "entry_time": "2026-01-02 12:15:00",
            "entry_price": 100.0,
            "sl": 90.0,
            "tp1": 110.0,
            "tp2": 120.0,
        }

        class Backtester:
            def __init__(self, **kwargs):
                pass

            def build_runtime_snapshot(self, strategy, start_at=None, resume_snapshot=None):
                if resume_snapshot != old_snapshot:
                    raise AssertionError("live restart did not resume the persisted snapshot")
                return {"as_of": "2026-01-02 12:15:00", "active_position": new_position}

        engine = Mock()
        engine.reconcile_position.return_value = (ExecutionResult(True, "OPEN"), [])
        engine.last_protection_status = {
            "protected": True,
            "covered_qty": 0.1,
            "stop_id": "stop-1",
        }
        engine.confirmed_position = {"type": "LONG", "size": 0.1}
        engine.collect_fills.return_value = ([], ["entry-1", "stop-1"])
        engine.merge_fills.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps({"snapshot": old_snapshot}), encoding="utf-8")
            with (
                patch.object(sys, "argv", ["run_live_trading.py", "--state-path", str(state_path)]),
                patch.object(run_live_trading, "ExchangeApiMarketDataFeed", Mock()),
                patch.object(run_live_trading, "MultiTimeframeBacktester", Backtester),
                patch.object(run_live_trading, "LiveExecutionEngine", return_value=engine),
            ):
                run_live_trading.main()

        self.assertTrue(engine.reconcile_position.call_args.kwargs["allow_entry"])

    def test_protection_failure_keeps_old_snapshot_and_retry_does_not_duplicate_fill(self):
        old_snapshot = {"as_of": "2026-01-02 12:00:00", "active_position": None}
        new_position = {
            "type": "LONG",
            "size": 0.4,
            "remaining_size": 0.4,
            "entry_time": "2026-01-02 12:15:00",
            "entry_price": 100.0,
            "sl": 90.0,
            "tp1": 110.0,
            "tp2": 120.0,
        }

        class Backtester:
            def __init__(self, **kwargs):
                pass

            def build_runtime_snapshot(self, strategy, start_at=None, resume_snapshot=None):
                return {"as_of": "2026-01-02 12:15:00", "active_position": new_position}

        engine = Mock()
        engine.reconcile_position.return_value = (
            ExecutionResult(True, "PARTIALLY_FILLED", exchange_order_id="entry-1", filled_quantity=0.4),
            [ExecutionResult(False, "REJECTED")],
        )
        engine.last_protection_status = {
            "protected": False,
            "covered_qty": 0.0,
            "stop_id": None,
        }
        engine.confirmed_position = {"type": "LONG", "size": 0.4}
        fill = {
            "fill_id": "trade-1",
            "order_id": "entry-1",
            "quantity": 0.4,
            "average_price": 100.0,
            "fee": 0.02,
            "fee_currency": "USDT",
            "timestamp": "2026-01-02T12:15:01+00:00",
        }
        engine.collect_fills.return_value = ([fill], ["entry-1"])
        engine.merge_fills.side_effect = LiveExecutionEngine.merge_fills
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            original = {"snapshot": old_snapshot}
            state_path.write_text(json.dumps(original), encoding="utf-8")
            for _ in range(2):
                with (
                    patch.object(sys, "argv", ["run_live_trading.py", "--state-path", str(state_path)]),
                    patch.object(run_live_trading, "ExchangeApiMarketDataFeed", Mock()),
                    patch.object(run_live_trading, "MultiTimeframeBacktester", Backtester),
                    patch.object(run_live_trading, "LiveExecutionEngine", return_value=engine),
                ):
                    run_live_trading.main()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["snapshot"], old_snapshot)
            self.assertEqual(saved["fill_ledger"], [fill])
            self.assertEqual(saved["last_execution"]["failure_statuses"], ["REJECTED"])
            self.assertFalse(saved["last_execution"]["snapshot_advanced"])

    def test_strategy_flat_persists_only_after_flat_convergence(self):
        old_position = {
            "type": "LONG",
            "size": 0.1,
            "remaining_size": 0.1,
            "live_entry_tag": "v8-entry-LONG-1",
        }
        old_snapshot = {"as_of": "2026-01-02 12:00:00", "active_position": old_position}

        class Backtester:
            def __init__(self, **kwargs):
                pass

            def build_runtime_snapshot(self, strategy, start_at=None, resume_snapshot=None):
                return {"as_of": "2026-01-02 12:15:00", "active_position": None}

        engine = Mock()
        engine.reconcile_flat.return_value = (ExecutionResult(True, "FLAT_CONVERGED"), [])
        engine.collect_fills.return_value = ([], ["close-1"])
        engine.merge_fills.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps({"snapshot": old_snapshot}), encoding="utf-8")
            with (
                patch.object(sys, "argv", ["run_live_trading.py", "--state-path", str(state_path)]),
                patch.object(run_live_trading, "ExchangeApiMarketDataFeed", Mock()),
                patch.object(run_live_trading, "MultiTimeframeBacktester", Backtester),
                patch.object(run_live_trading, "LiveExecutionEngine", return_value=engine),
            ):
                run_live_trading.main()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
        engine.reconcile_flat.assert_called_once_with(old_position)
        self.assertIsNone(saved["snapshot"]["active_position"])

    def test_flat_failure_keeps_old_snapshot_but_persists_close_fill(self):
        old_position = {
            "type": "LONG",
            "size": 0.1,
            "remaining_size": 0.1,
            "live_entry_tag": "v8-entry-LONG-1",
        }
        old_snapshot = {"as_of": "2026-01-02 12:00:00", "active_position": old_position}

        class Backtester:
            def __init__(self, **kwargs):
                pass

            def build_runtime_snapshot(self, strategy, start_at=None, resume_snapshot=None):
                return {"as_of": "2026-01-02 12:15:00", "active_position": None}

        close = ExecutionResult(
            True,
            "PARTIALLY_FILLED",
            exchange_order_id="close-1",
            filled_quantity=0.05,
            average_price=99.0,
            fee=0.01,
            timestamp="2026-01-02T12:15:01+00:00",
        )
        fill = {
            "fill_id": "order:close-1",
            "order_id": "close-1",
            "quantity": 0.05,
            "average_price": 99.0,
            "fee": 0.01,
            "fee_currency": None,
            "timestamp": "2026-01-02T12:15:01+00:00",
            "client_tag": "",
        }
        engine = Mock()
        engine.reconcile_flat.return_value = (
            ExecutionResult(False, "FLAT_NOT_CONVERGED", exchange_order_id="close-1"),
            [close],
        )
        engine.collect_fills.return_value = ([fill], ["close-1"])
        engine.merge_fills.side_effect = LiveExecutionEngine.merge_fills
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps({"snapshot": old_snapshot}), encoding="utf-8")
            with (
                patch.object(sys, "argv", ["run_live_trading.py", "--state-path", str(state_path)]),
                patch.object(run_live_trading, "ExchangeApiMarketDataFeed", Mock()),
                patch.object(run_live_trading, "MultiTimeframeBacktester", Backtester),
                patch.object(run_live_trading, "LiveExecutionEngine", return_value=engine),
            ):
                run_live_trading.main()
            saved = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["snapshot"], old_snapshot)
        self.assertEqual(saved["fill_ledger"], [fill])
        self.assertEqual(saved["last_execution"]["failure_statuses"], ["FLAT_NOT_CONVERGED"])
        self.assertEqual(saved["last_execution"]["managed_order_ids"], ["close-1"])


if __name__ == "__main__":
    unittest.main()
