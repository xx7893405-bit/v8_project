import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import run_live_trading
from execution_engine import ExecutionResult


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


if __name__ == "__main__":
    unittest.main()
