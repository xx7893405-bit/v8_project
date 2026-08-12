import unittest
from datetime import datetime, timedelta, timezone

from decision_engine import (
    DecisionContext,
    DecisionEngineConfigError,
    DecisionPipeline,
    DecisionStage,
    DecisionTemplate,
    PipelineResult,
    PluginMetadata,
    PluginResult,
    PluginRegistry,
    StageSelection,
)


SIGNAL_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def plugin_id(stage):
    return f"core.{stage.value}"


def metadata_for(stage, **changes):
    values = {
        "plugin_id": plugin_id(stage),
        "version": "1",
        "stage": stage,
        "capability": stage.value,
        "available_at": "signal_time",
        "time_safe": True,
        "profile": "default",
        "requirements": (),
        "config_fields": (),
        "required_config_fields": (),
    }
    values.update(changes)
    return PluginMetadata(**values)


def complete_template(*, selections=None, **changes):
    values = {
        "template_id": "complete_template",
        "version": "1",
        "profile": "default",
        "stages": selections
        or tuple(
            StageSelection(stage=stage, plugin_ids=(plugin_id(stage),))
            for stage in DecisionStage
        ),
    }
    values.update(changes)
    return DecisionTemplate(**values)


def complete_registry(*, plugins=None):
    return PluginRegistry(
        plugins
        or {plugin_id(stage): metadata_for(stage) for stage in DecisionStage}
    )


