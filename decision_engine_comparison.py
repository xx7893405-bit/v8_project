"""Fail-closed, compact comparison artifacts for Decision Engine templates.

This module only validates already-produced template summaries.  It deliberately
does not import strategy or market-data code, and cannot run a backtest.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Mapping, Sequence


COMPARISON_SCHEMA_VERSION = "decision-engine-comparison/v2"
BACKTEST_ENGINE_CONTRACT_ID = "backtest-engine/v1"
BASELINE_TEMPLATE_ID = "nfe_v2_compatible"
LEGACY_BASELINE_ID = "legacy_nfe_v2"
FROZEN_BASELINE_IDENTITY = {
    "data_sha256": "5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965",
    "snapshot_fingerprint": "ea28b7ca3c90c46b",
    "mdd_convention": "realized_only",
    "engine_contract_id": BACKTEST_ENGINE_CONTRACT_ID,
}
FROZEN_BASELINE_METRICS = {
    "return_pct": 210.022,
    "max_drawdown_pct": -36.5982,
    "trades": 89,
    "win_rate_pct": 40.4494,
    "profit_factor": 1.8393,
    "final_balance": 31_002.20,
}
FROZEN_BASELINE_ENTRY_IDENTITY_SHA256 = (
    "4104f109962bb0ce2a6898c86c215f65fe0f6a8678a814b96b29ac56f27ab863"
)
FROZEN_BASELINE_SOURCE_IDENTITY = {
    "summary_sha256": "3322dfc9c41dd4bb6c4d70e75e2e8bbd91bf748b4a9155fda7197101580dda5f",
    "trades_sha256": "89f3473ef609975d5c6751d00cade9fb97d6e66648db1d097883be822fa21b6c",
}
HEADLINE_METRICS = (
    "return_pct",
    "max_drawdown_pct",
    "trades",
    "win_rate_pct",
    "profit_factor",
    "final_balance",
)
_SUMMARY_FIELDS = {
    "template",
    "identity",
    "reason_code_funnel",
    "metrics",
    "entry_time_sides",
    "artifact_refs",
}
_TEMPLATE_FIELDS = {"id", "version", "resolved_config", "config_hash", "plugins"}
_IDENTITY_FIELDS = {
    "snapshot_id",
    "data_sha256",
    "snapshot_fingerprint",
    "git_revision",
    "period",
    "execution_config_hash",
    "cost_model_hash",
    "mdd_convention",
    "engine_contract_id",
}
_REQUIRED_ARTIFACT_REFS = {"summary", "trades", "equity"}


def publish_template_comparison(
    run_directory: str | Path,
    *,
    run_id: str,
    baseline_summary: Mapping[str, object],
    template_summaries: Sequence[Mapping[str, object]],
    artifact_identities: Mapping[str, str] | None = None,
    artifact_directory: str | Path | None = None,
    frozen_source_directory: str | Path | None = None,
) -> Path:
    """Validate summaries and publish one immutable, compact comparison JSON.

    ``baseline_summary`` is the frozen legacy NFE V2 result.  The named
    ``nfe_v2_compatible`` template must reproduce its headline metrics and the
    full multiset of entry-time/side identities before any artifact is written.
    """

    _validate_run_id(run_id)
    target = Path(run_directory)
    if target.exists():
        raise FileExistsError(f"comparison run directory already exists: {target}")

    if artifact_directory is None:
        raise ValueError("artifact_directory is required")
    artifact_identities = _artifact_file_identities(
        artifact_directory, (baseline_summary, *template_summaries)
    )

    artifact = build_template_comparison(
        run_id=run_id,
        baseline_summary=baseline_summary,
        template_summaries=template_summaries,
        artifact_identities=artifact_identities,
    )
    artifact["baseline"]["frozen_source_identity"] = _validated_frozen_source_identity(
        frozen_source_directory
    )
    _validate_ledgers(
        artifact_directory, (baseline_summary, *template_summaries)
    )
    payload = _canonical_json(artifact)

    target.mkdir(parents=True, exist_ok=False)
    artifact_path = target / "template-comparison.json"
    try:
        artifact_path.write_text(payload + "\n", encoding="utf-8")
    except BaseException:
        # A failed publication must not leave a partly-published target that
        # looks reusable; only the empty directory created by this invocation
        # can be removed safely.
        target.rmdir()
        raise
    return artifact_path


def build_template_comparison(
    *,
    run_id: str,
    baseline_summary: Mapping[str, object],
    template_summaries: Sequence[Mapping[str, object]],
    artifact_identities: Mapping[str, str],
) -> dict[str, object]:
    """Return the artifact payload without any filesystem write."""

    _validate_run_id(run_id)
    identities = _validated_artifact_identities(artifact_identities)
    baseline = _validated_summary(baseline_summary, role="baseline", identities=identities)
    if baseline["template"]["id"] != LEGACY_BASELINE_ID:
        raise ValueError(f"baseline template id must be {LEGACY_BASELINE_ID}")
    if (
        any(
            baseline["identity"][field] != value
            for field, value in FROZEN_BASELINE_IDENTITY.items()
        )
        or baseline["metrics"] != FROZEN_BASELINE_METRICS
    ):
        raise ValueError("frozen legacy baseline identity or metrics mismatch")
    baseline_entries = _entry_counter(baseline["entry_time_sides"])
    baseline_digest = _entry_identity_sha256(baseline_entries)
    if baseline_digest != FROZEN_BASELINE_ENTRY_IDENTITY_SHA256:
        raise ValueError("frozen legacy entry identity mismatch")
    summaries = [
        _validated_summary(summary, role="template", identities=identities)
        for summary in template_summaries
    ]
    if not summaries:
        raise ValueError("comparison requires template summaries")

    template_ids = [summary["template"]["id"] for summary in summaries]
    if len(template_ids) != len(set(template_ids)):
        raise ValueError("duplicate template id")
    try:
        compatible_index = template_ids.index(BASELINE_TEMPLATE_ID)
    except ValueError as error:
        raise ValueError(f"missing required template: {BASELINE_TEMPLATE_ID}") from error

    _require_same_identity(baseline, summaries)
    compatible = summaries[compatible_index]
    _require_nfe_v2_parity(baseline, compatible)

    compact_templates = [
        _compact_template(summary, baseline_entries, baseline_digest) for summary in summaries
    ]
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "run_id": run_id,
        "baseline_template_id": LEGACY_BASELINE_ID,
        "identity": deepcopy(baseline["identity"]),
        "baseline": {
            "template": deepcopy(baseline["template"]),
            "metrics": deepcopy(baseline["metrics"]),
            "entry_identity_sha256": baseline_digest,
            "artifact_identity": deepcopy(baseline["artifact_refs"]["summary"]),
            "ledger_identity": {
                "trades": deepcopy(baseline["artifact_refs"]["trades"]),
                "equity": deepcopy(baseline["artifact_refs"]["equity"]),
            },
        },
        "templates": compact_templates,
    }


def _validated_summary(
    summary: Mapping[str, object], *, role: str, identities: Mapping[str, str]
) -> dict[str, object]:
    if not isinstance(summary, Mapping) or set(summary) != _SUMMARY_FIELDS:
        raise ValueError(f"invalid {role} summary fields")
    result = {key: deepcopy(value) for key, value in summary.items()}
    _validate_template(result["template"])
    _validate_identity(result["identity"])
    _validate_reason_code_funnel(result["reason_code_funnel"])
    _validate_metrics(result["metrics"])
    _validate_entry_time_sides(result["entry_time_sides"], result["metrics"])
    _validate_artifact_refs(result["artifact_refs"], result["template"]["id"], identities)
    return result


def _validate_template(template: object) -> None:
    if not isinstance(template, dict) or set(template) != _TEMPLATE_FIELDS:
        raise ValueError("invalid template identity")
    if not isinstance(template["id"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", template["id"]
    ):
        raise ValueError("invalid template id")
    if not isinstance(template["version"], str) or not template["version"]:
        raise ValueError("invalid template version")
    _validate_sha256(template["config_hash"], "template config_hash")
    resolved_config = template["resolved_config"]
    if not isinstance(resolved_config, dict) or not resolved_config:
        raise ValueError("invalid resolved config")
    try:
        resolved_config_hash = hashlib.sha256(
            _canonical_json(resolved_config).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError) as error:
        raise ValueError("invalid resolved config") from error
    if resolved_config_hash != template["config_hash"]:
        raise ValueError("resolved config hash mismatch")
    plugins = template["plugins"]
    if not isinstance(plugins, list) or not plugins:
        raise ValueError("invalid template plugins")
    plugin_pairs: set[tuple[str, str]] = set()
    for plugin in plugins:
        if not isinstance(plugin, dict) or set(plugin) != {"id", "version"}:
            raise ValueError("invalid template plugin")
        pair = (plugin.get("id"), plugin.get("version"))
        if not all(isinstance(value, str) and value for value in pair):
            raise ValueError("invalid template plugin")
        if pair in plugin_pairs:
            raise ValueError("duplicate template plugin")
        plugin_pairs.add(pair)


def _validate_identity(identity: object) -> None:
    if not isinstance(identity, dict):
        raise ValueError("invalid comparison identity")
    if identity.get("engine_contract_id") != BACKTEST_ENGINE_CONTRACT_ID:
        raise ValueError("invalid engine contract identity")
    if set(identity) != _IDENTITY_FIELDS:
        raise ValueError("invalid comparison identity")
    if not isinstance(identity["snapshot_id"], str) or not identity["snapshot_id"]:
        raise ValueError("invalid snapshot identity")
    for field in ("data_sha256", "execution_config_hash", "cost_model_hash"):
        _validate_sha256(identity[field], field)
    if not isinstance(identity["snapshot_fingerprint"], str) or not re.fullmatch(
        r"[0-9a-f]{16}", identity["snapshot_fingerprint"]
    ):
        raise ValueError("invalid snapshot_fingerprint")
    if not isinstance(identity["git_revision"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", identity["git_revision"]
    ):
        raise ValueError("invalid git_revision")
    if not isinstance(identity["mdd_convention"], str) or not identity["mdd_convention"]:
        raise ValueError("invalid mdd_convention")
    period = identity["period"]
    if not isinstance(period, dict) or set(period) != {"start", "end"}:
        raise ValueError("invalid comparison period")
    if _aware_datetime(period["start"], "period start") >= _aware_datetime(
        period["end"], "period end"
    ):
        raise ValueError("invalid comparison period")


def _validate_reason_code_funnel(funnel: object) -> None:
    if not isinstance(funnel, dict) or not funnel:
        raise ValueError("invalid reason-code funnel")
    for reason_code, count in funnel.items():
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError("invalid reason-code funnel")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("invalid reason-code funnel")


def _validate_metrics(metrics: object) -> None:
    if not isinstance(metrics, dict) or set(metrics) != set(HEADLINE_METRICS):
        raise ValueError("missing or unknown headline metrics")
    trades = metrics["trades"]
    if not isinstance(trades, int) or isinstance(trades, bool) or trades < 0:
        raise ValueError("invalid trades")
    for metric in ("return_pct", "max_drawdown_pct", "final_balance"):
        _validate_finite_number(metrics[metric], metric)
    for metric in ("win_rate_pct", "profit_factor"):
        value = metrics[metric]
        if trades == 0 and value is not None:
            raise ValueError(f"zero-trade {metric} must be null")
        if value is not None:
            _validate_finite_number(value, metric)
    if metrics["win_rate_pct"] is not None and not 0 <= metrics["win_rate_pct"] <= 100:
        raise ValueError("invalid win_rate_pct")
    if metrics["profit_factor"] is not None and metrics["profit_factor"] < 0:
        raise ValueError("invalid profit_factor")


def _validate_entry_time_sides(entries: object, metrics: object) -> None:
    if not isinstance(entries, list):
        raise ValueError("invalid entry-time/side identity")
    if len(entries) != metrics["trades"]:
        raise ValueError("entry-time/side count does not match trades")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"entry_time", "side"}:
            raise ValueError("invalid entry-time/side identity")
        _aware_datetime(entry["entry_time"], "entry_time")
        if entry["side"] not in {"long", "short"}:
            raise ValueError("invalid entry-time/side identity")


def _validate_artifact_refs(
    references: object, template_id: object, identities: Mapping[str, str]
) -> None:
    if not isinstance(references, dict) or set(references) != _REQUIRED_ARTIFACT_REFS:
        raise ValueError("invalid artifact refs")
    expected_prefix = PurePosixPath("templates") / str(template_id)
    for reference in references.values():
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise ValueError("invalid artifact refs")
        path = reference["path"]
        if not isinstance(path, str) or not path:
            raise ValueError("invalid artifact refs")
        _validate_sha256(reference["sha256"], "artifact ref sha256")
        _validated_artifact_path(path, expected_prefix)
        if identities.get(path) != reference["sha256"]:
            raise ValueError("artifact ref identity missing or mismatched")


def _artifact_file_identities(
    artifact_directory: str | Path, summaries: Sequence[Mapping[str, object]]
) -> dict[str, str]:
    root = Path(artifact_directory).resolve()
    identities: dict[str, str] = {}
    for summary in summaries:
        template = summary.get("template") if isinstance(summary, Mapping) else None
        references = summary.get("artifact_refs") if isinstance(summary, Mapping) else None
        if not isinstance(template, Mapping) or not isinstance(references, Mapping):
            raise ValueError("invalid artifact refs")
        expected_prefix = PurePosixPath("templates") / str(template.get("id"))
        for reference in references.values():
            if not isinstance(reference, Mapping):
                raise ValueError("invalid artifact refs")
            path = _validated_artifact_path(reference.get("path"), expected_prefix)
            artifact_path = _contained_artifact_path(root, path)
            if not artifact_path.is_file():
                raise ValueError(f"artifact file missing: {path}")
            identities[path] = _file_sha256(artifact_path)
    return identities


def _validated_frozen_source_identity(
    source_directory: str | Path | None,
) -> dict[str, str]:
    if source_directory is None:
        raise ValueError("frozen_source_directory is required")
    root = Path(source_directory).resolve()
    actual = {}
    for artifact_name, filename in (
        ("summary_sha256", "summary.json"),
        ("trades_sha256", "trades.json"),
    ):
        source_path = _contained_artifact_path(root, filename)
        if not source_path.is_file():
            raise ValueError(f"frozen source file missing: {filename}")
        actual[artifact_name] = _file_sha256(source_path)
    if actual != FROZEN_BASELINE_SOURCE_IDENTITY:
        raise ValueError("frozen source identity mismatch")
    return actual


def _validate_ledgers(
    artifact_directory: str | Path, summaries: Sequence[Mapping[str, object]]
) -> None:
    import duckdb

    root = Path(artifact_directory).resolve()
    connection = duckdb.connect(":memory:")
    try:
        for summary in summaries:
            template_id = summary["template"]["id"]
            expected_prefix = PurePosixPath("templates") / str(template_id)
            reference = summary["artifact_refs"]["trades"]
            path = _validated_artifact_path(reference["path"], expected_prefix)
            trade_artifact = _contained_artifact_path(root, path)
            expected_entries = _entry_counter(summary["entry_time_sides"])
            try:
                rows = connection.execute(
                    "SELECT entry_time, lower(type) FROM read_parquet(?) LIMIT ?",
                    [str(trade_artifact), sum(expected_entries.values()) + 1],
                ).fetchall()
            except Exception as error:
                raise ValueError(f"invalid trade ledger schema: {path}") from error
            actual_entries = Counter((str(entry_time), side) for entry_time, side in rows)
            if actual_entries != expected_entries:
                raise ValueError(f"trade ledger mismatch: {path}")

            equity_reference = summary["artifact_refs"]["equity"]
            equity_path = _validated_artifact_path(
                equity_reference["path"], expected_prefix
            )
            equity_artifact = _contained_artifact_path(root, equity_path)
            try:
                equity_row = connection.execute(
                    "SELECT event_time, balance, equity "
                    "FROM read_parquet(?) ORDER BY event_time DESC LIMIT 1",
                    [str(equity_artifact)],
                ).fetchone()
            except Exception as error:
                raise ValueError(
                    f"invalid equity ledger schema: {equity_path}"
                ) from error
            if equity_row is None:
                raise ValueError(f"equity ledger mismatch: {equity_path}")
            event_time, balance, equity = equity_row
            _aware_datetime(str(event_time), "equity event_time")
            _validate_finite_number(balance, "equity balance")
            _validate_finite_number(equity, "equity")
            if not math.isclose(
                balance,
                summary["metrics"]["final_balance"],
                rel_tol=0.0,
                abs_tol=0.01,
            ):
                raise ValueError(f"equity ledger mismatch: {equity_path}")
    finally:
        connection.close()


def _validated_artifact_path(path: object, expected_prefix: PurePosixPath) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("invalid artifact refs")
    parsed = PurePosixPath(path)
    if (
        "\\" in path
        or parsed.is_absolute()
        or ".." in parsed.parts
        or path != parsed.as_posix()
        or not parsed.is_relative_to(expected_prefix)
    ):
        raise ValueError("artifact refs must be canonical run-relative paths")
    return path


def _contained_artifact_path(root: Path, path: str) -> Path:
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"artifact path escapes source directory: {path}") from error
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_artifact_identities(identities: object) -> dict[str, str]:
    if not isinstance(identities, Mapping) or not identities:
        raise ValueError("invalid artifact identities")
    result: dict[str, str] = {}
    for path, digest in identities.items():
        if not isinstance(path, str) or not path:
            raise ValueError("invalid artifact identities")
        _validate_sha256(digest, "artifact identity sha256")
        result[path] = digest
    return result


def _require_same_identity(
    baseline: Mapping[str, object], summaries: Sequence[Mapping[str, object]]
) -> None:
    for summary in summaries:
        if summary["identity"] != baseline["identity"]:
            raise ValueError("snapshot/config/cost identity mismatch")


def _require_nfe_v2_parity(
    baseline: Mapping[str, object], compatible: Mapping[str, object]
) -> None:
    if compatible["metrics"] != baseline["metrics"]:
        raise ValueError("nfe_v2_compatible headline metrics mismatch")
    if _entry_counter(compatible["entry_time_sides"]) != _entry_counter(
        baseline["entry_time_sides"]
    ):
        raise ValueError("nfe_v2_compatible entry-time/side identity mismatch")


def _compact_template(
    summary: Mapping[str, object],
    baseline_entries: Counter[tuple[str, str]],
    baseline_digest: str,
) -> dict[str, object]:
    entries = _entry_counter(summary["entry_time_sides"])
    template_digest = _entry_identity_sha256(entries)
    return {
        "template": deepcopy(summary["template"]),
        "reason_code_funnel": deepcopy(summary["reason_code_funnel"]),
        "metrics": deepcopy(summary["metrics"]),
        "entry_time_side_overlap": {
            "baseline_count": sum(baseline_entries.values()),
            "template_count": sum(entries.values()),
            "shared_count": sum((baseline_entries & entries).values()),
            "exact_match": entries == baseline_entries,
            "baseline_identity_sha256": baseline_digest,
            "template_identity_sha256": template_digest,
        },
        "artifact_refs": deepcopy(summary["artifact_refs"]),
    }


def _entry_counter(entries: object) -> Counter[tuple[str, str]]:
    return Counter((entry["entry_time"], entry["side"]) for entry in entries)


def _entry_identity_sha256(entries: Counter[tuple[str, str]]) -> str:
    values = [
        {"entry_time": entry_time, "side": side}
        for (entry_time, side), count in sorted(entries.items())
        for _ in range(count)
    ]
    return hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_run_id(run_id: object) -> None:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError("invalid run_id")


def _validate_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"invalid {field}")


def _validate_finite_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
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
