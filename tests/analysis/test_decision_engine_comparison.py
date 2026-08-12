from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import tempfile
import unittest

import duckdb

from decision_engine_comparison import build_template_comparison, publish_template_comparison


FROZEN_V2_ENTRY_TIME_SIDES = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures/decision_engine/frozen_v2_exact_fill_entry_time_sides.json"
    ).read_text(encoding="utf-8")
)
FROZEN_SOURCE_FIXTURE_DIRECTORY = (
    Path(__file__).parents[1] / "fixtures/decision_engine/frozen_baseline_exact_fill"
)


def template_summary(
    template_id: str,
    *,
    entries: list[dict[str, str]] | None = None,
    metrics: dict[str, object] | None = None,
) -> dict:
    is_parity_template = template_id in {"legacy_nfe_v2", "nfe_v2_compatible"}
    default_entries = [dict(entry) for entry in FROZEN_V2_ENTRY_TIME_SIDES] if is_parity_template else [
        {"entry_time": "2021-01-01T00:00:00+00:00", "side": "long"},
        {"entry_time": "2021-01-01T01:00:00+00:00", "side": "short"},
    ]
    default_metrics = {
        "return_pct": 210.022,
        "max_drawdown_pct": -36.5982,
        "trades": 89,
        "win_rate_pct": 40.4494,
        "profit_factor": 1.8393,
        "final_balance": 31_002.20,
    } if is_parity_template else {
        "return_pct": 12.5,
        "max_drawdown_pct": -8.25,
        "trades": 2,
        "win_rate_pct": 50.0,
        "profit_factor": 1.4,
        "final_balance": 11_250.0,
    }
    return {
        "template": {
            "id": template_id,
            "version": "1",
            "resolved_config": {"strategy": {"min_rr": 3.0}},
            "config_hash": "99ee1698ed8a0f55dac0630e4c80d8e6e817ccc0aa8ba77fad9efda7890fc6ec",
            "plugins": [
                {"id": "nfe_v2.htf_structure", "version": "1"},
            ],
        },
        "identity": {
            "snapshot_id": "binance-usdtm-btc-001",
            "data_sha256": "5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965",
            "snapshot_fingerprint": "ea28b7ca3c90c46b",
            "git_revision": "f" * 40,
            "period": {
                "start": "2021-01-01T00:00:00+00:00",
                "end": "2026-07-18T13:51:00+00:00",
            },
            "execution_config_hash": "b" * 64,
            "cost_model_hash": "c" * 64,
            "mdd_convention": "realized_only",
            "engine_contract_id": "backtest-engine/v1",
        },
        "reason_code_funnel": {"signal": 4, "risk_rejected": 1},
        "metrics": metrics
        if metrics is not None
        else default_metrics,
        "entry_time_sides": entries
        if entries is not None
        else default_entries,
        "artifact_refs": {
            "summary": {
                "path": f"templates/{template_id}/summary.json",
                "sha256": "1" * 64,
            },
            "trades": {
                "path": f"templates/{template_id}/trades.parquet",
                "sha256": "2" * 64,
            },
            "equity": {
                "path": f"templates/{template_id}/equity.parquet",
                "sha256": "3" * 64,
            },
        },
    }


def artifact_identities(*summaries: dict) -> dict[str, str]:
    return {
        reference["path"]: reference["sha256"]
        for summary in summaries
        for reference in summary["artifact_refs"].values()
    }