class DecisionEngineTemplateValidationTest(unittest.TestCase):
    def test_registry_rejects_missing_capability_and_invalid_status(self):
        for metadata, diagnostic in (
            (metadata_for(DecisionStage.DIRECTION, capability=""), "missing plugin capability"),
            (metadata_for(DecisionStage.DIRECTION, status="unknown"), "invalid plugin status"),
        ):
            with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(
                DecisionEngineConfigError,
                diagnostic,
            ):
                PluginRegistry({metadata.plugin_id: metadata})

    def test_registry_catalog_is_deterministic_and_counts_module_statuses(self):
        modules = {
            "z.implemented": PluginMetadata(
                "z.implemented",
                "1",
                DecisionStage.DIRECTION,
                "trend direction",
                status="implemented",
                inputs=("ohlcv",),
                outputs=("direction",),
            ),
            "a.identified": PluginMetadata(
                "a.identified",
                "1",
                DecisionStage.TARGET,
                "liquidity target",
                status="identified",
                inputs=("swings",),
                outputs=("target",),
            ),
        }

        catalog = PluginRegistry(modules).catalog()

        self.assertEqual(catalog["schema"], "strategy-module-catalog/v1")
        self.assertEqual(
            catalog["counts"],
            {
                "identified": 1,
                "transitional": 0,
                "implemented": 1,
                "parity-verified": 0,
                "deprecated": 0,
            },
        )
        self.assertEqual(
            [module["module_id"] for module in catalog["modules"]],
            ["a.identified", "z.implemented"],
        )
        self.assertEqual(catalog["modules"][0]["capability"], "liquidity target")
        self.assertEqual(catalog["modules"][0]["inputs"], ["swings"])
        self.assertEqual(catalog["modules"][0]["outputs"], ["target"])

    def test_complete_template_requires_every_stage_once_enabled_and_non_empty(self):
        registry = complete_registry()
        for selections, diagnostic in (
            (complete_template().stages[:-1], "missing stage: management"),
            (
                complete_template().stages
                + (StageSelection(DecisionStage.MANAGEMENT, (plugin_id(DecisionStage.MANAGEMENT),)),),
                "duplicate stage: management",
            ),
            (
                tuple(
                    StageSelection(
                        stage=stage,
                        plugin_ids=() if stage is DecisionStage.TARGET else (plugin_id(stage),),
                    )
                    for stage in DecisionStage
                ),
                "empty stage: target",
            ),
            (
                tuple(
                    StageSelection(
                        stage=stage,
                        plugin_ids=(plugin_id(stage),),
                        enabled=stage is not DecisionStage.RISK,
                    )
                    for stage in DecisionStage
                ),
                "disabled stage: risk",
            ),
        ):
            with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(
                DecisionEngineConfigError, diagnostic
            ):
                registry.resolve_template(complete_template(selections=selections))

    def test_registry_rejects_unknown_duplicate_stage_and_version_mismatched_plugins(self):
        registry = complete_registry()
        unknown = list(complete_template().stages)
        unknown[0] = StageSelection(DecisionStage.MARKET_CONTEXT, ("missing.closed_bar",))
        with self.assertRaisesRegex(DecisionEngineConfigError, "unknown plugin: missing.closed_bar"):
            registry.resolve_template(complete_template(selections=tuple(unknown)))

        duplicate = list(complete_template().stages)
        duplicate[1] = StageSelection(
            DecisionStage.DIRECTION,
            (plugin_id(DecisionStage.MARKET_CONTEXT),),
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "duplicate plugin id"):
            registry.resolve_template(complete_template(selections=tuple(duplicate)))

        versions = {plugin_id(DecisionStage.DIRECTION): "2"}
        selections = list(complete_template().stages)
        selections[1] = StageSelection(
            DecisionStage.DIRECTION,
            (plugin_id(DecisionStage.DIRECTION),),
            plugin_versions=versions,
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "plugin version mismatch"):
            registry.resolve_template(complete_template(selections=tuple(selections)))

    def test_registry_rejects_duplicate_registered_id_and_stage_mismatch(self):
        duplicate = metadata_for(DecisionStage.MARKET_CONTEXT)
        with self.assertRaisesRegex(DecisionEngineConfigError, "duplicate plugin id"):
            PluginRegistry({"first": duplicate, "second": duplicate})

        wrong_stage_id = "core.wrong_stage"
        plugins = {plugin_id(stage): metadata_for(stage) for stage in DecisionStage}
        plugins[wrong_stage_id] = metadata_for(
            DecisionStage.MARKET_CONTEXT, plugin_id=wrong_stage_id
        )
        stages = list(complete_template().stages)
        stages[1] = StageSelection(
            DecisionStage.DIRECTION,
            (wrong_stage_id,),
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "stage mismatch"):
            complete_registry(plugins=plugins).resolve_template(
                complete_template(selections=tuple(stages))
            )

    def test_registry_rejects_metadata_without_safe_availability_or_profile(self):
        unsafe = metadata_for(DecisionStage.MARKET_CONTEXT, time_safe=False)
        with self.assertRaisesRegex(DecisionEngineConfigError, "unsafe plugin metadata"):
            PluginRegistry({unsafe.plugin_id: unsafe})

        profileless = metadata_for(DecisionStage.MARKET_CONTEXT, profile="")
        with self.assertRaisesRegex(DecisionEngineConfigError, "missing plugin profile"):
            PluginRegistry({profileless.plugin_id: profileless})

    def test_registry_rejects_missing_disabled_and_circular_requirements(self):
        direction_id = plugin_id(DecisionStage.DIRECTION)
        context_id = plugin_id(DecisionStage.MARKET_CONTEXT)
        plugins = {plugin_id(stage): metadata_for(stage) for stage in DecisionStage}
        plugins[direction_id] = metadata_for(
            DecisionStage.DIRECTION, requirements=("missing.provider",)
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "missing required provider: missing.provider"):
            complete_registry(plugins=plugins).resolve_template(complete_template())

        plugins[direction_id] = metadata_for(DecisionStage.DIRECTION, requirements=(context_id,))
        extra_context_id = "core.context_extra"
        plugins[extra_context_id] = metadata_for(
            DecisionStage.MARKET_CONTEXT, plugin_id=extra_context_id
        )
        disabled = list(complete_template().stages)
        disabled[0] = StageSelection(
            DecisionStage.MARKET_CONTEXT,
            (context_id, extra_context_id),
            plugin_enabled={context_id: False},
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "disabled required provider"):
            complete_registry(plugins=plugins).resolve_template(
                complete_template(selections=tuple(disabled))
            )

        plugins[context_id] = metadata_for(
            DecisionStage.MARKET_CONTEXT, requirements=(direction_id,)
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "circular plugin requirements"):
            complete_registry(plugins=plugins).resolve_template(complete_template())

    def test_registry_rejects_selected_plugin_conflicts(self):
        direction_id = plugin_id(DecisionStage.DIRECTION)
        evidence_id = plugin_id(DecisionStage.EVIDENCE)
        plugins = {plugin_id(stage): metadata_for(stage) for stage in DecisionStage}
        plugins[evidence_id] = metadata_for(
            DecisionStage.EVIDENCE,
            conflicts=(direction_id,),
        )

        with self.assertRaisesRegex(
            DecisionEngineConfigError,
            f"conflicting plugins: {evidence_id} and {direction_id}",
        ):
            complete_registry(plugins=plugins).resolve_template(complete_template())

    def test_registry_rejects_invalid_or_unknown_plugin_configuration_and_policies(self):
        target_id = plugin_id(DecisionStage.TARGET)
        plugins = {plugin_id(stage): metadata_for(stage) for stage in DecisionStage}
        plugins[target_id] = metadata_for(
            DecisionStage.TARGET,
            config_fields=("window",),
            required_config_fields=("window",),
        )
        selections = list(complete_template().stages)
        selections[2] = StageSelection(
            DecisionStage.TARGET,
            (target_id,),
            plugin_config={target_id: {"unknown": 1}},
        )
        registry = complete_registry(plugins=plugins)
        with self.assertRaisesRegex(DecisionEngineConfigError, "unknown config field"):
            registry.resolve_template(complete_template(selections=tuple(selections)))

        selections[2] = StageSelection(
            DecisionStage.TARGET,
            (target_id,),
            plugin_config={target_id: {"window": datetime.now(timezone.utc)}},
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "is not JSON serializable"):
            registry.resolve_template(complete_template(selections=tuple(selections)))

        selections[2] = StageSelection(
            DecisionStage.TARGET,
            (target_id,),
            plugin_config={target_id: {}},
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "missing required config field"):
            registry.resolve_template(complete_template(selections=tuple(selections)))

        selections[2] = StageSelection(
            DecisionStage.TARGET,
            (target_id,),
            combine_policy="sometimes",
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "invalid combine policy"):
            registry.resolve_template(complete_template(selections=tuple(selections)))

        selections[2] = StageSelection(
            DecisionStage.TARGET,
            (target_id,),
            score_policy="magic",
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "invalid score policy"):
            registry.resolve_template(complete_template(selections=tuple(selections)))


