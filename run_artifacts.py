from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path, PurePosixPath
import re


RUN_SCHEMA_VERSION = "run-artifact/v1"
METRICS_SCHEMA_VERSION = "metrics/v1"
CANONICAL_METRICS = (
    "return_pct",
    "max_drawdown_pct",
    "trades",
    "win_rate_pct",
    "profit_factor",
    "final_balance",
)
SUMMARY_FIELDS = {
    "schema_version",
    "metrics_version",
    "run_id",
    "created_at",
    "provenance",
    "verdict",
    "profile",
    "results",
    "warnings",
    "baseline",
    "artifacts",
}
RESULT_FIELDS = {
    "strategy",
    "period",
    "start",
    "end",
    "metrics",
    "baseline_deltas",
}


def canonical_artifact_references() -> dict[str, dict[str, object]]:
    return {
        "manifest": {"available": True, "path": "manifest.json"},
        "summary": {"available": True, "path": "summary.json"},
        "summary_markdown": {"available": True, "path": "summary.md"},
        "review": {"available": True, "path": "review.md"},
        "trades": {"available": True, "path": "trades.parquet"},
        "equity": {"available": True, "path": "equity.parquet"},
        "diagnostics": {"available": True, "path": "diagnostics.parquet"},
        "log": {"available": True, "path": "run.log"},
        "orders": {"available": False, "path": None, "reason": "not produced"},
    }


def create_run_directory(path: str | Path) -> Path:
    run_directory = Path(path)
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def validate_run_id(run_id: object) -> None:
    if not isinstance(run_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id
    ):
        raise ValueError("invalid run_id")


def validate_run_manifest(manifest: dict) -> None:
    required = (
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
    )
    for key in required:
        if key not in manifest:
            raise ValueError(f"manifest missing {key}")
    if manifest["schema_version"] != RUN_SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    if manifest["metrics_version"] != METRICS_SCHEMA_VERSION:
        raise ValueError("unsupported metrics_version")
    validate_run_id(manifest["run_id"])

    created_at = _aware_datetime(manifest["created_at"], "created_at")
    del created_at
    nested_required = {
        "strategy": ("name", "config_id"),
        "data": ("snapshot_id", "content_sha256", "market_type", "symbol"),
        "git": ("revision",),
        "period": ("start", "end"),
        "assumptions": ("costs", "leverage"),
    }
    for section, fields in nested_required.items():
        value = manifest[section]
        if not isinstance(value, dict):
            raise ValueError(f"invalid {section}")
        for field in fields:
            if field not in value:
                raise ValueError(f"{section} missing {field}")
            if section not in {"period", "assumptions"} and not value[field]:
                raise ValueError(f"invalid {section}.{field}")
    if not manifest["assumptions"]["costs"] or not manifest["assumptions"]["leverage"]:
        raise ValueError("invalid assumptions")
    _validate_sha256(manifest["data"]["content_sha256"], "data.content_sha256")

    start = _aware_datetime(manifest["period"]["start"], "period start")
    end = _aware_datetime(manifest["period"]["end"], "period end")
    if start >= end:
        raise ValueError("invalid period")
    _validate_artifact_references(manifest["artifacts"])


