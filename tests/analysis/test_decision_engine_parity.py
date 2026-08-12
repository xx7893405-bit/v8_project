from __future__ import annotations

import unittest
import json
from pathlib import Path
import tempfile
import time

from run_decision_engine_parity import (
    calculate_realized_metrics,
    parity_strategy_specs,
    publish_parity_artifacts,
    run_exact_parity,
    runtime_limit,
    validate_exact_parity,
    validate_run_identity,
)


class DecisionEngineParityTest(unittest.TestCase):
    def test_runtime_limit_fails_closed(self):
        with self.assertRaisesRegex(TimeoutError, "parity runtime exceeded"):
            with runtime_limit(0.01):
                time.sleep(0.05)

    def test_realized_metrics_exclude_mark_to_market_equity(self):
        metrics = calculate_realized_metrics(
            [
                {"exit_time": "2021-01-01T01:00:00+00:00", "pnl": 100.0},
                {"exit_time": "2021-01-01T02:00:00+00:00", "pnl": -50.0},
            ]
        )

        self.assertEqual(
            metrics,
            {
                "return_pct": 0.5,
                "max_drawdown_pct": -0.495,
                "trades": 2,
                "win_rate_pct": 50.0,
                "profit_factor": 2.0,
                "final_balance": 10_050.0,
            },
        )

    def test_parity_specs_share_the_frozen_v2_parameters(self):
        legacy, modular = parity_strategy_specs()

        self.assertEqual(legacy["name"], "legacy_nfe_v2")
        self.assertEqual(modular["name"], "v2_modular")
        self.assertEqual(legacy["kwargs"], modular["kwargs"])
        self.assertEqual(legacy["max_holding_bars"], 96)
        self.assertEqual(modular["max_holding_bars"], 96)

    def test_refuses_to_overwrite_a_parity_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "parity-001"
            target.mkdir()

            with self.assertRaises(FileExistsError):
                publish_parity_artifacts(
                    target,
                    identity={},
                    legacy_metrics={},
                    modular_metrics={},
                    legacy_trades=[],
                    modular_trades=[],
                    legacy_equity=[],
                    modular_equity=[],
                    resolved_config={},
                    module_versions={},
                    runtime_seconds=1.0,
                    runtime_budget_seconds_per_year=180.0,
                    test_evidence={},
                )

    def test_refuses_run_id_that_can_escape_output_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid run_id"):
                run_exact_parity(
                    database=Path(directory) / "missing.duckdb",
                    manifest=Path(directory) / "missing.json",
                    output_root=Path(directory),
                    run_id="../outside",
                )

    def test_publishes_validated_parity_ledgers_and_identity(self):
        entries = json.loads(
            (
                Path(__file__).parents[1]
                / "fixtures/decision_engine/frozen_v2_exact_fill_entry_time_sides.json"
            ).read_text(encoding="utf-8")
        )
        trades = [
            {"entry_time": entry["entry_time"], "type": entry["side"]}
            for entry in entries
        ]
        equity = [
            {
                "event_time": "2026-07-18T13:51:00+00:00",
                "equity": 31_002.20,
                "mark_source": "realized_balance",
            }
        ]
        metrics = {
            "return_pct": 210.022,
            "max_drawdown_pct": -36.5982,
            "trades": 89,
            "win_rate_pct": 40.4494,
            "profit_factor": 1.8393,
            "final_balance": 31_002.20,
        }
        identity = {
            "data_sha256": "5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965",
            "snapshot_fingerprint": "ea28b7ca3c90c46b",
            "mdd_convention": "realized_only",
            "engine_contract_id": "backtest-engine/v1",
            "git_revision": "f" * 40,
        }
        modules = {
            "v2.closed_bar_context": "1",
            "v2.htf_structure_direction": "1",
            "v2.swing_liquidity_target": "1",
            "v2.htf_ob_retrace": "1",
            "v2.ltf_structure_confirmation": "1",
            "v2.rr_cost_risk_gate": "1",
            "v2.retrace_limit_execution": "1",
            "v2.atr_structural_management": "1",
        }

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "parity-001"
            summary_path = publish_parity_artifacts(
                target,
                identity=identity,
                legacy_metrics=metrics,
                modular_metrics=metrics,
                legacy_trades=trades,
                modular_trades=trades,
                legacy_equity=equity,
                modular_equity=equity,
                resolved_config={
                    "min_rr": 3.0,
                    "period": {
                        "start": "2021-01-01 00:00:00",
                        "end": "2026-07-18 13:51:00",
                    },
                },
                module_versions=modules,
                runtime_seconds=555.79,
                runtime_budget_seconds_per_year=180.0,
                test_evidence={
                    "command": "python -m unittest discover -s tests",
                    "passed": 210,
                    "git_revision": "f" * 40,
                },
            )

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["candidate_template_id"], "v2_modular")
            self.assertEqual(summary["identity"], identity)
            self.assertEqual(summary["module_versions"], modules)
            self.assertEqual(summary["schema_version"], "decision-engine-parity/v2")
            self.assertEqual(summary["identity"]["git_revision"], "f" * 40)
            self.assertEqual(summary["verification"]["tests"]["passed"], 210)
            self.assertLessEqual(
                summary["verification"]["runtime"]["seconds_per_year"], 180.0
            )
            self.assertTrue((target / "legacy-trades.parquet").is_file())
            self.assertTrue((target / "modular-trades.parquet").is_file())
            self.assertTrue((target / "legacy-equity.parquet").is_file())
            self.assertTrue((target / "modular-equity.parquet").is_file())

    def test_refuses_non_frozen_engine_or_snapshot_identity(self):
        identity = {
            "data_sha256": "5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965",
            "snapshot_fingerprint": "ea28b7ca3c90c46b",
            "mdd_convention": "realized_only",
            "engine_contract_id": "backtest-engine/v2",
        }

        with self.assertRaisesRegex(ValueError, "frozen run identity mismatch"):
            validate_run_identity(identity)

    def test_refuses_run_identity_without_full_git_revision(self):
        identity = {
            "data_sha256": "5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965",
            "snapshot_fingerprint": "ea28b7ca3c90c46b",
            "mdd_convention": "realized_only",
            "engine_contract_id": "backtest-engine/v1",
        }

        with self.assertRaisesRegex(ValueError, "invalid git_revision"):
            validate_run_identity(identity)

    def test_accepts_the_frozen_entry_and_metric_identity(self):
        entries = json.loads(
            (
                Path(__file__).parents[1]
                / "fixtures/decision_engine/frozen_v2_exact_fill_entry_time_sides.json"
            ).read_text(encoding="utf-8")
        )
        trades = [
            {"entry_time": entry["entry_time"], "type": entry["side"]}
            for entry in entries
        ]
        metrics = {
            "return_pct": 210.022,
            "max_drawdown_pct": -36.5982,
            "trades": 89,
            "win_rate_pct": 40.4494,
            "profit_factor": 1.8393,
            "final_balance": 31_002.20,
        }

        validate_exact_parity(
            trades,
            trades,
            legacy_metrics=metrics,
            modular_metrics=metrics,
        )

    def test_refuses_entry_time_side_mismatch(self):
        legacy = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "LONG"},
        ]
        modular = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "SHORT"},
        ]

        with self.assertRaisesRegex(
            ValueError,
            "entry-time/side exact parity mismatch.*legacy_only.*modular_only",
        ):
            validate_exact_parity(legacy, modular)

    def test_refuses_exit_or_trade_ledger_mismatch(self):
        legacy = [
            {
                "entry_time": "2021-01-01T00:00:00+00:00",
                "exit_time": "2021-01-01T01:00:00+00:00",
                "type": "LONG",
                "pnl": 100.0,
            },
        ]
        modular = [
            {
                "entry_time": "2021-01-01T00:00:00+00:00",
                "exit_time": "2021-01-01T01:15:00+00:00",
                "type": "LONG",
                "pnl": 100.0,
            },
        ]

        with self.assertRaisesRegex(ValueError, "trade ledger exact parity mismatch"):
            validate_exact_parity(legacy, modular)

    def test_refuses_realized_equity_ledger_mismatch(self):
        trades = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "LONG"},
        ]
        legacy_equity = [
            {
                "event_time": "2021-01-01T01:00:00+00:00",
                "equity": 10_100.0,
                "mark_source": "realized_balance",
            },
        ]
        modular_equity = [
            {
                "event_time": "2021-01-01T01:00:00+00:00",
                "equity": 10_099.0,
                "mark_source": "realized_balance",
            },
        ]

        with self.assertRaisesRegex(
            ValueError, "realized equity exact parity mismatch"
        ):
            validate_exact_parity(
                trades,
                trades,
                legacy_equity=legacy_equity,
                modular_equity=modular_equity,
            )

    def test_refuses_headline_metric_mismatch(self):
        trades = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "LONG"},
        ]
        legacy_metrics = {"return_pct": 210.2279, "trades": 89}
        modular_metrics = {"return_pct": 210.2278, "trades": 89}

        with self.assertRaisesRegex(ValueError, "headline metrics exact parity mismatch"):
            validate_exact_parity(
                trades,
                trades,
                legacy_metrics=legacy_metrics,
                modular_metrics=modular_metrics,
            )

    def test_refuses_matching_metrics_that_are_not_the_frozen_baseline(self):
        trades = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "LONG"},
        ]
        wrong_metrics = {
            "return_pct": 210.2278,
            "max_drawdown_pct": -36.5458,
            "trades": 89,
            "win_rate_pct": 40.4494,
            "profit_factor": 1.8409,
            "final_balance": 31_022.79,
        }

        with self.assertRaisesRegex(
            ValueError, "frozen legacy headline metrics mismatch"
        ):
            validate_exact_parity(
                trades,
                trades,
                legacy_metrics=wrong_metrics,
                modular_metrics=wrong_metrics,
            )

    def test_refuses_matching_entries_that_are_not_the_frozen_baseline(self):
        trades = [
            {"entry_time": "2021-01-01T00:00:00+00:00", "type": "LONG"},
        ]
        frozen_metrics = {
            "return_pct": 210.022,
            "max_drawdown_pct": -36.5982,
            "trades": 89,
            "win_rate_pct": 40.4494,
            "profit_factor": 1.8393,
            "final_balance": 31_002.20,
        }

        with self.assertRaisesRegex(
            ValueError, "frozen legacy entry identity mismatch"
        ):
            validate_exact_parity(
                trades,
                trades,
                legacy_metrics=frozen_metrics,
                modular_metrics=frozen_metrics,
            )


if __name__ == "__main__":
    unittest.main()