class DecisionPipelineTest(unittest.TestCase):
    def test_pipeline_passes_resolved_plugin_config_to_provider(self):
        direction_id = plugin_id(DecisionStage.DIRECTION)
        plugins = {}
        for stage in DecisionStage:
            metadata = metadata_for(
                stage,
                config_fields=("window",) if stage is DecisionStage.DIRECTION else (),
            )
            plugins[metadata.plugin_id] = (
                ConfigEchoPlugin(metadata)
                if stage is DecisionStage.DIRECTION
                else StaticPlugin(
                    metadata,
                    PluginResult.passed(
                        metadata.plugin_id,
                        stage,
                        available_at=SIGNAL_TIME,
                        profile="default",
                        requirements=(),
                    ),
                )
            )
        selections = list(complete_template().stages)
        selections[1] = StageSelection(
            DecisionStage.DIRECTION,
            (direction_id,),
            plugin_config={direction_id: {"window": 20}},
        )

        result = DecisionPipeline(PluginRegistry(plugins)).evaluate(
            complete_template(selections=tuple(selections)),
            DecisionContext(signal_time=SIGNAL_TIME),
        )

        self.assertEqual(result.plugin_results[1].facts, {"config": {"window": 20}})

    def test_pipeline_applies_stage_combine_and_score_policies(self):
        plugins = {}
        for stage in DecisionStage:
            metadata = metadata_for(stage)
            plugins[metadata.plugin_id] = StaticPlugin(
                metadata,
                PluginResult.passed(
                    metadata.plugin_id,
                    stage,
                    available_at=SIGNAL_TIME,
                    profile="default",
                    requirements=(),
                    score_contribution=2.0,
                ),
            )
        rejected_id = "core.evidence_rejected"
        rejected_metadata = metadata_for(
            DecisionStage.EVIDENCE,
            plugin_id=rejected_id,
        )
        plugins[rejected_id] = StaticPlugin(
            rejected_metadata,
            PluginResult(
                plugin_id=rejected_id,
                stage=DecisionStage.EVIDENCE,
                status="rejected",
                available_at=SIGNAL_TIME,
                time_safe=True,
                profile="default",
                score_contribution=5.0,
            ),
        )
        registry = PluginRegistry(plugins)

        for combine_policy, score_policy, expected_status, expected_score in (
            ("all", "sum", "rejected", 7.0),
            ("any", "max", "passed", 5.0),
        ):
            selections = list(complete_template().stages)
            selections[3] = StageSelection(
                DecisionStage.EVIDENCE,
                (plugin_id(DecisionStage.EVIDENCE), rejected_id),
                combine_policy=combine_policy,
                score_policy=score_policy,
            )

            result = DecisionPipeline(registry).evaluate(
                complete_template(selections=tuple(selections)),
                DecisionContext(signal_time=SIGNAL_TIME),
            )
            evidence = result.stage_results[3]

            with self.subTest(combine_policy=combine_policy, score_policy=score_policy):
                self.assertEqual(evidence.stage, DecisionStage.EVIDENCE)
                self.assertEqual(evidence.status, expected_status)
                self.assertEqual(evidence.score, expected_score)
                self.assertEqual(evidence.combine_policy, combine_policy)
                self.assertEqual(evidence.score_policy, score_policy)

    def test_pipeline_rejects_non_aware_signal_time(self):
        plugins = {}
        for stage in DecisionStage:
            metadata = metadata_for(stage)
            plugins[metadata.plugin_id] = StaticPlugin(
                metadata,
                PluginResult.passed(
                    metadata.plugin_id,
                    stage,
                    available_at=SIGNAL_TIME,
                    profile="default",
                    requirements=(),
                ),
            )
        pipeline = DecisionPipeline(PluginRegistry(plugins))

        for invalid_time in (1_767_225_600, "2026-01-01T00:00:00Z", datetime(2026, 1, 1)):
            with self.subTest(signal_time=invalid_time), self.assertRaisesRegex(
                DecisionEngineConfigError,
                "signal_time must be a timezone-aware datetime",
            ):
                pipeline.evaluate(
                    complete_template(),
                    DecisionContext(signal_time=invalid_time),
                )

    def test_pipeline_rejects_non_aware_plugin_available_at(self):
        for invalid_time in (1_767_225_600, "2026-01-01T00:00:00Z", datetime(2026, 1, 1)):
            plugins = {}
            for stage in DecisionStage:
                metadata = metadata_for(stage)
                available_at = (
                    invalid_time
                    if stage is DecisionStage.EVIDENCE
                    else SIGNAL_TIME
                )
                plugins[metadata.plugin_id] = StaticPlugin(
                    metadata,
                    PluginResult.passed(
                        metadata.plugin_id,
                        stage,
                        available_at=available_at,
                        profile="default",
                        requirements=(),
                    ),
                )

            with self.subTest(available_at=invalid_time), self.assertRaisesRegex(
                DecisionEngineConfigError,
                "available_at must be a timezone-aware datetime",
            ):
                DecisionPipeline(PluginRegistry(plugins)).evaluate(
                    complete_template(),
                    DecisionContext(signal_time=SIGNAL_TIME),
                )

    def test_pipeline_evaluates_valid_complete_template_in_stage_order(self):
        plugins = {}
        for stage in DecisionStage:
            metadata = metadata_for(stage)
            plugins[metadata.plugin_id] = StaticPlugin(
                metadata,
                PluginResult.passed(
                    metadata.plugin_id,
                    stage,
                    stage.value.upper(),
                    available_at=SIGNAL_TIME,
                    profile="default",
                    requirements=(),
                ),
            )

        result = DecisionPipeline(PluginRegistry(plugins)).evaluate(
            complete_template(), DecisionContext(signal_time=SIGNAL_TIME)
        )

        self.assertEqual([item.stage for item in result.plugin_results], list(DecisionStage))
        self.assertEqual(result.reason_codes, tuple(stage.value.upper() for stage in DecisionStage))

    def test_pipeline_rejects_unsafe_or_future_result_and_empty_success(self):
        plugins = {}
        for stage in DecisionStage:
            metadata = metadata_for(stage)
            plugins[metadata.plugin_id] = StaticPlugin(
                metadata,
                PluginResult.passed(
                    metadata.plugin_id,
                    stage,
                    available_at=SIGNAL_TIME,
                    profile="default",
                    requirements=(),
                ),
            )
        plugins[plugin_id(DecisionStage.EVIDENCE)] = StaticPlugin(
            metadata_for(DecisionStage.EVIDENCE),
            PluginResult(
                plugin_id(DecisionStage.EVIDENCE),
                DecisionStage.EVIDENCE,
                "passed",
                available_at=SIGNAL_TIME,
                profile="default",
                requirements=(),
            ),
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "unsafe plugin result"):
            DecisionPipeline(PluginRegistry(plugins)).evaluate(
                complete_template(), DecisionContext(signal_time=SIGNAL_TIME)
            )

        plugins[plugin_id(DecisionStage.EVIDENCE)] = StaticPlugin(
            metadata_for(DecisionStage.EVIDENCE),
            PluginResult.passed(
                plugin_id(DecisionStage.EVIDENCE),
                DecisionStage.EVIDENCE,
                available_at=SIGNAL_TIME + timedelta(seconds=1),
                profile="default",
                requirements=(),
            ),
        )
        with self.assertRaisesRegex(DecisionEngineConfigError, "future plugin result"):
            DecisionPipeline(PluginRegistry(plugins)).evaluate(
                complete_template(), DecisionContext(signal_time=SIGNAL_TIME)
            )

        with self.assertRaisesRegex(DecisionEngineConfigError, "empty pipeline result"):
            PipelineResult(())


class StaticPlugin:
    def __init__(self, metadata, result):
        self.metadata = metadata
        self._result = result

    def evaluate(self, context, upstream_results, config):
        return self._result


class ConfigEchoPlugin:
    def __init__(self, metadata):
        self.metadata = metadata

    def evaluate(self, context, upstream_results, config):
        return PluginResult.passed(
            self.metadata.plugin_id,
            self.metadata.stage,
            available_at=context.signal_time,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
            facts={"config": dict(config)},
        )


if __name__ == "__main__":
    unittest.main()
