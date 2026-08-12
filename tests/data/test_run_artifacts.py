from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_artifacts import (
    canonical_artifact_references,
    create_run_directory,
    render_review_markdown,
    render_summary_markdown,
    validate_compact_summary,
    validate_run_artifact,
    validate_run_id,
    validate_run_manifest,
)


def valid_manifest():
    return {
        "schema_version": "run-artifact/v1",
        "metrics_version": "metrics/v1",
        "run_id": "20260728T010203Z_a1b2c3d",
        "created_at": "2026-07-28T01:02:03+00:00",
        "strategy": {"name": "nfe_v2", "config_id": "risk5-lev20"},
        "data": {
            "snapshot_id": "sha256:abc123",
            "content_sha256": "a" * 64,
            "market_type": "swap",
            "symbol": "BTC/USDT:USDT",
        },
        "git": {"revision": "81799ed"},
        "period": {
            "start": "2021-01-01T00:00:00+00:00",
            "end": "2026-07-18T13:51:00+00:00",
        },
        "assumptions": {
            "costs": {"maker_fee": 0.0002, "taker_fee": 0.0005},
            "leverage": {"maximum": 20.0},
        },
        "artifacts": canonical_artifact_references(),
    }


def valid_provenance():
    manifest = valid_manifest()
    return {
        key: deepcopy(manifest[key])
        for key in ("strategy", "data", "git", "period", "assumptions")
    }


def valid_summary():
    return {
        "schema_version": "run-artifact/v1",
        "metrics_version": "metrics/v1",
        "run_id": "20260728T010203Z_a1b2c3d",
        "created_at": "2026-07-28T01:02:03+00:00",
        "provenance": valid_provenance(),
        "artifacts": canonical_artifact_references(),
        "verdict": "review",
        "warnings": ["research profile"],
        "results": [
            {
                "strategy": "nfe_v2",
                "period": "full",
                "start": "2021-01-01T00:00:00+00:00",
                "end": "2026-07-18T13:51:00+00:00",
                "metrics": {
                    "return_pct": 12.5,
                    "max_drawdown_pct": -8.25,
                    "trades": 42,
                    "win_rate_pct": 45.24,
                    "profit_factor": 1.4,
                    "final_balance": 11_250.0,
                },
            }
        ],
    }