def validate_compact_summary(summary: dict) -> None:
    unknown = set(summary) - SUMMARY_FIELDS
    if unknown:
        raise ValueError(f"unknown summary field: {sorted(unknown)[0]}")
    if summary.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    if summary.get("metrics_version") != METRICS_SCHEMA_VERSION:
        raise ValueError("unsupported metrics_version")
    validate_run_id(summary.get("run_id"))
    _aware_datetime(summary.get("created_at"), "created_at")
    for field in ("verdict", "profile"):
        if field in summary and (
            not isinstance(summary[field], str)
            or not summary[field]
            or len(summary[field]) > 200
        ):
            raise ValueError(f"invalid {field}")
    warnings = summary.get("warnings", [])
    if (
        not isinstance(warnings, list)
        or len(warnings) > 5
        or any(not isinstance(item, str) or not item or len(item) > 500 for item in warnings)
    ):
        raise ValueError("invalid warnings")
    _validate_compact_provenance(summary.get("provenance"))
    _validate_artifact_references(summary.get("artifacts"))
    if "baseline" in summary:
        _validate_baseline(summary["baseline"])
    results = _summary_results(summary)
    for result in results:
        unknown = set(result) - RESULT_FIELDS if isinstance(result, dict) else set()
        if unknown:
            raise ValueError(f"unknown result field: {sorted(unknown)[0]}")
        if not isinstance(result, dict):
            raise ValueError("invalid result")
        for field in ("strategy", "period"):
            if (
                not isinstance(result.get(field), str)
                or not result[field]
                or len(result[field]) > 200
            ):
                raise ValueError(f"invalid result {field}")
        start = _aware_datetime(result.get("start"), "result start")
        end = _aware_datetime(result.get("end"), "result end")
        if start >= end:
            raise ValueError("invalid result period")
        metrics = result.get("metrics") if isinstance(result, dict) else None
        if not isinstance(metrics, dict):
            raise ValueError("result missing metrics")
        for metric in CANONICAL_METRICS:
            if metric not in metrics:
                raise ValueError(f"metrics missing {metric}")
        _validate_metrics(metrics)
        if "baseline_deltas" in result:
            _validate_baseline_deltas(result["baseline_deltas"])
    _reject_embedded_records(
        {key: value for key, value in summary.items() if key != "artifacts"}
    )


def validate_run_artifact(manifest: dict, summary: dict) -> None:
    validate_run_manifest(manifest)
    validate_compact_summary(summary)
    if manifest["run_id"] != summary["run_id"]:
        raise ValueError("manifest and summary run_id mismatch")
    if manifest["created_at"] != summary["created_at"]:
        raise ValueError("manifest and summary created_at mismatch")
    for section in ("strategy", "data", "git", "period", "assumptions"):
        if manifest[section] != summary["provenance"][section]:
            raise ValueError(f"manifest and summary {section} mismatch")


def render_summary_markdown(summary: dict) -> str:
    validate_compact_summary(summary)
    rows = [
        "| Strategy | Period | Return % | MDD % | Trades | Win rate % | Profit factor | Final balance |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in _summary_results(summary):
        metrics = result["metrics"]
        rows.append(
            f"| {result.get('strategy', '')} | {result.get('period', '')} | "
            f"{metrics['return_pct']} | {metrics['max_drawdown_pct']} | "
            f"{metrics['trades']} | {metrics['win_rate_pct']} | "
            f"{metrics['profit_factor']} | {metrics['final_balance']} |"
        )
    return (
        "# Run summary\n\n"
        f"Run ID: `{summary['run_id']}`\n\n"
        + "\n".join(rows)
        + "\n"
        + _render_warnings(summary)
    )


def render_review_markdown(summary: dict) -> str:
    validate_compact_summary(summary)
    return (
        "# Review\n\n"
        f"Run ID: `{summary['run_id']}`\n\n"
        f"Verdict: **{summary.get('verdict', 'unreviewed')}**.\n"
        + _render_warnings(summary)
    )


def _render_warnings(summary: dict) -> str:
    warnings = summary.get("warnings", [])
    if not warnings:
        return ""
    return "\n## Warnings\n\n" + "".join(f"- {warning}\n" for warning in warnings)


def _summary_results(summary: dict) -> list[dict]:
    results = summary.get("results")
    if isinstance(results, list) and results:
        return results
    raise ValueError("summary requires results")


def _validate_compact_provenance(provenance: object) -> None:
    if not isinstance(provenance, dict):
        raise ValueError("summary missing provenance")
    fields = {
        "strategy": {"name", "config_id"},
        "data": {"snapshot_id", "content_sha256", "market_type", "symbol"},
        "git": {"revision"},
        "period": {"start", "end"},
        "assumptions": {"costs", "leverage"},
    }
    if set(provenance) != set(fields):
        difference = set(fields).symmetric_difference(provenance)
        raise ValueError(f"invalid provenance section: {sorted(difference)[0]}")
    for section, expected in fields.items():
        value = provenance.get(section)
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError(f"invalid provenance {section}")
    for section in ("strategy", "data", "git"):
        if any(
            not isinstance(value, str) or not value or len(value) > 500
            for value in provenance[section].values()
        ):
            raise ValueError(f"invalid provenance {section}")
    assumptions = provenance["assumptions"]
    for values in (assumptions["costs"], assumptions["leverage"]):
        if not isinstance(values, dict) or not values or any(
            not _is_compact_scalar(item) for item in values.values()
        ):
            raise ValueError("invalid provenance assumptions")
    validate_run_manifest(
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "metrics_version": METRICS_SCHEMA_VERSION,
            "run_id": "provenance-validation",
            "created_at": "1970-01-01T00:00:00+00:00",
            **provenance,
            "artifacts": canonical_artifact_references(),
        }
    )


