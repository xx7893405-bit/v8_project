import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nfe_strategy import NFEDoubleLevelStrategy
from nfe_v2_strategy import NFEV2Strategy
from nfe_v4_strategy import NFEV4Strategy
from oracle_strategy_job import (
    build_strategy,
    classify_decision,
    load_or_create_forward_start,
    load_or_create_forward_run,
    load_resume_snapshot,
    parse_args,
    strategy_events,
)
from v8_strategy import V8FvgOverlapStrategy


class OracleStrategyJobTest(unittest.TestCase):
    def test_strategy_selection(self):
        self.assertIsInstance(build_strategy("nfe", "1h", "15m"), NFEDoubleLevelStrategy)
        self.assertIsInstance(build_strategy("nfe-v2", "1h", "15m"), NFEV2Strategy)
        self.assertIsInstance(build_strategy("nfe-v4", "1h", "15m"), NFEV4Strategy)
        self.assertIsInstance(build_strategy("v8", "1h", "15m"), V8FvgOverlapStrategy)

    def test_decision_priority(self):
        self.assertEqual(classify_decision({"active_position": {"type": "long"}}), ("LONG", "ACTIVE_POSITION"))
        self.assertEqual(classify_decision({"pending_retest_order": {"type": "short"}}), ("SHORT", "PENDING_ORDER"))
        self.assertEqual(classify_decision({}), ("FLAT", "NO_SETUP"))

    def test_default_risk_is_five_percent(self):
        with patch.object(sys, "argv", ["oracle_strategy_job.py"]):
            self.assertEqual(parse_args().risk_pct, 0.05)

    def test_account_id_is_configurable(self):
        with patch.object(sys, "argv", ["oracle_strategy_job.py", "--account-id", "paper-002"]):
            self.assertEqual(parse_args().account_id, "paper-002")

    def test_account_name_is_configurable(self):
        with patch.object(sys, "argv", ["oracle_strategy_job.py", "--account-name", "主帳戶"]):
            self.assertEqual(parse_args().account_name, "主帳戶")

    def test_max_leverage_is_configurable(self):
        with patch.object(sys, "argv", ["oracle_strategy_job.py", "--max-leverage", "1000"]):
            self.assertEqual(parse_args().max_leverage, 1000.0)

    def test_forward_start_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.json"
            first = load_or_create_forward_start(path)
            self.assertEqual(load_or_create_forward_start(path), first)

    def test_requested_forward_start_overrides_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.json"
            actual = load_or_create_forward_start(path, "2026-07-01T00:00:00Z")
            self.assertEqual(actual, "2026-07-01T00:00:00+00:00")

    def test_forward_run_id_is_stable_until_the_start_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.json"
            start, first_run = load_or_create_forward_run(path, "2026-07-01T00:00:00Z")
            self.assertEqual(load_or_create_forward_run(path, "2026-07-01T00:00:00Z"), (start, first_run))
            self.assertNotEqual(
                load_or_create_forward_run(path, "2026-07-02T00:00:00Z")[1], first_run
            )

    def test_resume_requires_matching_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                '{"forward_start":"2026-07-01T00:00:00+00:00","snapshot":{"balance":10000}}',
                encoding="utf-8",
            )
            self.assertEqual(
                load_resume_snapshot(path, "2026-07-01T00:00:00+00:00"),
                {"balance": 10000},
            )
            self.assertIsNone(
                load_resume_snapshot(path, "2026-07-02T00:00:00+00:00")
            )

    def test_events_are_emitted_once(self):
        payload = {
            "evaluated_at": "2026-07-11T02:30:00+00:00",
            "run_id": "test-run",
            "account_id": "paper-nfe-v2",
            "strategy": "nfe-v2",
            "decision": "LONG",
            "snapshot": {"as_of": "2026-07-11 02:15:00", "balance": 10000, "active_position": {"type": "LONG", "entry_time": "2026-07-11 02:15:00"}, "trades": []},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            events = strategy_events(payload, path)
            self.assertEqual(events[0]["event_type"], "ENTRY")
            self.assertEqual(events[0]["account_id"], "paper-nfe-v2")
            self.assertEqual(events[0]["event_id"].split(":")[0], "test-run")
            path.write_text(__import__("json").dumps(events[0]) + "\n", encoding="utf-8")
            self.assertEqual(strategy_events(payload, path), [])


if __name__ == "__main__":
    unittest.main()