def materialize_artifacts(directory: Path, *summaries: dict) -> None:
    for summary in summaries:
        expected_prefix = PurePosixPath("templates") / summary["template"]["id"]
        for artifact_name, reference in summary["artifact_refs"].items():
            path = reference["path"]
            parsed = PurePosixPath(path)
            if (
                "\\" in path
                or parsed.is_absolute()
                or ".." in parsed.parts
                or path != parsed.as_posix()
                or not parsed.is_relative_to(expected_prefix)
            ):
                continue
            artifact_path = directory / path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            if artifact_name == "trades":
                connection = duckdb.connect(":memory:")
                try:
                    connection.execute("CREATE TABLE records(entry_time VARCHAR, type VARCHAR)")
                    rows = [
                        (entry["entry_time"], entry["side"].upper())
                        for entry in summary["entry_time_sides"]
                    ]
                    if rows:
                        connection.executemany(
                            "INSERT INTO records VALUES (?, ?)", rows
                        )
                    connection.execute(
                        "COPY records TO ? (FORMAT PARQUET)", [str(artifact_path)]
                    )
                finally:
                    connection.close()
            elif artifact_name == "equity":
                connection = duckdb.connect(":memory:")
                try:
                    connection.execute(
                        "CREATE TABLE records(event_time VARCHAR, balance DOUBLE, equity DOUBLE)"
                    )
                    connection.execute(
                        "INSERT INTO records VALUES (?, ?, ?)",
                        [
                            summary["identity"]["period"]["end"],
                            summary["metrics"]["final_balance"],
                            summary["metrics"]["final_balance"],
                        ],
                    )
                    connection.execute(
                        "COPY records TO ? (FORMAT PARQUET)", [str(artifact_path)]
                    )
                finally:
                    connection.close()
            else:
                artifact_path.write_bytes(path.encode("utf-8"))
            reference["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def publish_with_artifacts(
    target: Path,
    *,
    run_id: str,
    baseline_summary: dict,
    template_summaries: list[dict],
) -> Path:
    artifact_directory = target.parent / f"{target.name}-artifacts"
    frozen_source_directory = target.parent / f"{target.name}-frozen-source"
    materialize_artifacts(
        artifact_directory, baseline_summary, *template_summaries
    )
    materialize_frozen_source(frozen_source_directory)
    return publish_template_comparison(
        target,
        run_id=run_id,
        baseline_summary=baseline_summary,
        template_summaries=template_summaries,
        artifact_directory=artifact_directory,
        frozen_source_directory=frozen_source_directory,
    )


