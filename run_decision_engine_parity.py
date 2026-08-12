"""Fail-closed exact parity checks for legacy and modular V2 results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic

import pandas as pd

from decision_engine_comparison import (
    FROZEN_BASELINE_IDENTITY,
    FROZEN_BASELINE_ENTRY_IDENTITY_SHA256,
    FROZEN_BASELINE_METRICS,
)
from download_perpetual_history import verify_manifest
from nfe_v2_decision_template import V2ModularDecisionTemplate, build_v2_modular_template
from nfe_v2_strategy import NFEV2Strategy
from run_contract_strategy_comparison import (
    DEFAULT_DATABASE,
    DEFAULT_DATA_MANIFEST,
    FULL_START,
    assert_same_snapshot,
    benchmark_config,
    calculate_metrics,
    clip_period,
    run_period,
    snapshot_identity,
    strategy_specs,
    write_parquet,
)
from run_artifacts import validate_run_id


V2_MODULE_VERSIONS = {
    "v2.closed_bar_context": "1",
    "v2.htf_structure_direction": "1",
    "v2.swing_liquidity_target": "1",
    "v2.htf_ob_retrace": "1",
    "v2.ltf_structure_confirmation": "1",
    "v2.rr_cost_risk_gate": "1",
    "v2.retrace_limit_execution": "1",
    "v2.atr_structural_management": "1",
}


def current_git_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid git_revision")
    return revision


@contextmanager
def runtime_limit(seconds: float):
    """Abort a parity run that exceeds the user-facing runtime budget."""

    previous_handler = signal.getsignal(signal.SIGALRM)

    def timeout_handler(_signum, _frame):
        raise TimeoutError(f"parity runtime exceeded {seconds:g} seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _modular_v2_factory(**kwargs) -> V2ModularDecisionTemplate:
    return V2ModularDecisionTemplate(NFEV2Strategy(**kwargs))


def parity_strategy_specs() -> tuple[dict[str, object], dict[str, object]]:
    """Return legacy and modular V2 specs with one shared parameter snapshot."""

    frozen = next(spec for spec in strategy_specs() if spec["name"] == "nfe_v2")
    legacy = {**frozen, "name": "legacy_nfe_v2"}
    modular = {**legacy, "name": "v2_modular", "class": _modular_v2_factory}
    return legacy, modular


def calculate_realized_metrics(
    trades: Sequence[Mapping[str, object]], *, missed: int = 0
) -> dict[str, object]:
    """Calculate the frozen realized-only headline convention."""

    metrics = calculate_metrics([dict(trade) for trade in trades], missed, 10_000.0)
    metrics.pop("missed")
    return metrics


def run_exact_parity(
    *,
    database: Path,
    manifest: Path,
    output_root: Path,
    run_id: str,
    runtime_budget_seconds_per_year: float = 180.0,
    verified_test_count: int = 0,
    verified_test_command: str = "",
) -> Path:
    """Run legacy and modular V2 once on the frozen full-period snapshot."""

    validate_run_id(run_id)
    started = monotonic()
    target = output_root / run_id
    if target.exists():
        raise FileExistsError(target)
    verified = verify_manifest(database, manifest)
    snapshot = snapshot_identity(database)
    identity = {
        "data_sha256": verified["sha256"],
        "snapshot_fingerprint": snapshot["fingerprint"],
        "mdd_convention": "realized_only",
        "engine_contract_id": "backtest-engine/v1",
        "git_revision": current_git_revision(),
    }
    validate_run_identity(identity)
    start, end = clip_period(
        FULL_START,
        pd.Timestamp(snapshot["last_open_time"]),
        pd.Timestamp(snapshot["first_open_time"]),
        pd.Timestamp(snapshot["last_open_time"]),
    )

    runs = []
    for spec in parity_strategy_specs():
        result, trades, equity, _ = run_period(
            spec, "full", start, end, database, snapshot
        )
        unlabeled_trades = [
            {key: value for key, value in row.items() if key not in {"strategy", "period"}}
            for row in trades
        ]
        unlabeled_equity = [
            {key: value for key, value in row.items() if key not in {"strategy", "period"}}
            for row in equity
        ]
        runs.append(
            {
                "trades": unlabeled_trades,
                "equity": unlabeled_equity,
                "metrics": calculate_realized_metrics(
                    unlabeled_trades, missed=int(result["metrics"]["missed"])
                ),
            }
        )
    assert_same_snapshot(snapshot, snapshot_identity(database))

    legacy_spec, _ = parity_strategy_specs()
    config = benchmark_config(96)
    template = build_v2_modular_template(
        NFEV2Strategy(**legacy_spec["kwargs"]),
        config.to_backtest_config(),
        config.to_run_config(),
    )
    resolved_config = {
        "strategy": dict(legacy_spec["kwargs"]),
        "backtest": asdict(config),
        "template": template.to_dict(),
        "period": {"start": str(start), "end": str(end)},
    }

    output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_root, prefix=f".{run_id}.") as staging_root:
        staged = Path(staging_root) / run_id
        summary = publish_parity_artifacts(
            staged,
            identity=identity,
            legacy_metrics=runs[0]["metrics"],
            modular_metrics=runs[1]["metrics"],
            legacy_trades=runs[0]["trades"],
            modular_trades=runs[1]["trades"],
            legacy_equity=runs[0]["equity"],
            modular_equity=runs[1]["equity"],
            resolved_config=resolved_config,
            module_versions=V2_MODULE_VERSIONS,
            runtime_seconds=monotonic() - started,
            runtime_budget_seconds_per_year=runtime_budget_seconds_per_year,
            test_evidence={
                "command": verified_test_command,
                "passed": verified_test_count,
                "git_revision": identity["git_revision"],
            },
        )
        if target.exists():
            raise FileExistsError(target)
        staged.rename(target)
    return target / summary.name


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen legacy/modular V2 exact parity.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DATA_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=Path("reports/decision_engine_parity"))
    parser.add_argument(
        "--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    parser.add_argument("--max-runtime-seconds", type=float, default=600.0)
    parser.add_argument("--runtime-budget-seconds-per-year", type=float, default=180.0)
    parser.add_argument("--verified-test-count", type=int, default=0)
    parser.add_argument("--verified-test-command", default="")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    with runtime_limit(args.max_runtime_seconds):
        summary = run_exact_parity(
            database=args.database,
            manifest=args.manifest,
            output_root=args.output_root,
            run_id=args.run_id,
            runtime_budget_seconds_per_year=args.runtime_budget_seconds_per_year,
            verified_test_count=args.verified_test_count,
            verified_test_command=args.verified_test_command,
        )
    print(json.dumps({"status": "exact_parity", "summary": str(summary)}))


def validate_run_identity(identity: Mapping[str, object]) -> None:
    """Require the frozen data, snapshot, MDD, and engine contract."""

    if any(identity.get(key) != value for key, value in FROZEN_BASELINE_IDENTITY.items()):
        raise ValueError("frozen run identity mismatch")
    if not isinstance(identity.get("git_revision"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", identity["git_revision"]
    ):
        raise ValueError("invalid git_revision")


def publish_parity_artifacts(
    run_directory: str | Path,
    *,
    identity: Mapping[str, object],
    legacy_metrics: Mapping[str, object],
    modular_metrics: Mapping[str, object],
    legacy_trades: Sequence[Mapping[str, object]],
    modular_trades: Sequence[Mapping[str, object]],
    legacy_equity: Sequence[Mapping[str, object]],
    modular_equity: Sequence[Mapping[str, object]],
    resolved_config: Mapping[str, object],
    module_versions: Mapping[str, str],
    runtime_seconds: float,
    runtime_budget_seconds_per_year: float,
    test_evidence: Mapping[str, object],
) -> Path:
    """Publish one immutable parity run directory."""

    target = Path(run_directory)
    if target.exists():
        raise FileExistsError(target)
    validate_run_identity(identity)
    validate_exact_parity(
        legacy_trades,
        modular_trades,
        legacy_equity=legacy_equity,
        modular_equity=modular_equity,
        legacy_metrics=legacy_metrics,
        modular_metrics=modular_metrics,
    )
    if not resolved_config:
        raise ValueError("resolved config is required")
    if dict(module_versions) != V2_MODULE_VERSIONS:
        raise ValueError("v2 modular module versions mismatch")
    period = resolved_config.get("period")
    if not isinstance(period, Mapping):
        raise ValueError("resolved config period is required")
    period_years = (
        pd.Timestamp(period.get("end")) - pd.Timestamp(period.get("start"))
    ).total_seconds() / (365.2425 * 24 * 60 * 60)
    if runtime_seconds <= 0 or period_years <= 0 or runtime_budget_seconds_per_year <= 0:
        raise ValueError("invalid runtime evidence")
    seconds_per_year = runtime_seconds / period_years
    if seconds_per_year > runtime_budget_seconds_per_year:
        raise ValueError("parity runtime budget exceeded")
    tests = dict(test_evidence)
    if (
        not isinstance(tests.get("command"), str)
        or not tests["command"]
        or not isinstance(tests.get("passed"), int)
        or tests["passed"] <= 0
        or tests.get("git_revision") != identity["git_revision"]
    ):
        raise ValueError("invalid test evidence")

    target.mkdir(parents=True, exist_ok=False)
    artifact_rows = {
        "legacy-trades.parquet": legacy_trades,
        "modular-trades.parquet": modular_trades,
        "legacy-equity.parquet": legacy_equity,
        "modular-equity.parquet": modular_equity,
    }
    for filename, rows in artifact_rows.items():
        write_parquet([dict(row) for row in rows], target / filename)

    canonical_config = json.dumps(
        resolved_config,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    summary = {
        "schema_version": "decision-engine-parity/v2",
        "run_id": target.name,
        "baseline_template_id": "legacy_nfe_v2",
        "candidate_template_id": "v2_modular",
        "identity": dict(identity),
        "resolved_config": dict(resolved_config),
        "resolved_config_sha256": hashlib.sha256(
            canonical_config.encode("utf-8")
        ).hexdigest(),
        "module_versions": dict(module_versions),
        "metrics": dict(modular_metrics),
        "artifacts": {
            filename: hashlib.sha256((target / filename).read_bytes()).hexdigest()
            for filename in artifact_rows
        },
        "verification": {
            "runtime": {
                "seconds": round(runtime_seconds, 2),
                "period_years": round(period_years, 6),
                "seconds_per_year": round(seconds_per_year, 2),
                "budget_seconds_per_year": runtime_budget_seconds_per_year,
            },
            "tests": tests,
        },
        "exact_parity": True,
    }
    summary_path = target / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return summary_path


def validate_exact_parity(
    legacy_trades: Sequence[Mapping[str, object]],
    modular_trades: Sequence[Mapping[str, object]],
    *,
    legacy_equity: Sequence[Mapping[str, object]] = (),
    modular_equity: Sequence[Mapping[str, object]] = (),
    legacy_metrics: Mapping[str, object] | None = None,
    modular_metrics: Mapping[str, object] | None = None,
) -> None:
    """Refuse a candidate whose entry-time/side identity differs."""

    def entry_identity(trades: Sequence[Mapping[str, object]]) -> Counter:
        return Counter(
            (str(trade["entry_time"]), str(trade["type"]).lower())
            for trade in trades
        )

    legacy_entries = entry_identity(legacy_trades)
    modular_entries = entry_identity(modular_trades)
    if legacy_entries != modular_entries:
        def bounded(counter: Counter) -> list[dict[str, object]]:
            return [
                {"entry_time": entry_time, "side": side, "count": count}
                for (entry_time, side), count in sorted(counter.items())[:20]
            ]

        detail = {
            "legacy_count": sum(legacy_entries.values()),
            "modular_count": sum(modular_entries.values()),
            "shared_count": sum((legacy_entries & modular_entries).values()),
            "legacy_only": bounded(legacy_entries - modular_entries),
            "modular_only": bounded(modular_entries - legacy_entries),
        }
        raise ValueError(
            "entry-time/side exact parity mismatch: "
            + json.dumps(detail, sort_keys=True, separators=(",", ":"))
        )
    if list(legacy_trades) != list(modular_trades):
        raise ValueError("trade ledger exact parity mismatch")
    realized = lambda rows: [
        row for row in rows if row.get("mark_source") == "realized_balance"
    ]
    if realized(legacy_equity) != realized(modular_equity):
        raise ValueError("realized equity exact parity mismatch")
    if legacy_metrics != modular_metrics:
        raise ValueError("headline metrics exact parity mismatch")
    if legacy_metrics is not None and legacy_metrics != FROZEN_BASELINE_METRICS:
        raise ValueError("frozen legacy headline metrics mismatch")
    if legacy_metrics is not None:
        entries = [
            {"entry_time": entry_time, "side": side}
            for (entry_time, side), count in sorted(legacy_entries.items())
            for _ in range(count)
        ]
        digest = hashlib.sha256(
            json.dumps(
                entries,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if digest != FROZEN_BASELINE_ENTRY_IDENTITY_SHA256:
            raise ValueError("frozen legacy entry identity mismatch")


if __name__ == "__main__":
    main()