class RunArtifactContractTest(unittest.TestCase):
    def test_run_id_is_a_strict_single_filesystem_segment(self):
        self.assertEqual(validate_run_id("20260728T010203Z_a1b2c3d"), None)

        for invalid in ("", ".", "..", "../escape", "parent/run", r"parent\run"):
            with self.subTest(run_id=invalid):
                with self.assertRaisesRegex(ValueError, "run_id"):
                    validate_run_id(invalid)

    def test_canonical_references_are_portable_and_orders_are_explicitly_unavailable(self):
        references = canonical_artifact_references()

        self.assertEqual(
            references,
            {
                "manifest": {"available": True, "path": "manifest.json"},
                "summary": {"available": True, "path": "summary.json"},
                "summary_markdown": {"available": True, "path": "summary.md"},
                "review": {"available": True, "path": "review.md"},
                "trades": {"available": True, "path": "trades.parquet"},
                "equity": {"available": True, "path": "equity.parquet"},
                "diagnostics": {"available": True, "path": "diagnostics.parquet"},
                "log": {"available": True, "path": "run.log"},
                "orders": {
                    "available": False,
                    "path": None,
                    "reason": "not produced",
                },
            },
        )

    def test_manifest_requires_versioned_provenance(self):
        manifest = valid_manifest()
        validate_run_manifest(manifest)

        for key in (
            "schema_version",
            "metrics_version",
            "run_id",
            "created_at",
            "strategy",
            "data",
            "git",
            "period",
            "assumptions",
            "artifacts",
        ):
            invalid = dict(manifest)
            invalid.pop(key)
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, key):
                    validate_run_manifest(invalid)

    def test_manifest_rejects_incomplete_or_ambiguous_identity_and_time(self):
        invalid_cases = []
        for section, field in (
            ("strategy", "name"),
            ("strategy", "config_id"),
            ("data", "snapshot_id"),
            ("data", "market_type"),
            ("data", "symbol"),
            ("git", "revision"),
            ("period", "start"),
            ("period", "end"),
            ("assumptions", "costs"),
            ("assumptions", "leverage"),
        ):
            invalid = valid_manifest()
            invalid[section].pop(field)
            invalid_cases.append((f"{section}.{field}", invalid))

        blank_run_id = valid_manifest()
        blank_run_id["run_id"] = ""
        invalid_cases.append(("run_id", blank_run_id))
        naive_created_at = valid_manifest()
        naive_created_at["created_at"] = "2026-07-28T01:02:03"
        invalid_cases.append(("created_at", naive_created_at))
        reversed_period = deepcopy(valid_manifest())
        reversed_period["period"]["start"], reversed_period["period"]["end"] = (
            reversed_period["period"]["end"],
            reversed_period["period"]["start"],
        )
        invalid_cases.append(("period", reversed_period))

        for message, invalid in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message.split(".")[0]):
                    validate_run_manifest(invalid)

    def test_manifest_identity_and_assumptions_cannot_be_empty(self):
        for section, field in (
            ("strategy", "name"),
            ("strategy", "config_id"),
            ("data", "snapshot_id"),
            ("data", "market_type"),
            ("data", "symbol"),
            ("git", "revision"),
        ):
            invalid = valid_manifest()
            invalid[section][field] = ""
            with self.subTest(section=section, field=field):
                with self.assertRaisesRegex(ValueError, section):
                    validate_run_manifest(invalid)

        for field in ("costs", "leverage"):
            invalid = valid_manifest()
            invalid["assumptions"][field] = {}
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "assumptions"):
                    validate_run_manifest(invalid)

    def test_data_identity_requires_a_strong_content_sha256(self):
        for value in (None, "", "abc123", "g" * 64):
            invalid = valid_manifest()
            if value is None:
                invalid["data"].pop("content_sha256")
            else:
                invalid["data"]["content_sha256"] = value
            with self.subTest(content_sha256=value):
                with self.assertRaisesRegex(ValueError, "content_sha256"):
                    validate_run_manifest(invalid)

    def test_manifest_rejects_nonportable_or_implicit_artifact_references(self):
        invalid_cases = []
        absolute = valid_manifest()
        absolute["artifacts"]["summary"]["path"] = "/tmp/summary.json"
        invalid_cases.append(absolute)
        traversal = valid_manifest()
        traversal["artifacts"]["summary"]["path"] = "../summary.json"
        invalid_cases.append(traversal)
        implicit_orders = valid_manifest()
        implicit_orders["artifacts"].pop("orders")
        invalid_cases.append(implicit_orders)

        for invalid in invalid_cases:
            with self.subTest(artifacts=invalid["artifacts"]):
                with self.assertRaisesRegex(ValueError, "artifacts"):
                    validate_run_manifest(invalid)

    def test_compact_summary_requires_canonical_metrics_for_every_result(self):
        summary = valid_summary()
        validate_compact_summary(summary)

        for metric in (
            "return_pct",
            "max_drawdown_pct",
            "trades",
            "win_rate_pct",
            "profit_factor",
            "final_balance",
        ):
            invalid = deepcopy(summary)
            invalid["results"][0]["metrics"].pop(metric)
            with self.subTest(metric=metric):
                with self.assertRaisesRegex(ValueError, metric):
                    validate_compact_summary(invalid)

    def test_compact_summary_requires_reviewable_provenance(self):
        validate_compact_summary(valid_summary())

        for section in ("strategy", "data", "git", "period", "assumptions"):
            invalid = valid_summary()
            invalid["provenance"].pop(section)
            with self.subTest(section=section):
                with self.assertRaisesRegex(ValueError, section):
                    validate_compact_summary(invalid)

    def test_compact_summary_provenance_is_known_scalar_identity_only(self):
        invalid = valid_summary()
        invalid["provenance"]["data"]["payload"] = [{"rows": 1}]
        with self.assertRaisesRegex(ValueError, "data"):
            validate_compact_summary(invalid)

        invalid = valid_summary()
        invalid["provenance"]["data"]["snapshot_id"] = ["snapshot-001"]
        with self.assertRaisesRegex(ValueError, "data"):
            validate_compact_summary(invalid)

        invalid = valid_summary()
        invalid["provenance"]["assumptions"]["costs"]["fee_schedule"] = [0.1]
        with self.assertRaisesRegex(ValueError, "assumptions"):
            validate_compact_summary(invalid)

    def test_compact_summary_requires_an_aware_created_at(self):
        for value in (None, "2026-07-28T01:02:03"):
            invalid = valid_summary()
            if value is None:
                invalid.pop("created_at")
            else:
                invalid["created_at"] = value
            with self.subTest(created_at=value):
                with self.assertRaisesRegex(ValueError, "created_at"):
                    validate_compact_summary(invalid)

    def test_compact_summary_reuses_strict_run_id_validation(self):
        invalid = valid_summary()
        invalid["run_id"] = "../escape"

        with self.assertRaisesRegex(ValueError, "run_id"):
            validate_compact_summary(invalid)

    def test_compact_summary_accepts_canonical_artifact_references(self):
        summary = valid_summary()
        summary["artifacts"] = canonical_artifact_references()

        validate_compact_summary(summary)

    def test_compact_summary_rejects_missing_or_nonportable_artifact_references(self):
        missing = valid_summary()
        missing.pop("artifacts")
        invalid_cases = [missing]
        for path in ("/tmp/trades.parquet", "../trades.parquet"):
            invalid = valid_summary()
            invalid["artifacts"]["trades"]["path"] = path
            invalid_cases.append(invalid)

        for invalid in invalid_cases:
            with self.subTest(artifacts=invalid.get("artifacts")):
                with self.assertRaisesRegex(ValueError, "artifacts"):
                    validate_compact_summary(invalid)

    def test_compact_summary_rejects_legacy_top_level_metric_set(self):
        summary = valid_summary()
        result = summary.pop("results")[0]
        summary.update(result)

        with self.assertRaisesRegex(ValueError, "unknown summary field"):
            validate_compact_summary(summary)

    def test_compact_summary_rejects_embedded_raw_series_and_records(self):
        for field in ("candles", "raw_candles", "trades", "equity", "orders"):
            invalid = valid_summary()
            invalid["details"] = {field: [{"timestamp": "2026-07-01T00:00:00Z"}]}
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_compact_summary(invalid)

        scalar_trade_count = valid_summary()
        scalar_trade_count["results"][0]["metrics"]["trades"] = 0
        validate_compact_summary(scalar_trade_count)

    def test_compact_summary_rejects_unknown_collection_aliases(self):
        for field in ("trade_records", "equity_events", "payload"):
            invalid = valid_summary()
            invalid[field] = [{"timestamp": "2026-07-01T00:00:00Z"}]
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    validate_compact_summary(invalid)

    def test_compact_summary_rejects_raw_records_nested_inside_a_result(self):
        invalid = valid_summary()
        invalid["results"][0]["details"] = {
            "trades": [{"entry_time": "2026-07-01T00:00:00Z"}]
        }

        with self.assertRaises(ValueError):
            validate_compact_summary(invalid)

    def test_compact_summary_rejects_unknown_result_fields(self):
        invalid = valid_summary()
        invalid["results"][0]["payload"] = {"secret_records": [1, 2, 3]}

        with self.assertRaisesRegex(ValueError, "payload"):
            validate_compact_summary(invalid)

    def test_compact_summary_known_identity_fields_are_nonempty_strings(self):
        invalid = valid_summary()
        invalid["verdict"] = {"status": "review"}
        with self.assertRaisesRegex(ValueError, "verdict"):
            validate_compact_summary(invalid)

        invalid = valid_summary()
        invalid["results"][0]["strategy"] = {"name": "nfe_v2"}
        with self.assertRaisesRegex(ValueError, "strategy"):
            validate_compact_summary(invalid)

    def test_each_result_requires_aware_ordered_period_bounds(self):
        invalid_cases = []
        for field in ("start", "end"):
            invalid = valid_summary()
            invalid["results"][0].pop(field)
            invalid_cases.append((field, invalid))
        naive = valid_summary()
        naive["results"][0]["start"] = "2021-01-01T00:00:00"
        invalid_cases.append(("start", naive))
        reversed_period = valid_summary()
        reversed_period["results"][0]["start"], reversed_period["results"][0]["end"] = (
            reversed_period["results"][0]["end"],
            reversed_period["results"][0]["start"],
        )
        invalid_cases.append(("period", reversed_period))

        for message, invalid in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_compact_summary(invalid)

    def test_compact_summary_warnings_are_bounded_strings(self):
        for warnings in ([{"message": "not compact"}], ["x" * 501], ["x"] * 6):
            invalid = valid_summary()
            invalid["warnings"] = warnings
            with self.subTest(warnings=warnings):
                with self.assertRaisesRegex(ValueError, "warnings"):
                    validate_compact_summary(invalid)

    def test_baseline_is_compact_scalar_identity_only(self):
        summary = valid_summary()
        summary["baseline"] = {
            "run_id": "baseline-001",
            "content_sha256": "b" * 64,
            "generated_at": "2026-07-18T14:04:39+00:00",
            "snapshot_id": "snapshot-001",
        }
        validate_compact_summary(summary)

        invalid = deepcopy(summary)
        invalid["baseline"]["payload"] = [{"trades": 10}]
        with self.assertRaisesRegex(ValueError, "baseline"):
            validate_compact_summary(invalid)

    def test_metrics_reject_nonfinite_values_and_invalid_counts_or_rates(self):
        invalid_values = {
            "return_pct": float("nan"),
            "max_drawdown_pct": float("inf"),
            "trades": 1.5,
            "win_rate_pct": 100.1,
            "profit_factor": -0.1,
            "final_balance": float("-inf"),
        }
        for metric, value in invalid_values.items():
            invalid = valid_summary()
            invalid["results"][0]["metrics"][metric] = value
            with self.subTest(metric=metric):
                with self.assertRaisesRegex(ValueError, metric):
                    validate_compact_summary(invalid)

        no_losses = valid_summary()
        no_losses["results"][0]["metrics"]["profit_factor"] = None
        validate_compact_summary(no_losses)

    def test_metrics_allow_only_canonical_keys_plus_nonnegative_missed(self):
        summary = valid_summary()
        summary["results"][0]["metrics"]["missed"] = 3
        validate_compact_summary(summary)

        for field, value in (("missed", -1), ("missed", 1.5), ("trade_records", 3)):
            invalid = valid_summary()
            invalid["results"][0]["metrics"][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    validate_compact_summary(invalid)

    def test_baseline_deltas_are_canonical_finite_scalars_or_none(self):
        summary = valid_summary()
        summary["results"][0]["baseline_deltas"] = {
            "return_pct": 1.25,
            "profit_factor": None,
        }
        validate_compact_summary(summary)

        for field, value in (
            ("payload", 1),
            ("return_pct", [1.25]),
            ("return_pct", float("inf")),
        ):
            invalid = deepcopy(summary)
            invalid["results"][0]["baseline_deltas"][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "baseline_deltas"):
                    validate_compact_summary(invalid)

    def test_markdown_renderers_are_deterministic_and_use_only_the_summary_object(self):
        summary = valid_summary()
        expected_summary = """# Run summary

Run ID: `20260728T010203Z_a1b2c3d`

| Strategy | Period | Return % | MDD % | Trades | Win rate % | Profit factor | Final balance |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| nfe_v2 | full | 12.5 | -8.25 | 42 | 45.24 | 1.4 | 11250.0 |

## Warnings

- research profile
"""
        expected_review = """# Review

Run ID: `20260728T010203Z_a1b2c3d`

Verdict: **review**.

## Warnings

- research profile
"""
        with patch("builtins.open", side_effect=AssertionError("renderer read a file")):
            self.assertEqual(render_summary_markdown(summary), expected_summary)
            self.assertEqual(render_summary_markdown(summary), expected_summary)
            self.assertEqual(render_review_markdown(summary), expected_review)
            self.assertEqual(render_review_markdown(summary), expected_review)

    def test_completed_run_directory_cannot_be_reused_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory) / "run-001"
            self.assertEqual(create_run_directory(run_directory), run_directory)
            sentinel = run_directory / "summary.json"
            sentinel.write_text("original", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                create_run_directory(run_directory)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")

    def test_run_artifact_rejects_manifest_summary_identity_mismatch(self):
        validate_run_artifact(valid_manifest(), valid_summary())

        mismatched = valid_summary()
        mismatched["run_id"] = "another-run"
        with self.assertRaisesRegex(ValueError, "run_id"):
            validate_run_artifact(valid_manifest(), mismatched)

        mismatched = valid_summary()
        mismatched["created_at"] = "2026-07-28T01:02:04+00:00"
        with self.assertRaisesRegex(ValueError, "created_at"):
            validate_run_artifact(valid_manifest(), mismatched)

        mismatched = valid_summary()
        mismatched["provenance"]["data"]["snapshot_id"] = "sha256:different"
        with self.assertRaisesRegex(ValueError, "data"):
            validate_run_artifact(valid_manifest(), mismatched)


if __name__ == "__main__":
    unittest.main()