def materialize_frozen_source(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in ("summary.json", "trades.json"):
        content = (FROZEN_SOURCE_FIXTURE_DIRECTORY / filename).read_bytes()
        (directory / filename).write_bytes(content.removesuffix(b"\n"))


class DecisionEngineComparisonTest(unittest.TestCase):
    def test_publisher_requires_artifact_files_not_only_caller_declared_hashes(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "comparison-run"
            with self.assertRaisesRegex(ValueError, "artifact_directory is required"):
                publish_template_comparison(
                    target,
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_identities=artifact_identities(baseline, compatible),
                )
            self.assertFalse(target.exists())

    def test_refuses_unverified_frozen_baseline_source_files(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_directory = root / "artifacts"
            materialize_artifacts(artifact_directory, baseline, compatible)
            source_directory = root / "frozen-source"
            source_directory.mkdir()
            (source_directory / "summary.json").write_text("not frozen", encoding="utf-8")
            (source_directory / "trades.json").write_text("not frozen", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "frozen source identity mismatch"):
                publish_template_comparison(
                    root / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                    frozen_source_directory=source_directory,
                )

    def test_refuses_caller_declared_hash_when_artifact_content_differs(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            artifact_directory = Path(directory) / "artifacts"
            for summary in (baseline, compatible):
                for reference in summary["artifact_refs"].values():
                    artifact_path = artifact_directory / reference["path"]
                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    artifact_path.write_bytes(b"content-does-not-match-declared-sha")

            with self.assertRaisesRegex(ValueError, "artifact ref identity.*mismatched"):
                publish_template_comparison(
                    Path(directory) / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                    artifact_identities=artifact_identities(baseline, compatible),
                )

    def test_refuses_missing_artifact_file_before_publication(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_directory = root / "artifacts"
            frozen_source_directory = root / "frozen-source"
            materialize_artifacts(artifact_directory, baseline, compatible)
            materialize_frozen_source(frozen_source_directory)
            missing_reference = compatible["artifact_refs"]["equity"]
            (artifact_directory / missing_reference["path"]).unlink()
            target = Path(directory) / "comparison-run"

            with self.assertRaisesRegex(ValueError, "artifact file missing"):
                publish_template_comparison(
                    target,
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                    frozen_source_directory=frozen_source_directory,
                )
            self.assertFalse(target.exists())

    def test_refuses_artifact_symlink_that_escapes_source_directory(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_directory = root / "artifacts"
            materialize_artifacts(artifact_directory, baseline, compatible)
            reference = baseline["artifact_refs"]["summary"]
            artifact_path = artifact_directory / reference["path"]
            outside = root / "outside-summary.json"
            outside.write_bytes(artifact_path.read_bytes())
            artifact_path.unlink()
            artifact_path.symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "artifact path escapes"):
                publish_template_comparison(
                    root / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                )

    def test_refuses_trade_ledger_that_does_not_reconcile_with_summary(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_directory = root / "artifacts"
            frozen_source_directory = root / "frozen-source"
            materialize_artifacts(artifact_directory, baseline, compatible)
            materialize_frozen_source(frozen_source_directory)
            reference = compatible["artifact_refs"]["trades"]
            artifact_path = artifact_directory / reference["path"]
            artifact_path.unlink()
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    "CREATE TABLE records(entry_time VARCHAR, type VARCHAR)"
                )
                connection.executemany(
                    "INSERT INTO records VALUES (?, ?)",
                    [
                        (entry["entry_time"], entry["side"].upper())
                        for entry in compatible["entry_time_sides"][1:]
                    ],
                )
                connection.execute(
                    "COPY records TO ? (FORMAT PARQUET)", [str(artifact_path)]
                )
            finally:
                connection.close()
            reference["sha256"] = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()

            with self.assertRaisesRegex(ValueError, "trade ledger mismatch"):
                publish_template_comparison(
                    Path(directory) / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                    frozen_source_directory=frozen_source_directory,
                )

    def test_refuses_equity_ledger_that_does_not_reconcile_final_balance(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_directory = root / "artifacts"
            frozen_source_directory = root / "frozen-source"
            materialize_artifacts(artifact_directory, baseline, compatible)
            materialize_frozen_source(frozen_source_directory)
            reference = compatible["artifact_refs"]["equity"]
            artifact_path = artifact_directory / reference["path"]
            artifact_path.unlink()
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    "CREATE TABLE records(event_time VARCHAR, balance DOUBLE, equity DOUBLE)"
                )
                connection.execute(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    [compatible["identity"]["period"]["end"], 1.0, 1.0],
                )
                connection.execute(
                    "COPY records TO ? (FORMAT PARQUET)", [str(artifact_path)]
                )
            finally:
                connection.close()
            reference["sha256"] = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()

            with self.assertRaisesRegex(ValueError, "equity ledger mismatch"):
                publish_template_comparison(
                    Path(directory) / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=artifact_directory,
                    frozen_source_directory=frozen_source_directory,
                )

    def test_publishes_compact_comparison_with_exact_entry_identity(self):
        baseline = template_summary("legacy_nfe_v2")
        nfe_v2_compatible = template_summary("nfe_v2_compatible")
        candidate = template_summary("experimental_template")

        with tempfile.TemporaryDirectory() as directory:
            artifact_path = publish_with_artifacts(
                Path(directory) / "comparison-run",
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[nfe_v2_compatible, candidate],
            )

            self.assertEqual(artifact_path.name, "template-comparison.json")
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

        self.assertEqual(artifact["schema_version"], "decision-engine-comparison/v2")
        self.assertEqual(artifact["baseline_template_id"], "legacy_nfe_v2")
        self.assertEqual(artifact["identity"], baseline["identity"])
        self.assertEqual(artifact["baseline"]["metrics"], baseline["metrics"])
        self.assertEqual(
            artifact["templates"][0]["template"],
            nfe_v2_compatible["template"],
        )
        self.assertEqual(
            {
                key: artifact["templates"][1]["entry_time_side_overlap"][key]
                for key in ("baseline_count", "template_count", "shared_count", "exact_match")
            },
            {
                "baseline_count": 89,
                "template_count": 2,
                "shared_count": 0,
                "exact_match": False,
            },
        )
        self.assertEqual(
            artifact["templates"][1]["entry_time_side_overlap"][
                "baseline_identity_sha256"
            ],
            artifact["baseline"]["entry_identity_sha256"],
        )
        self.assertRegex(
            artifact["templates"][1]["entry_time_side_overlap"][
                "template_identity_sha256"
            ],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(artifact["baseline"]["entry_identity_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            artifact["baseline"]["artifact_identity"],
            baseline["artifact_refs"]["summary"],
        )
        self.assertEqual(
            artifact["baseline"]["ledger_identity"],
            {
                "trades": baseline["artifact_refs"]["trades"],
                "equity": baseline["artifact_refs"]["equity"],
            },
        )
        self.assertEqual(
            artifact["baseline"]["frozen_source_identity"],
            {
                "summary_sha256": "3322dfc9c41dd4bb6c4d70e75e2e8bbd91bf748b4a9155fda7197101580dda5f",
                "trades_sha256": "89f3473ef609975d5c6751d00cade9fb97d6e66648db1d097883be822fa21b6c",
            },
        )
        self.assertNotIn("entry_time_sides", artifact["templates"][0])
        self.assertEqual(
            artifact["templates"][0]["artifact_refs"],
            nfe_v2_compatible["artifact_refs"],
        )
        self.assertNotIn("candles", json.dumps(artifact))
        self.assertNotIn("entry_time_sides", json.dumps(artifact))

    def test_refuses_to_publish_when_v2_compatibility_metrics_do_not_match_baseline(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        compatible["metrics"]["final_balance"] = 11_251.0

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "comparison-run"
            with self.assertRaisesRegex(ValueError, "headline metrics mismatch"):
                publish_with_artifacts(
                    target,
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                )
            self.assertFalse(target.exists())

    def test_refuses_to_publish_when_v2_compatibility_entry_identity_differs(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        compatible["entry_time_sides"][0]["side"] = "long"

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "entry-time/side identity mismatch"):
                publish_with_artifacts(
                    Path(directory) / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                )

    def test_refuses_missing_headline_metrics_and_zero_trade_non_null_rates(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        missing_metric = template_summary("candidate")
        missing_metric["metrics"].pop("profit_factor")
        zero_trade = template_summary(
            "zero-trade-candidate",
            entries=[],
            metrics={
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": None,
                "final_balance": 10_000.0,
            },
        )
        zero_trade_profit_factor = template_summary(
            "zero-trade-profit-factor",
            entries=[],
            metrics={
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "trades": 0,
                "win_rate_pct": None,
                "profit_factor": 1.0,
                "final_balance": 10_000.0,
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "headline metrics"):
                publish_with_artifacts(
                    Path(directory) / "missing",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible, missing_metric],
                )
            with self.assertRaisesRegex(ValueError, "zero-trade win_rate_pct must be null"):
                publish_with_artifacts(
                    Path(directory) / "zero-trade",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible, zero_trade],
                )
            with self.assertRaisesRegex(ValueError, "zero-trade profit_factor must be null"):
                publish_with_artifacts(
                    Path(directory) / "zero-trade-profit-factor",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible, zero_trade_profit_factor],
                )

    def test_refuses_mixed_snapshot_execution_config_or_cost_identity(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        for field, value in (
            ("snapshot_id", "a-different-snapshot"),
            ("execution_config_hash", "d" * 64),
            ("cost_model_hash", "e" * 64),
        ):
            with self.subTest(field=field):
                candidate = template_summary("candidate")
                candidate["identity"][field] = value
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ValueError, "snapshot/config/cost identity mismatch"):
                        publish_with_artifacts(
                            Path(directory) / "comparison-run",
                            run_id="comparison-001",
                            baseline_summary=baseline,
                            template_summaries=[compatible, candidate],
                        )

    def test_build_fails_closed_for_fake_baseline_or_missing_reproducibility_identity(self):
        compatible = template_summary("nfe_v2_compatible")
        fake_baseline = template_summary("not_the_frozen_legacy")

        with self.assertRaisesRegex(ValueError, "baseline template id"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=fake_baseline,
                template_summaries=[compatible],
                artifact_identities=artifact_identities(fake_baseline, compatible),
            )

        for field in (
            "data_sha256",
            "snapshot_fingerprint",
            "git_revision",
            "period",
            "execution_config_hash",
            "cost_model_hash",
            "mdd_convention",
        ):
            with self.subTest(field=field):
                baseline = template_summary("legacy_nfe_v2")
                baseline["identity"].pop(field)
                with self.assertRaisesRegex(ValueError, "comparison identity"):
                    build_template_comparison(
                        run_id="comparison-001",
                        baseline_summary=baseline,
                        template_summaries=[compatible],
                        artifact_identities=artifact_identities(baseline, compatible),
                    )

    def test_build_refuses_identity_and_artifact_manifest_mismatches(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")

        for field, value in (
            ("data_sha256", "9" * 64),
            ("snapshot_fingerprint", "8" * 16),
            ("git_revision", "7" * 40),
            ("mdd_convention", "mark_to_market_1m"),
            (
                "period",
                {
                    "start": "2022-01-01T00:00:00+00:00",
                    "end": "2026-07-18T13:51:00+00:00",
                },
            ),
        ):
            with self.subTest(field=field):
                candidate = template_summary("candidate")
                candidate["identity"][field] = value
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    build_template_comparison(
                        run_id="comparison-001",
                        baseline_summary=baseline,
                        template_summaries=[compatible, candidate],
                        artifact_identities=artifact_identities(
                            baseline, compatible, candidate
                        ),
                    )

        identities = artifact_identities(baseline, compatible)
        identities.pop(baseline["artifact_refs"]["trades"]["path"])
        with self.assertRaisesRegex(ValueError, "identity missing or mismatched"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=identities,
            )

    def test_build_refuses_matching_but_false_frozen_baseline_inputs(self):
        for field, value in (
            ("data_sha256", "9" * 64),
            ("snapshot_fingerprint", "8" * 16),
            ("mdd_convention", "mark_to_market_1m"),
        ):
            with self.subTest(field=field):
                baseline = template_summary("legacy_nfe_v2")
                compatible = template_summary("nfe_v2_compatible")
                baseline["identity"][field] = value
                compatible["identity"][field] = value
                with self.assertRaisesRegex(ValueError, "frozen legacy baseline"):
                    build_template_comparison(
                        run_id="comparison-001",
                        baseline_summary=baseline,
                        template_summaries=[compatible],
                        artifact_identities=artifact_identities(baseline, compatible),
                    )

        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        baseline["metrics"]["return_pct"] = 999.0
        compatible["metrics"]["return_pct"] = 999.0
        with self.assertRaisesRegex(ValueError, "frozen legacy baseline"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=artifact_identities(baseline, compatible),
            )

        identities = artifact_identities(baseline, compatible)
        identities[baseline["artifact_refs"]["equity"]["path"]] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity missing or mismatched"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=identities,
            )

    def test_build_refuses_matching_but_false_frozen_entry_identity(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        baseline["entry_time_sides"][0]["side"] = "long"
        compatible["entry_time_sides"][0]["side"] = "long"

        with self.assertRaisesRegex(ValueError, "frozen legacy entry identity"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=artifact_identities(baseline, compatible),
            )

    def test_build_does_not_claim_frozen_source_was_verified(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        artifact = build_template_comparison(
            run_id="comparison-001",
            baseline_summary=baseline,
            template_summaries=[compatible],
            artifact_identities=artifact_identities(baseline, compatible),
        )

        self.assertNotIn("frozen_source_identity", artifact["baseline"])

    def test_build_requires_frozen_backtest_engine_contract_identity(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        baseline["identity"].pop("engine_contract_id")

        with self.assertRaisesRegex(ValueError, "engine contract"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=artifact_identities(baseline, compatible),
            )

    def test_build_requires_config_hash_to_match_resolved_config(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        compatible["template"]["resolved_config"]["strategy"]["min_rr"] = 4.0

        with self.assertRaisesRegex(ValueError, "resolved config hash mismatch"):
            build_template_comparison(
                run_id="comparison-001",
                baseline_summary=baseline,
                template_summaries=[compatible],
                artifact_identities=artifact_identities(baseline, compatible),
            )

    def test_refuses_noncanonical_or_raw_artifact_inputs(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        invalid_reference = template_summary("candidate")
        invalid_reference["artifact_refs"]["summary"]["path"] = "../summary.json"
        raw_records = template_summary("raw-records")
        raw_records["trades"] = [{"entry_time": "2021-01-03T01:00:00+00:00"}]

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "artifact refs"):
                publish_with_artifacts(
                    Path(directory) / "invalid-reference",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible, invalid_reference],
                )
            with self.assertRaisesRegex(ValueError, "summary fields"):
                publish_with_artifacts(
                    Path(directory) / "raw-records",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible, raw_records],
                )

    def test_refuses_normalizable_but_noncanonical_artifact_path(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        compatible["artifact_refs"]["summary"]["path"] = (
            "templates/nfe_v2_compatible/./summary.json"
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "canonical run-relative"):
                publish_with_artifacts(
                    Path(directory) / "comparison-run",
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                )

    def test_never_overwrites_an_existing_run_directory(self):
        baseline = template_summary("legacy_nfe_v2")
        compatible = template_summary("nfe_v2_compatible")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "comparison-run"
            target.mkdir()
            sentinel = target / "existing.json"
            sentinel.write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                publish_template_comparison(
                    target,
                    run_id="comparison-001",
                    baseline_summary=baseline,
                    template_summaries=[compatible],
                    artifact_directory=Path(directory) / "artifacts",
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