def _validate_baseline(baseline: object) -> None:
    required = {"run_id", "content_sha256"}
    allowed = required | {"generated_at", "snapshot_id"}
    if not isinstance(baseline, dict) or not required <= set(baseline) or set(baseline) - allowed:
        raise ValueError("invalid baseline")
    validate_run_id(baseline["run_id"])
    _validate_sha256(baseline["content_sha256"], "baseline content_sha256")
    if "generated_at" in baseline:
        _aware_datetime(baseline["generated_at"], "baseline generated_at")
    if "snapshot_id" in baseline and (
        not isinstance(baseline["snapshot_id"], str) or not baseline["snapshot_id"]
    ):
        raise ValueError("invalid baseline snapshot_id")


def _validate_baseline_deltas(deltas: object) -> None:
    if (
        not isinstance(deltas, dict)
        or set(deltas) - set(CANONICAL_METRICS)
        or any(
            value is not None
            and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            )
            for value in deltas.values()
        )
    ):
        raise ValueError("invalid baseline_deltas")


def _is_compact_scalar(value: object) -> bool:
    return (
        value is None
        or isinstance(value, (str, bool))
        or isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"invalid {field}")


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"invalid {field}: timezone required")
    return parsed


def _reject_embedded_records(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"candles", "raw_candles", "trades", "equity", "orders"} and isinstance(
                item, (dict, list, tuple)
            ):
                raise ValueError(f"embedded {key} not allowed")
            _reject_embedded_records(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_embedded_records(item)


def _validate_metrics(metrics: dict) -> None:
    unknown = set(metrics) - set(CANONICAL_METRICS) - {"missed"}
    if unknown:
        raise ValueError(f"unknown metric: {sorted(unknown)[0]}")
    for metric in CANONICAL_METRICS:
        value = metrics[metric]
        if metric == "profit_factor" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"invalid {metric}")
        if not math.isfinite(value):
            raise ValueError(f"invalid {metric}")
    if not isinstance(metrics["trades"], int) or metrics["trades"] < 0:
        raise ValueError("invalid trades")
    if not 0 <= metrics["win_rate_pct"] <= 100:
        raise ValueError("invalid win_rate_pct")
    if metrics["profit_factor"] is not None and metrics["profit_factor"] < 0:
        raise ValueError("invalid profit_factor")
    if "missed" in metrics and (
        not isinstance(metrics["missed"], int)
        or isinstance(metrics["missed"], bool)
        or metrics["missed"] < 0
    ):
        raise ValueError("invalid missed")


def _validate_artifact_references(references: object) -> None:
    if not isinstance(references, dict):
        raise ValueError("invalid artifacts")
    for reference in references.values():
        if not isinstance(reference, dict):
            raise ValueError("invalid artifacts")
        path = reference.get("path")
        if path is not None:
            if (
                not isinstance(path, str)
                or "\\" in path
                or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
            ):
                raise ValueError("invalid artifacts path")
    if references != canonical_artifact_references():
        raise ValueError("artifacts do not match run-artifact/v1")
