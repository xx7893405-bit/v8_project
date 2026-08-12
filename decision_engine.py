"""Fail-closed, serializable contracts for the V8 Decision Engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol, Sequence


class DecisionEngineConfigError(ValueError):
    """Raised when a Decision Engine template cannot be resolved safely."""


class DecisionStage(str, Enum):
    MARKET_CONTEXT = "market_context"
    DIRECTION = "direction"
    TARGET = "target"
    EVIDENCE = "evidence"
    RISK = "risk"
    EXECUTION = "execution"
    MANAGEMENT = "management"


_COMBINE_POLICIES = frozenset(("all", "any"))
_SCORE_POLICIES = frozenset(("none", "sum", "max"))
_RESULT_STATUSES = frozenset(("passed", "rejected", "blocked"))
_MODULE_STATUSES = (
    "identified",
    "transitional",
    "implemented",
    "parity-verified",
    "deprecated",
)


def _json_serializable(value: object, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise DecisionEngineConfigError(f"{label} is not JSON serializable") from error


def _time_value(value: object) -> object:
    return value.isoformat() if callable(getattr(value, "isoformat", None)) else value


def _require_aware_datetime(value: object, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DecisionEngineConfigError(
            f"{label} must be a timezone-aware datetime"
        )
    return value


@dataclass(frozen=True)
class StageSelection:
    stage: DecisionStage
    plugin_ids: tuple[str, ...]
    enabled: bool = True
    plugin_config: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    plugin_versions: Mapping[str, str] = field(default_factory=dict)
    plugin_enabled: Mapping[str, bool] = field(default_factory=dict)
    combine_policy: str = "all"
    score_policy: str = "none"

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "plugin_ids": list(self.plugin_ids),
            "enabled": self.enabled,
            "plugin_config": dict(self.plugin_config),
            "plugin_versions": dict(self.plugin_versions),
            "plugin_enabled": dict(self.plugin_enabled),
            "combine_policy": self.combine_policy,
            "score_policy": self.score_policy,
        }


@dataclass(frozen=True)
class PluginMetadata:
    plugin_id: str
    version: str
    stage: DecisionStage
    capability: str
    status: str = "implemented"
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    available_at: str = "signal_time"
    time_safe: bool = True
    profile: str = "default"
    requirements: tuple[str, ...] = ()
    config_fields: tuple[str, ...] = ()
    required_config_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "module_id": self.plugin_id,
            "plugin_id": self.plugin_id,
            "version": self.version,
            "stage": self.stage.value,
            "capability": self.capability,
            "status": self.status,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "conflicts": list(self.conflicts),
            "available_at": self.available_at,
            "time_safe": self.time_safe,
            "profile": self.profile,
            "requirements": list(self.requirements),
            "config_fields": list(self.config_fields),
            "required_config_fields": list(self.required_config_fields),
        }


@dataclass(frozen=True)
class DecisionContext:
    signal_time: datetime
    market: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginResult:
    plugin_id: str
    stage: DecisionStage
    status: str
    reason_codes: tuple[str, ...] = ()
    facts: Mapping[str, object] = field(default_factory=dict)
    score_contribution: float = 0.0
    available_at: datetime | None = None
    time_safe: bool = False
    profile: str = ""
    requirements: tuple[str, ...] = ()

    @classmethod
    def passed(
        cls,
        plugin_id: str,
        stage: DecisionStage,
        *reason_codes: str,
        available_at: object,
        profile: str,
        requirements: tuple[str, ...] = (),
        facts: Mapping[str, object] | None = None,
        score_contribution: float = 0.0,
    ) -> "PluginResult":
        return cls(
            plugin_id=plugin_id,
            stage=stage,
            status="passed",
            reason_codes=reason_codes,
            facts=facts or {},
            score_contribution=score_contribution,
            available_at=available_at,
            time_safe=True,
            profile=profile,
            requirements=requirements,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "stage": self.stage.value,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "facts": dict(self.facts),
            "score_contribution": self.score_contribution,
            "available_at": _time_value(self.available_at),
            "time_safe": self.time_safe,
            "profile": self.profile,
            "requirements": list(self.requirements),
        }


class DecisionPlugin(Protocol):
    metadata: PluginMetadata

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        ...


@dataclass(frozen=True)
class DecisionTemplate:
    template_id: str
    version: str
    stages: tuple[StageSelection, ...]
    profile: str = "default"

    def to_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "profile": self.profile,
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass(frozen=True)
class StageResult:
    stage: DecisionStage
    status: str
    score: float
    combine_policy: str
    score_policy: str
    plugin_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "status": self.status,
            "score": self.score,
            "combine_policy": self.combine_policy,
            "score_policy": self.score_policy,
            "plugin_ids": list(self.plugin_ids),
        }


@dataclass(frozen=True)
class PipelineResult:
    plugin_results: tuple[PluginResult, ...]
    stage_results: tuple[StageResult, ...] = ()

    def __post_init__(self) -> None:
        if not self.plugin_results:
            raise DecisionEngineConfigError("empty pipeline result")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            reason_code
            for result in self.plugin_results
            for reason_code in result.reason_codes
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_results": [result.to_dict() for result in self.plugin_results],
            "stage_results": [result.to_dict() for result in self.stage_results],
        }


class PluginRegistry:
    """Resolves a complete template without fallback providers or configuration."""

    def __init__(
        self,
        plugins: Mapping[str, PluginMetadata | DecisionPlugin] | None = None,
    ) -> None:
        self._plugins: dict[str, PluginMetadata | DecisionPlugin] = {}
        registered_ids: set[str] = set()
        resolved: list[tuple[str, PluginMetadata | DecisionPlugin, PluginMetadata]] = []
        for key, plugin in (plugins or {}).items():
            metadata = plugin if isinstance(plugin, PluginMetadata) else getattr(plugin, "metadata", None)
            if not isinstance(metadata, PluginMetadata):
                raise DecisionEngineConfigError(f"invalid plugin metadata: {key}")
            if metadata.plugin_id in registered_ids:
                raise DecisionEngineConfigError(f"duplicate plugin id: {metadata.plugin_id}")
            registered_ids.add(metadata.plugin_id)
            resolved.append((key, plugin, metadata))
        for key, plugin, metadata in resolved:
            if key != metadata.plugin_id:
                raise DecisionEngineConfigError(
                    f"plugin id mismatch: registry key {key}, metadata {metadata.plugin_id}"
                )
            self._validate_metadata(metadata)
            self._plugins[key] = plugin
    @staticmethod
    def _validate_metadata(metadata: PluginMetadata) -> None:
        if not metadata.plugin_id or not metadata.version:
            raise DecisionEngineConfigError("plugin id and version are required")
        if not isinstance(metadata.stage, DecisionStage):
            raise DecisionEngineConfigError(f"invalid plugin stage: {metadata.plugin_id}")
        if not metadata.capability:
            raise DecisionEngineConfigError(f"missing plugin capability: {metadata.plugin_id}")
        if metadata.status not in _MODULE_STATUSES:
            raise DecisionEngineConfigError(f"invalid plugin status: {metadata.plugin_id}")
        if not metadata.available_at or not metadata.time_safe:
            raise DecisionEngineConfigError(f"unsafe plugin metadata: {metadata.plugin_id}")
        if not metadata.profile:
            raise DecisionEngineConfigError(f"missing plugin profile: {metadata.plugin_id}")
        if len(set(metadata.requirements)) != len(metadata.requirements):
            raise DecisionEngineConfigError(f"duplicate plugin requirement: {metadata.plugin_id}")
        if metadata.plugin_id in metadata.requirements:
            raise DecisionEngineConfigError(f"circular plugin requirements: {metadata.plugin_id}")
        allowed = set(metadata.config_fields)
        required = set(metadata.required_config_fields)
        if len(allowed) != len(metadata.config_fields) or len(required) != len(metadata.required_config_fields):
            raise DecisionEngineConfigError(f"duplicate config field: {metadata.plugin_id}")
        if not required <= allowed:
            raise DecisionEngineConfigError(f"invalid required config field: {metadata.plugin_id}")

    def resolve_template(self, template: DecisionTemplate) -> DecisionTemplate:
        if not isinstance(template, DecisionTemplate) or not template.template_id or not template.version:
            raise DecisionEngineConfigError("invalid decision template")
        if not template.profile:
            raise DecisionEngineConfigError("missing template profile")

        seen_stages: set[DecisionStage] = set()
        selected: dict[str, bool] = {}
        active_order: list[str] = []
        for selection in template.stages:
            if not isinstance(selection.stage, DecisionStage):
                raise DecisionEngineConfigError("invalid stage selection")
            if selection.stage in seen_stages:
                raise DecisionEngineConfigError(f"duplicate stage: {selection.stage.value}")
            seen_stages.add(selection.stage)
            self._validate_selection(selection)
            if not selection.enabled:
                raise DecisionEngineConfigError(f"disabled stage: {selection.stage.value}")
            if not selection.plugin_ids:
                raise DecisionEngineConfigError(f"empty stage: {selection.stage.value}")
            if not any(selection.plugin_enabled.get(plugin_id, True) for plugin_id in selection.plugin_ids):
                raise DecisionEngineConfigError(f"empty stage: {selection.stage.value}")
            for plugin_id in selection.plugin_ids:
                if plugin_id in selected:
                    raise DecisionEngineConfigError(f"duplicate plugin id: {plugin_id}")
                selected[plugin_id] = selection.plugin_enabled.get(plugin_id, True)
                if selected[plugin_id]:
                    active_order.append(plugin_id)
                self._validate_plugin_reference(template, selection, plugin_id)

        for stage in DecisionStage:
            if stage not in seen_stages:
                raise DecisionEngineConfigError(f"missing stage: {stage.value}")
        self._validate_dependencies(selected, active_order)
        self._validate_conflicts(active_order)
        return template

    @staticmethod
    def _validate_selection(selection: StageSelection) -> None:
        if not isinstance(selection.enabled, bool):
            raise DecisionEngineConfigError(f"invalid stage enabled flag: {selection.stage.value}")
        if selection.combine_policy not in _COMBINE_POLICIES:
            raise DecisionEngineConfigError(f"invalid combine policy: {selection.combine_policy}")
        if selection.score_policy not in _SCORE_POLICIES:
            raise DecisionEngineConfigError(f"invalid score policy: {selection.score_policy}")
        selected = set(selection.plugin_ids)
        for config_map, label in (
            (selection.plugin_config, "plugin config"),
            (selection.plugin_versions, "plugin version"),
            (selection.plugin_enabled, "plugin enabled"),
        ):
            if not isinstance(config_map, Mapping) or not set(config_map) <= selected:
                raise DecisionEngineConfigError(f"unknown {label} provider")
        if any(not isinstance(enabled, bool) for enabled in selection.plugin_enabled.values()):
            raise DecisionEngineConfigError("invalid plugin enabled flag")

    def _validate_plugin_reference(
        self,
        template: DecisionTemplate,
        selection: StageSelection,
        plugin_id: str,
    ) -> None:
        if plugin_id not in self._plugins:
            raise DecisionEngineConfigError(f"unknown plugin: {plugin_id}")
        metadata = self.metadata_for(plugin_id)
        if metadata.stage is not selection.stage:
            raise DecisionEngineConfigError(
                f"stage mismatch: {plugin_id} is {metadata.stage.value}, not {selection.stage.value}"
            )
        if metadata.profile != template.profile:
            raise DecisionEngineConfigError(
                f"plugin profile mismatch: {plugin_id} is {metadata.profile}, not {template.profile}"
            )
        expected_version = selection.plugin_versions.get(plugin_id)
        if expected_version is not None and metadata.version != expected_version:
            raise DecisionEngineConfigError(
                f"plugin version mismatch: {plugin_id} is {metadata.version}, expected {expected_version}"
            )
        config = selection.plugin_config.get(plugin_id, {})
        if not isinstance(config, Mapping):
            raise DecisionEngineConfigError(f"invalid plugin config: {plugin_id}")
        unknown = set(config) - set(metadata.config_fields)
        if unknown:
            raise DecisionEngineConfigError(f"unknown config field: {plugin_id}.{sorted(unknown)[0]}")
        missing = set(metadata.required_config_fields) - set(config)
        if missing:
            raise DecisionEngineConfigError(
                f"missing required config field: {plugin_id}.{sorted(missing)[0]}"
            )
        _json_serializable(dict(config), f"plugin config: {plugin_id}")

    def _validate_dependencies(self, selected: Mapping[str, bool], active_order: Sequence[str]) -> None:
        active = set(active_order)
        for plugin_id in active_order:
            for provider in self.metadata_for(plugin_id).requirements:
                if provider not in selected:
                    raise DecisionEngineConfigError(f"missing required provider: {provider}")
                if not selected[provider]:
                    raise DecisionEngineConfigError(f"disabled required provider: {provider}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visiting:
                raise DecisionEngineConfigError(f"circular plugin requirements: {plugin_id}")
            if plugin_id in visited:
                return
            visiting.add(plugin_id)
            for provider in self.metadata_for(plugin_id).requirements:
                if provider in active:
                    visit(provider)
            visiting.remove(plugin_id)
            visited.add(plugin_id)

        for plugin_id in active_order:
            visit(plugin_id)
        positions = {plugin_id: position for position, plugin_id in enumerate(active_order)}
        for plugin_id in active_order:
            for provider in self.metadata_for(plugin_id).requirements:
                if positions[provider] >= positions[plugin_id]:
                    raise DecisionEngineConfigError(
                        f"required provider is not upstream: {provider} before {plugin_id}"
                    )

    def _validate_conflicts(self, active_order: Sequence[str]) -> None:
        active = set(active_order)
        for plugin_id in active_order:
            for conflict in self.metadata_for(plugin_id).conflicts:
                if conflict in active:
                    raise DecisionEngineConfigError(
                        f"conflicting plugins: {plugin_id} and {conflict}"
                    )

    def metadata_for(self, plugin_id: str) -> PluginMetadata:
        plugin = self._plugins[plugin_id]
        return plugin if isinstance(plugin, PluginMetadata) else plugin.metadata

    def plugin_for(self, plugin_id: str) -> DecisionPlugin:
        plugin = self._plugins[plugin_id]
        if isinstance(plugin, PluginMetadata):
            raise DecisionEngineConfigError(f"plugin is not executable: {plugin_id}")
        return plugin

    def catalog(self) -> dict[str, object]:
        counts = {status: 0 for status in _MODULE_STATUSES}
        modules = []
        for plugin_id in sorted(self._plugins):
            metadata = self.metadata_for(plugin_id)
            counts[metadata.status] += 1
            modules.append(metadata.to_dict())
        return {
            "schema": "strategy-module-catalog/v1",
            "counts": counts,
            "modules": modules,
        }


class DecisionPipeline:
    """Evaluates resolved, time-safe plugins in fixed market-decision order."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        template: DecisionTemplate,
        context: DecisionContext,
    ) -> PipelineResult:
        _require_aware_datetime(context.signal_time, "signal_time")
        self._registry.resolve_template(template)
        selections = {selection.stage: selection for selection in template.stages}
        results: list[PluginResult] = []
        stage_results: list[StageResult] = []
        for stage in DecisionStage:
            selection = selections[stage]
            current_stage_results: list[PluginResult] = []
            for plugin_id in selection.plugin_ids:
                if not selection.plugin_enabled.get(plugin_id, True):
                    continue
                plugin = self._registry.plugin_for(plugin_id)
                config = dict(selection.plugin_config.get(plugin_id, {}))
                result = plugin.evaluate(context, tuple(results), config)
                self._validate_result(plugin_id, stage, context, result)
                results.append(result)
                current_stage_results.append(result)
            stage_results.append(
                self._summarize_stage(selection, current_stage_results)
            )
        return PipelineResult(
            plugin_results=tuple(results),
            stage_results=tuple(stage_results),
        )

    @staticmethod
    def _summarize_stage(
        selection: StageSelection,
        results: Sequence[PluginResult],
    ) -> StageResult:
        statuses = tuple(result.status for result in results)
        if selection.combine_policy == "all":
            status = (
                "passed"
                if all(value == "passed" for value in statuses)
                else "blocked"
                if "blocked" in statuses
                else "rejected"
            )
        else:
            status = (
                "passed"
                if "passed" in statuses
                else "blocked"
                if "blocked" in statuses
                else "rejected"
            )

        scores = tuple(result.score_contribution for result in results)
        if selection.score_policy == "sum":
            score = sum(scores)
        elif selection.score_policy == "max":
            score = max(scores)
        else:
            score = 0.0
        return StageResult(
            stage=selection.stage,
            status=status,
            score=score,
            combine_policy=selection.combine_policy,
            score_policy=selection.score_policy,
            plugin_ids=tuple(result.plugin_id for result in results),
        )

    def _validate_result(
        self,
        plugin_id: str,
        stage: DecisionStage,
        context: DecisionContext,
        result: PluginResult,
    ) -> None:
        metadata = self._registry.metadata_for(plugin_id)
        if not isinstance(result, PluginResult):
            raise DecisionEngineConfigError(f"invalid plugin result: {plugin_id}")
        if result.plugin_id != plugin_id:
            raise DecisionEngineConfigError(
                f"plugin result id mismatch: {result.plugin_id}, expected {plugin_id}"
            )
        if result.stage is not stage:
            raise DecisionEngineConfigError(
                f"plugin result stage mismatch: {plugin_id} returned {result.stage.value}, expected {stage.value}"
            )
        if result.status not in _RESULT_STATUSES:
            raise DecisionEngineConfigError(f"invalid plugin result status: {plugin_id}")
        if not result.time_safe or result.available_at is None:
            raise DecisionEngineConfigError(f"unsafe plugin result: {plugin_id}")
        if result.profile != metadata.profile:
            raise DecisionEngineConfigError(f"plugin result profile mismatch: {plugin_id}")
        if result.requirements != metadata.requirements:
            raise DecisionEngineConfigError(f"plugin result requirements mismatch: {plugin_id}")
        _json_serializable(dict(result.facts), f"plugin result facts: {plugin_id}")
        available_at = _require_aware_datetime(result.available_at, "available_at")
        is_future = available_at > context.signal_time
        if is_future:
            raise DecisionEngineConfigError(f"future plugin result: {plugin_id}")
