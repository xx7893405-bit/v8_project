import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from decision_engine import (
    DecisionContext,
    DecisionEngineConfigError,
    DecisionPipeline,
    DecisionStage,
    DecisionTemplate,
    PluginMetadata,
    PluginResult,
    PluginRegistry,
    StageSelection,
)
from backtest_config import BacktestConfig, RunConfig
from nfe_v2_decision_template import (
    NFEV2DecisionTemplate,
    V2ModularDecisionTemplate,
    NFE_V2_COMPATIBLE_TEMPLATE,
    NFE_V2_PLUGIN_IDS,
    V2_MODULAR_PLUGIN_IDS,
    V2_MODULAR_TEMPLATE_ID,
    V2RRCostRiskGatePlugin,
    V2LTFStructureConfirmationPlugin,
    V2HTFStructureDirectionPlugin,
    V2RetraceLimitExecutionPlugin,
    V2ATRStructuralManagementPlugin,
    build_v2_modular_template,
    nfe_v2_plugin_registry,
)
from nfe_v2_strategy import NFEV2Strategy
from strategy_base import StrategyDecision


class LegacyV2Stub:
    def __init__(self, decision):
        self.decision = decision
        self.scan_calls = []
        self.management_calls = []

    def scan_entry_signal(self, *args):
        self.scan_calls.append(args)
        return self.decision

    def after_manage_position(self, *args):
        self.management_calls.append(args)
        args[0]["sl"] = 101.0


class NFEV2BacktesterStub:
    def __init__(self, curr_time, side, *, future_row=False):
        index = pd.date_range(end=curr_time, periods=60, freq="15min")
        self.frame = pd.DataFrame(
            {
                "open": 100.0,
                "high": 120.0,
                "low": 80.0,
                "close": 100.0,
                "ATR_14": 10.0,
            },
            index=index,
        )
        if future_row:
            self.frame.loc[curr_time + pd.Timedelta("15min")] = [
                1.0,
                999.0,
                1.0,
                999.0,
                999.0,
            ]
        self.side = side
        self.config = SimpleNamespace(maker_fee=0.0, taker_fee=0.0)
        self.price_scale = 1.0

    def get_timeframe_df(self, _timeframe):
        return self.frame

    def _allow_directions(self, *_args):
        return self.side == "LONG", self.side == "SHORT"

    def _build_retrace_order(
        self, side, _prev, _time, _balance, _close_pct, entry, sl, tp1, tp2, risk
    ):
        return (
            {
                "type": side,
                "entry_price": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "rr_potential": abs(tp1 - entry) / risk,
            },
            None,
        )


class BoundedV2Backtester:
    def __init__(self, htf, ltf, side, config):
        self.df_1h = htf
        self.df_4h = htf
        self.frame = ltf
        self.side = side
        self.config = config
        self.price_scale = 1.0

    def get_timeframe_df(self, _timeframe):
        return self.frame

    def _allow_directions(self, *_args):
        return self.side == "LONG", self.side == "SHORT"

    def _build_retrace_order(
        self, side, _prev, _time, _balance, _close_pct, entry, sl, tp1, tp2, risk
    ):
        return (
            {
                "type": side,
                "entry_price": entry,
                "limit_price": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "size": 1.0,
                "rr_potential": abs(tp1 - entry) / risk,
                "actual_risk_usd": risk,
            },
            None,
        )


class FixedFactsPlugin:
    def __init__(self, plugin_id, stage, facts):
        self.metadata = PluginMetadata(plugin_id, "1", stage, f"fixed {stage.value}")
        self.facts = facts

    def evaluate(self, context, _upstream_results, _config):
        return PluginResult.passed(
            self.metadata.plugin_id,
            self.metadata.stage,
            "FIXED_TEST_FACTS",
            available_at=context.signal_time,
            profile=self.metadata.profile,
            facts=self.facts,
        )


def prepared_nfe_v2(side):
    strategy = NFEV2Strategy(min_rr=0.1)
    now = pd.Timestamp("2026-01-02 12:00:00")
    strategy.precomputed_htf_df = pd.DataFrame(
        {
            "htf_long_ob_high": [90.0 if side == "LONG" else float("nan")],
            "htf_long_ob_low": [70.0 if side == "LONG" else float("nan")],
            "htf_target_high": [130.0 if side == "LONG" else float("nan")],
            "htf_short_ob_high": [130.0 if side == "SHORT" else float("nan")],
            "htf_short_ob_low": [110.0 if side == "SHORT" else float("nan")],
            "htf_target_low": [70.0 if side == "SHORT" else float("nan")],
        },
        index=[now],
    )
    strategy._find_recent_swings_from_slice = lambda *_args, **_kwargs: (
        [{"high": 95.0, "ob_low": 115.0, "ob_high": 125.0}],
        [{"low": 105.0, "ob_low": 70.0, "ob_high": 80.0}],
    )
    return strategy, now


def evaluate_v2_direction(htf, signal_time, **market_changes):
    stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
    stages[0] = StageSelection(
        DecisionStage.MARKET_CONTEXT,
        ("v2.closed_bar_context",),
        plugin_config={"v2.closed_bar_context": {"htf_timeframe": "1h"}},
    )
    stages[1] = StageSelection(
        DecisionStage.DIRECTION,
        ("v2.htf_structure_direction",),
        plugin_config={
            "v2.htf_structure_direction": {"htf_n": 1, "ob_range_type": "full"}
        },
    )
    market = {
        "htf_ohlcv": htf,
        "ltf_ohlcv": htf,
        "mode": "NONE",
        "bias_1d": "NONE",
        "bias_4h": "NONE",
        "allow_long_entries": True,
        "allow_short_entries": True,
        "legacy_scan": StrategyDecision,
        "decision_sink": [],
    }
    market.update(market_changes)
    return DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
        DecisionTemplate("v2_direction_test", "1", tuple(stages)),
        DecisionContext(signal_time=signal_time, market=market),
    ).plugin_results[1]


def evaluate_fixed_risk(side, target, evidence, *, config_changes=None, market_changes=None):
    facts = {
            DecisionStage.MARKET_CONTEXT: {},
            DecisionStage.DIRECTION: {"direction": side},
            DecisionStage.TARGET: {
                "targets": {side: {"target": target, "invalidation": evidence.get("entry_ob_low")}}
            },
            DecisionStage.EVIDENCE: {"evidence": {side: evidence} if evidence else {}},
            DecisionStage.EXECUTION: {},
            DecisionStage.MANAGEMENT: {},
    }
    plugin_ids = {
        stage: (
            "v2.ltf_structure_confirmation"
            if stage is DecisionStage.EVIDENCE
            else f"test.{stage.value}"
        )
        for stage in facts
    }
    plugins = {
        plugin_ids[stage]: FixedFactsPlugin(plugin_ids[stage], stage, stage_facts)
        for stage, stage_facts in facts.items()
    }
    plugins[V2RRCostRiskGatePlugin.metadata.plugin_id] = V2RRCostRiskGatePlugin()
    risk_config = {
        "maker_fee": 0.0,
        "taker_fee": 0.0,
        "min_rr": 3.0,
        "use_dynamic_sl": False,
        "sl_padding": 0.0,
        "sl_padding_atr_mult": 0.5,
        "limit_order_slippage": 0.0,
        "min_net_profit_r": 0.0,
        "tp1_close_pct": 1.0,
        "risk_pct": 0.01,
        "position_sizing_mode": "risk_based",
        "fixed_margin_usd": 1_000.0,
        "leverage": 1.0,
        "max_vol_pct": 1.0,
        "max_short_rr": None,
        "max_short_stop_atr": None,
    }
    risk_config.update(config_changes or {})
    stages = tuple(
        StageSelection(
            stage,
            (
                V2RRCostRiskGatePlugin.metadata.plugin_id
                if stage is DecisionStage.RISK
                else plugin_ids[stage],
            ),
            plugin_config=(
                {V2RRCostRiskGatePlugin.metadata.plugin_id: risk_config}
                if stage is DecisionStage.RISK
                else {}
            ),
        )
        for stage in DecisionStage
    )
    market = {
        "signal_bar": {"close": 100.0},
        "atr": 0.0,
        "price_scale": 1.0,
        "balance": 10_000.0,
        "signal_volume": 10_000.0,
    }
    market.update(market_changes or {})
    return DecisionPipeline(PluginRegistry(plugins)).evaluate(
        DecisionTemplate("v2_risk_test", "1", stages),
        DecisionContext(
            signal_time=pd.Timestamp("2026-01-02 05:00:00", tz="UTC"),
            market=market,
        ),
    ).plugin_results[4]


def evaluate_fixed_execution(side, risk_decision):
    facts = {
        DecisionStage.MARKET_CONTEXT: {},
        DecisionStage.DIRECTION: {"direction": side},
        DecisionStage.TARGET: {},
        DecisionStage.EVIDENCE: {},
        DecisionStage.RISK: {
            "risk_decisions": {side: risk_decision} if risk_decision else {}
        },
        DecisionStage.MANAGEMENT: {},
    }
    plugin_ids = {
        stage: (
            "v2.rr_cost_risk_gate"
            if stage is DecisionStage.RISK
            else f"test.{stage.value}"
        )
        for stage in facts
    }
    plugins = {
        plugin_ids[stage]: FixedFactsPlugin(plugin_ids[stage], stage, stage_facts)
        for stage, stage_facts in facts.items()
    }
    plugins[V2RetraceLimitExecutionPlugin.metadata.plugin_id] = V2RetraceLimitExecutionPlugin()
    stages = tuple(
        StageSelection(
            stage,
            (
                V2RetraceLimitExecutionPlugin.metadata.plugin_id
                if stage is DecisionStage.EXECUTION
                else plugin_ids[stage],
            ),
            plugin_config=(
                {
                    V2RetraceLimitExecutionPlugin.metadata.plugin_id: {
                        "expiry_bars": 72
                    }
                }
                if stage is DecisionStage.EXECUTION
                else {}
            ),
        )
        for stage in DecisionStage
    )
    return DecisionPipeline(PluginRegistry(plugins)).evaluate(
        DecisionTemplate("v2_execution_test", "1", stages),
        DecisionContext(
            signal_time=pd.Timestamp("2026-01-02 05:00:00", tz="UTC"),
            market={},
        ),
    ).plugin_results[5]


def evaluate_fixed_management(active_position, ltf, *, config_changes=None):
    facts = {
        stage: {} for stage in DecisionStage if stage is not DecisionStage.MANAGEMENT
    }
    plugins = {
        f"test.{stage.value}": FixedFactsPlugin(f"test.{stage.value}", stage, stage_facts)
        for stage, stage_facts in facts.items()
    }
    plugins[V2ATRStructuralManagementPlugin.metadata.plugin_id] = V2ATRStructuralManagementPlugin()
    management_config = {
        "use_trailing_stop": True,
        "use_dynamic_sl": True,
        "sl_padding": 20.0,
        "sl_padding_atr_mult": 0.5,
        "ltf_n": 1,
        "ob_range_type": "full",
        "enable_be": False,
        "be_trigger_ratio": 1.5,
        "max_holding_bars": 48,
    }
    management_config.update(config_changes or {})
    stages = tuple(
        StageSelection(
            stage,
            (
                V2ATRStructuralManagementPlugin.metadata.plugin_id
                if stage is DecisionStage.MANAGEMENT
                else f"test.{stage.value}",
            ),
            plugin_config=(
                {V2ATRStructuralManagementPlugin.metadata.plugin_id: management_config}
                if stage is DecisionStage.MANAGEMENT
                else {}
            ),
        )
        for stage in DecisionStage
    )
    signal_time = pd.Timestamp(ltf.index[-1])
    if signal_time.tzinfo is None:
        signal_time = signal_time.tz_localize("UTC")
    return DecisionPipeline(PluginRegistry(plugins)).evaluate(
        DecisionTemplate("v2_management_test", "1", stages),
        DecisionContext(
            signal_time=signal_time,
            market={
                "active_position": active_position,
                "ltf_ohlcv": ltf,
                "price_scale": 1.0,
            },
        ),
    ).plugin_results[6]


def evaluate_modular_side(side, *, future_rows=False, no_retrace=False):
    signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
    if side == "LONG":
        htf_values = {
            "open": [7.0, 10.0, 8.0, 15.0, 10.0],
            "high": [10.0, 15.0, 12.0, 16.0, 14.0],
            "low": [5.0, 8.0, 6.0, 9.0, 7.0],
            "close": [7.0, 10.0, 8.0, 16.0, 10.0],
        }
        ltf_values = {
            "open": [7.0, 10.0, 8.0, 12.0, 15.0],
            "high": [10.0, 15.0, 12.0, 14.0, 16.0],
            "low": [5.0, 8.0, 6.0, 9.0, 10.0],
            "close": [7.0, 10.0, 8.0, 12.0, 16.0],
        }
        signal_bar = {"high": 16.0, "low": 11.0, "close": 16.0}
    else:
        htf_values = {
            "open": [12.0, 8.0, 10.0, 5.0, 9.0],
            "high": [15.0, 12.0, 14.0, 11.0, 13.0],
            "low": [10.0, 5.0, 8.0, 4.0, 6.0],
            "close": [12.0, 8.0, 10.0, 4.0, 9.0],
        }
        ltf_values = {
            "open": [12.0, 8.0, 10.0, 6.0, 4.0],
            "high": [15.0, 12.0, 14.0, 11.0, 10.0],
            "low": [10.0, 5.0, 8.0, 4.0, 3.0],
            "close": [12.0, 8.0, 10.0, 6.0, 3.0],
        }
        signal_bar = {"high": 9.0, "low": 3.0, "close": 3.0}
    if no_retrace:
        signal_bar = (
            {"high": 21.0, "low": 20.0, "close": 20.0}
            if side == "LONG"
            else {"high": 1.0, "low": 0.0, "close": 0.0}
        )
    htf = pd.DataFrame(
        htf_values,
        index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
    )
    ltf = pd.DataFrame(
        ltf_values | {"ATR_14": 0.0},
        index=pd.date_range("2026-01-02 04:00:00", periods=5, freq="15min"),
    )
    if future_rows:
        htf.loc[pd.Timestamp("2026-01-02 05:00:00")] = [1.0, 999.0, 1.0, 999.0]
        ltf.loc[pd.Timestamp("2026-01-02 05:15:00")] = [1.0, 999.0, 1.0, 999.0, 999.0]
    template = build_v2_modular_template(
        NFEV2Strategy(
            htf_n=1,
            ltf_n=1,
            min_rr=0.1,
            sl_padding=0.0,
            use_dynamic_sl=False,
        ),
        BacktestConfig(
            maker_fee=0.0,
            taker_fee=0.0,
            limit_order_slippage_usd=0.0,
            min_net_profit_r=0.0,
        ),
        RunConfig(tp1_close_pct=1.0),
    )
    return DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
        template,
        DecisionContext(
            signal_time=signal_time,
            market={
                "htf_ohlcv": htf,
                "ltf_ohlcv": ltf,
                "signal_bar": signal_bar,
                "mode": "NONE",
                "bias_1d": "NONE",
                "bias_4h": "NONE",
                "allow_long_entries": True,
                "allow_short_entries": True,
                "atr": 0.0,
                "price_scale": 1.0,
                "balance": 10_000.0,
                "signal_volume": 1_000.0,
                "active_position": None,
            },
        ),
    )


def bounded_v2_frames(side):
    if side == "LONG":
        htf_values = {
            "open": [7.0, 10.0, 8.0, 15.0, 10.0],
            "high": [10.0, 15.0, 12.0, 16.0, 14.0],
            "low": [5.0, 8.0, 6.0, 9.0, 7.0],
            "close": [7.0, 10.0, 8.0, 16.0, 10.0],
        }
        base = {"open": 10.0, "high": 12.0, "low": 9.0, "close": 10.0}
    else:
        htf_values = {
            "open": [12.0, 8.0, 10.0, 5.0, 9.0],
            "high": [15.0, 12.0, 14.0, 11.0, 13.0],
            "low": [10.0, 5.0, 8.0, 4.0, 6.0],
            "close": [12.0, 8.0, 10.0, 4.0, 9.0],
        }
        base = {"open": 10.0, "high": 11.0, "low": 8.0, "close": 10.0}
    htf = pd.DataFrame(
        htf_values,
        index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
    )
    ltf = pd.DataFrame(
        {key: [value] * 60 for key, value in base.items()} | {
            "ATR_14": [0.0] * 60,
            "volume": [1_000.0] * 60,
        },
        index=pd.date_range("2026-01-02 00:00:00", periods=60, freq="15min"),
    )
    if side == "LONG":
        ltf.loc[ltf.index[-5], "high"] = 15.0
        ltf.loc[ltf.index[-3], ["low", "close"]] = [6.0, 8.0]
        ltf.loc[ltf.index[-1], ["open", "high", "low", "close"]] = [15.0, 16.0, 11.0, 16.0]
    else:
        ltf.loc[ltf.index[-5], "low"] = 5.0
        ltf.loc[ltf.index[-3], ["high", "close"]] = [14.0, 12.0]
        ltf.loc[ltf.index[-1], ["open", "high", "low", "close"]] = [4.0, 9.0, 3.0, 3.0]
    return htf, ltf


class NFEV2DecisionTemplateTest(unittest.TestCase):
    def test_cached_htf_structure_uses_release_time_not_raw_open_time(self):
        signal_time = pd.Timestamp("2026-01-02 16:00:00", tz="UTC")
        structure = pd.DataFrame(
            {
                "htf_long_ob_high": [float("nan"), float("nan")],
                "htf_long_ob_low": [float("nan"), float("nan")],
                "htf_target_high": [float("nan"), float("nan")],
                "htf_short_ob_high": [20.0, float("nan")],
                "htf_short_ob_low": [10.0, float("nan")],
                "htf_target_low": [5.0, float("nan")],
            },
            index=pd.to_datetime(
                ["2026-01-02 15:00:00", "2026-01-02 16:00:00"], utc=True
            ),
        )
        market_context = PluginResult.passed(
            "v2.closed_bar_context",
            DecisionStage.MARKET_CONTEXT,
            "CONTEXT",
            available_at=signal_time,
            profile="default",
            facts={"latest_htf_open": "2026-01-02T15:00:00+00:00"},
        )

        result = V2HTFStructureDirectionPlugin().evaluate(
            DecisionContext(
                signal_time=signal_time,
                market={
                    "precomputed_htf_structure": structure,
                    "allow_long_entries": True,
                    "allow_short_entries": True,
                    "mode": "NONE",
                },
            ),
            (market_context,),
            {"htf_n": 1, "ob_range_type": "full"},
        )

        self.assertEqual(
            (result.facts["structure_short"], result.facts["direction"]),
            (False, "NONE"),
        )

    def test_ltf_confirmation_skips_swing_scan_without_htf_retrace(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        market_context = PluginResult.passed(
            "v2.closed_bar_context",
            DecisionStage.MARKET_CONTEXT,
            "CONTEXT",
            available_at=signal_time,
            profile="default",
            facts={"latest_ltf_open": signal_time.isoformat()},
        )
        htf_retrace = PluginResult(
            plugin_id="v2.htf_ob_retrace",
            stage=DecisionStage.EVIDENCE,
            status="rejected",
            reason_codes=("V2_HTF_OB_RETRACE_NONE",),
            facts={"evidence": {}},
            available_at=signal_time,
            time_safe=True,
        )

        result = V2LTFStructureConfirmationPlugin().evaluate(
            DecisionContext(signal_time=signal_time, market={"signal_bar": {"close": 1.0}}),
            (market_context, htf_retrace),
            {"ltf_n": 3, "ob_range_type": "full"},
        )

        self.assertEqual(
            (result.status, result.facts),
            ("rejected", {"evidence": {}}),
        )

    def test_v2_modular_template_resolves_all_eight_modules_with_config_snapshot(self):
        strategy = NFEV2Strategy(
            htf="1h",
            ltf="15m",
            htf_n=5,
            ltf_n=3,
            ob_range_type="full",
            min_rr=3.0,
            sl_padding=20.0,
            max_short_rr=8.0,
            max_short_stop_atr=4.0,
            use_dynamic_sl=True,
            sl_padding_atr_mult=0.5,
            use_trailing_stop=True,
        )
        backtest_config = BacktestConfig(
            maker_fee=0.0002,
            taker_fee=0.0005,
            risk_pct=0.05,
            leverage=20.0,
            max_holding_bars=48,
        )
        run_config = RunConfig(tp1_close_pct=0.5, enable_be=True)

        template = build_v2_modular_template(strategy, backtest_config, run_config)
        resolved = nfe_v2_plugin_registry().resolve_template(template)

        self.assertEqual(
            (
                resolved.template_id,
                [selection.plugin_ids for selection in resolved.stages],
                resolved.stages[4].plugin_config["v2.rr_cost_risk_gate"],
                resolved.stages[6].plugin_config["v2.atr_structural_management"],
            ),
            (
                V2_MODULAR_TEMPLATE_ID,
                [V2_MODULAR_PLUGIN_IDS[stage] for stage in DecisionStage],
                {
                    "maker_fee": 0.0002,
                    "taker_fee": 0.0005,
                    "min_rr": 3.0,
                    "use_dynamic_sl": True,
                    "sl_padding": 20.0,
                    "sl_padding_atr_mult": 0.5,
                    "limit_order_slippage": 5.0,
                    "min_net_profit_r": 1.2,
                    "tp1_close_pct": 0.5,
                    "risk_pct": 0.05,
                    "position_sizing_mode": "risk_based",
                    "fixed_margin_usd": 1000.0,
                    "leverage": 20.0,
                    "max_vol_pct": 0.05,
                    "max_short_rr": 8.0,
                    "max_short_stop_atr": 4.0,
                },
                {
                    "use_trailing_stop": True,
                    "use_dynamic_sl": True,
                    "sl_padding": 20.0,
                    "sl_padding_atr_mult": 0.5,
                    "ltf_n": 3,
                    "ob_range_type": "full",
                    "enable_be": True,
                    "be_trigger_ratio": 1.5,
                    "max_holding_bars": 48,
                },
            ),
        )

    def test_v2_modular_pipeline_emits_long_intent_without_legacy_scan(self):
        result = evaluate_modular_side("LONG")

        self.assertEqual(
            (
                [plugin.plugin_id for plugin in result.plugin_results],
                result.plugin_results[-2].reason_codes,
                next(iter(result.plugin_results[-2].facts["execution_intents"])),
            ),
            (
                [
                    plugin_id
                    for stage in DecisionStage
                    for plugin_id in V2_MODULAR_PLUGIN_IDS[stage]
                ],
                ("V2_RETRACE_LIMIT_LONG_INTENT",),
                "LONG",
            ),
        )

    def test_v2_modular_pipeline_emits_short_intent_without_legacy_scan(self):
        result = evaluate_modular_side("SHORT")

        self.assertEqual(
            (
                result.plugin_results[-2].reason_codes,
                next(iter(result.plugin_results[-2].facts["execution_intents"])),
            ),
            (("V2_RETRACE_LIMIT_SHORT_INTENT",), "SHORT"),
        )

    def test_composition_cannot_overwrite_a_verified_v2_module_id(self):
        replacement = FixedFactsPlugin(
            "v2.htf_structure_direction",
            DecisionStage.DIRECTION,
            {"direction": "SHORT"},
        )

        with self.assertRaisesRegex(
            DecisionEngineConfigError,
            "duplicate plugin id: v2.htf_structure_direction",
        ):
            nfe_v2_plugin_registry({replacement.metadata.plugin_id: replacement})

    def test_composed_template_uses_the_existing_backtest_adapter_contract(self):
        htf, ltf = bounded_v2_frames("LONG")
        config = BacktestConfig(
            maker_fee=0.0,
            taker_fee=0.0,
            limit_order_slippage_usd=0.0,
            min_net_profit_r=0.0,
        )
        run_config = RunConfig(tp1_close_pct=1.0)
        strategy_args = {
            "htf_n": 1,
            "ltf_n": 1,
            "min_rr": 0.1,
            "sl_padding": 0.0,
            "use_dynamic_sl": False,
        }
        baseline_strategy = NFEV2Strategy(**strategy_args)
        strategy = NFEV2Strategy(
            htf_n=1,
            ltf_n=1,
            min_rr=0.1,
            sl_padding=0.0,
            use_dynamic_sl=False,
        )
        replacement = FixedFactsPlugin(
            "other.fixed_long_direction",
            DecisionStage.DIRECTION,
            {"direction": "LONG"},
        )
        stages = list(build_v2_modular_template(strategy, config, run_config).stages)
        stages[1] = StageSelection(
            DecisionStage.DIRECTION,
            (replacement.metadata.plugin_id,),
        )
        composed_template = DecisionTemplate(
            "other_direction_with_v2_modules",
            "1",
            tuple(stages),
        )
        backtester = BoundedV2Backtester(htf, ltf, "LONG", config)
        baseline_adapter = V2ModularDecisionTemplate(baseline_strategy)
        baseline = baseline_adapter.scan_entry_signal(
            backtester,
            ltf.iloc[-2],
            ltf.iloc[-1],
            ltf.index[-1],
            10_000.0,
            run_config,
        )

        composed_adapter = V2ModularDecisionTemplate(
            strategy,
            registry=nfe_v2_plugin_registry(
                {replacement.metadata.plugin_id: replacement}
            ),
            template=composed_template,
        )
        decision = composed_adapter.scan_entry_signal(
            backtester,
            ltf.iloc[-2],
            ltf.iloc[-1],
            ltf.index[-1],
            10_000.0,
            run_config,
        )

        self.assertEqual(decision.retrace_order, baseline.retrace_order)
        baseline_results = baseline_adapter.last_pipeline_result.plugin_results
        composed_results = composed_adapter.last_pipeline_result.plugin_results
        baseline_ids = [result.plugin_id for result in baseline_results]
        self.assertEqual(
            [result.plugin_id for result in composed_results],
            baseline_ids[:1] + [replacement.metadata.plugin_id] + baseline_ids[2:],
        )
        self.assertEqual(
            [result.facts for index, result in enumerate(composed_results) if index != 1],
            [result.facts for index, result in enumerate(baseline_results) if index != 1],
        )

    def test_v2_modular_pipeline_ignores_future_htf_and_ltf_rows(self):
        original = evaluate_modular_side("LONG")
        with_future = evaluate_modular_side("LONG", future_rows=True)

        self.assertEqual(
            with_future.plugin_results[-2].facts,
            original.plugin_results[-2].facts,
        )

    def test_v2_modular_rejected_decision_keeps_every_module_contribution(self):
        result = evaluate_modular_side("LONG", no_retrace=True)

        self.assertEqual(
            (
                len(result.plugin_results),
                all(plugin.reason_codes for plugin in result.plugin_results),
                result.plugin_results[-2].status,
                result.plugin_results[-2].facts,
            ),
            (
                8,
                True,
                "rejected",
                {"execution_intents": {}},
            ),
        )

    def test_v2_modular_bounded_long_and_short_intents_match_legacy_prices(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                htf, ltf = bounded_v2_frames(side)
                strategy = NFEV2Strategy(
                    htf_n=1,
                    ltf_n=1,
                    min_rr=0.1,
                    sl_padding=0.0,
                    use_dynamic_sl=False,
                )
                config = BacktestConfig(
                    maker_fee=0.0,
                    taker_fee=0.0,
                    limit_order_slippage_usd=0.0,
                    min_net_profit_r=0.0,
                )
                run_config = RunConfig(tp1_close_pct=1.0)
                backtester = BoundedV2Backtester(htf, ltf, side, config)
                curr_time = ltf.index[-1]
                legacy = strategy.scan_entry_signal(
                    backtester,
                    ltf.iloc[-2],
                    ltf.iloc[-1],
                    curr_time,
                    10_000.0,
                    run_config,
                ).retrace_order
                pipeline_time = curr_time.tz_localize("UTC")
                modular = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
                    build_v2_modular_template(strategy, config, run_config),
                    DecisionContext(
                        signal_time=pipeline_time,
                        market={
                            "htf_ohlcv": htf,
                            "ltf_ohlcv": ltf,
                            "signal_bar": ltf.iloc[-1],
                            "mode": "NONE",
                            "bias_1d": "NONE",
                            "bias_4h": "NONE",
                            "allow_long_entries": side == "LONG",
                            "allow_short_entries": side == "SHORT",
                            "atr": 0.0,
                            "price_scale": 1.0,
                            "balance": 10_000.0,
                            "signal_volume": 1_000.0,
                            "active_position": None,
                        },
                    ),
                ).plugin_results[-2].facts["execution_intents"][side]

                self.assertEqual(
                    (
                        modular["side"],
                        modular["limit_price"],
                        modular["stop_price"],
                        modular["take_profit_1"],
                        modular["take_profit_2"],
                    ),
                    (
                        legacy["type"],
                        legacy["entry_price"],
                        legacy["sl"],
                        legacy["tp1"],
                        legacy["tp2"],
                    ),
                )

    def test_v2_modular_management_contribution_matches_legacy_stop_move(self):
        for side, current_sl in (("LONG", 5.0), ("SHORT", 15.0)):
            with self.subTest(side=side):
                htf, ltf = bounded_v2_frames(side)
                strategy = NFEV2Strategy(
                    htf_n=1,
                    ltf_n=1,
                    min_rr=0.1,
                    sl_padding=0.0,
                    use_dynamic_sl=False,
                )
                config = BacktestConfig(
                    maker_fee=0.0,
                    taker_fee=0.0,
                    limit_order_slippage_usd=0.0,
                    min_net_profit_r=0.0,
                )
                run_config = RunConfig(tp1_close_pct=1.0)
                backtester = BoundedV2Backtester(htf, ltf, side, config)
                legacy_position = {"type": side, "sl": current_sl}
                strategy.after_manage_position(legacy_position, backtester, ltf.index[-1])
                modular_position = {"type": side, "sl": current_sl}
                management = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
                    build_v2_modular_template(strategy, config, run_config),
                    DecisionContext(
                        signal_time=ltf.index[-1].tz_localize("UTC"),
                        market={
                            "htf_ohlcv": htf,
                            "ltf_ohlcv": ltf,
                            "signal_bar": ltf.iloc[-1],
                            "mode": "NONE",
                            "bias_1d": "NONE",
                            "bias_4h": "NONE",
                            "allow_long_entries": side == "LONG",
                            "allow_short_entries": side == "SHORT",
                            "atr": 0.0,
                            "price_scale": 1.0,
                            "balance": 10_000.0,
                            "signal_volume": 1_000.0,
                            "active_position": modular_position,
                        },
                    ),
                ).plugin_results[-1]

                self.assertEqual(
                    (
                        modular_position["sl"],
                        management.facts["management_intents"][side]["stop_price"],
                    ),
                    (current_sl, legacy_position["sl"]),
                )

    def test_v2_modular_backtest_adapter_matches_bounded_legacy_order_by_side(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                htf, ltf = bounded_v2_frames(side)
                config = BacktestConfig(
                    maker_fee=0.0,
                    taker_fee=0.0,
                    limit_order_slippage_usd=0.0,
                    min_net_profit_r=0.0,
                )
                run_config = RunConfig(tp1_close_pct=1.0)
                backtester = BoundedV2Backtester(htf, ltf, side, config)
                strategy_args = {
                    "htf_n": 1,
                    "ltf_n": 1,
                    "min_rr": 0.1,
                    "sl_padding": 0.0,
                    "use_dynamic_sl": False,
                }
                curr_time = ltf.index[-1]
                legacy = NFEV2Strategy(**strategy_args).scan_entry_signal(
                    backtester,
                    ltf.iloc[-2],
                    ltf.iloc[-1],
                    curr_time,
                    10_000.0,
                    run_config,
                ).retrace_order

                modular = V2ModularDecisionTemplate(
                    NFEV2Strategy(**strategy_args)
                ).scan_entry_signal(
                    backtester,
                    ltf.iloc[-2],
                    ltf.iloc[-1],
                    curr_time,
                    10_000.0,
                    run_config,
                ).retrace_order

                self.assertEqual(
                    {key: modular[key] for key in (
                        "type", "entry_price", "limit_price", "sl", "tp1", "tp2", "entry_mode"
                    )},
                    {key: legacy[key] for key in (
                        "type", "entry_price", "limit_price", "sl", "tp1", "tp2", "entry_mode"
                    )},
                )

    def test_v2_modular_backtest_adapter_reuses_one_htf_structure_snapshot(self):
        htf, ltf = bounded_v2_frames("LONG")
        config = BacktestConfig(
            maker_fee=0.0,
            taker_fee=0.0,
            limit_order_slippage_usd=0.0,
            min_net_profit_r=0.0,
        )
        run_config = RunConfig(tp1_close_pct=1.0)
        backtester = BoundedV2Backtester(htf, ltf, "LONG", config)
        adapter = V2ModularDecisionTemplate(
            NFEV2Strategy(
                htf_n=1,
                ltf_n=1,
                min_rr=0.1,
                sl_padding=0.0,
                use_dynamic_sl=False,
            )
        )

        for _ in range(2):
            adapter.scan_entry_signal(
                backtester,
                ltf.iloc[-2],
                ltf.iloc[-1],
                ltf.index[-1],
                10_000.0,
                run_config,
            )
            if adapter.strategy.precomputed_htf_df is not None:
                cached = adapter.strategy.precomputed_htf_df

        self.assertIs(adapter.strategy.precomputed_htf_df, cached)

    def test_v2_modular_backtest_adapter_applies_management_intent_like_legacy(self):
        for side, current_sl in (("LONG", 5.0), ("SHORT", 15.0)):
            with self.subTest(side=side):
                htf, ltf = bounded_v2_frames(side)
                config = BacktestConfig(
                    maker_fee=0.0,
                    taker_fee=0.0,
                    limit_order_slippage_usd=0.0,
                    min_net_profit_r=0.0,
                )
                run_config = RunConfig(tp1_close_pct=1.0)
                backtester = BoundedV2Backtester(htf, ltf, side, config)
                strategy_args = {
                    "htf_n": 1,
                    "ltf_n": 1,
                    "min_rr": 0.1,
                    "sl_padding": 0.0,
                    "use_dynamic_sl": False,
                }
                legacy = NFEV2Strategy(**strategy_args)
                legacy_position = {"type": side, "sl": current_sl}
                legacy.after_manage_position(legacy_position, backtester, ltf.index[-1])
                adapter = V2ModularDecisionTemplate(NFEV2Strategy(**strategy_args))
                adapter.scan_entry_signal(
                    backtester,
                    ltf.iloc[-2],
                    ltf.iloc[-1],
                    ltf.index[-1],
                    10_000.0,
                    run_config,
                )
                modular_position = {"type": side, "sl": current_sl}

                adapter.after_manage_position(
                    modular_position, backtester, ltf.index[-1]
                )

                self.assertEqual(modular_position, legacy_position)

    def test_atr_structural_management_emits_long_stop_move_without_mutating_position(self):
        ltf = pd.DataFrame(
            {
                "open": 100.0,
                "high": 110.0,
                "low": 100.0,
                "close": 100.0,
                "ATR_14": 10.0,
            },
            index=pd.date_range("2026-01-01", periods=60, freq="15min"),
        )
        ltf.loc[ltf.index[-3], "low"] = 80.0
        position = {"type": "LONG", "sl": 70.0}

        management = evaluate_fixed_management(position, ltf)

        self.assertEqual(
            (position, management.status, management.reason_codes, management.facts),
            (
                {"type": "LONG", "sl": 70.0},
                "passed",
                ("V2_ATR_STRUCTURAL_LONG_STOP_MOVE",),
                {
                    "management_intents": {
                        "LONG": {
                            "intent_type": "move_stop",
                            "side": "LONG",
                            "created_at": "2026-01-01T14:45:00+00:00",
                            "stop_price": 75.0,
                            "reason": "ATR_STRUCTURAL_TRAILING",
                        }
                    }
                },
            ),
        )

    def test_management_policy_records_tp1_be_time_and_liquidation_without_resolving_events(self):
        ltf = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "ATR_14": 10.0,
            },
            index=pd.date_range("2026-01-01", periods=60, freq="15min"),
        )
        position = {
            "type": "LONG",
            "entry_price": 100.0,
            "sl": 90.0,
            "tp1": 120.0,
            "tp2": 9_999_999.0,
            "tp1_close_pct": 0.5,
            "tp1_hit": False,
            "be_active": False,
            "leverage": 2.0,
            "liquidation_price": 55.0,
        }

        management = evaluate_fixed_management(
            position,
            ltf,
            config_changes={
                "enable_be": True,
                "be_trigger_ratio": 0.5,
                "max_holding_bars": 48,
            },
        )

        self.assertEqual(
            (management.status, management.reason_codes, management.facts),
            (
                "passed",
                ("V2_MANAGEMENT_LONG_POLICY",),
                {
                    "management_intents": {},
                    "management_policy": {
                        "side": "LONG",
                        "event_order": [
                            "liquidation",
                            "stop_loss",
                            "take_profit_1",
                            "take_profit_2",
                            "break_even_after_bar",
                            "time_stop",
                        ],
                        "take_profit_1": {
                            "price": 120.0,
                            "close_pct": 0.5,
                            "already_hit": False,
                        },
                        "take_profit_2": {"price": 9_999_999.0},
                        "break_even": {
                            "enabled": True,
                            "trigger_price": 110.0,
                            "stop_price": 100.0,
                            "active": False,
                        },
                        "time_stop": {"max_holding_bars": 48},
                        "liquidation": {"enabled": True, "price": 55.0},
                    },
                },
            ),
        )

    def test_management_policy_and_structural_stop_match_legacy_short_side(self):
        ltf = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.0,
                "low": 90.0,
                "close": 100.0,
                "ATR_14": 10.0,
            },
            index=pd.date_range("2026-01-01", periods=60, freq="15min"),
        )
        ltf.loc[ltf.index[-3], "high"] = 120.0
        position = {
            "type": "SHORT",
            "entry_price": 100.0,
            "sl": 130.0,
            "tp1": 80.0,
            "tp2": 0.01,
            "tp1_close_pct": 0.5,
            "tp1_hit": False,
            "be_active": True,
            "leverage": 1.0,
            "liquidation_price": None,
        }

        management = evaluate_fixed_management(
            position,
            ltf,
            config_changes={
                "enable_be": True,
                "be_trigger_ratio": 0.5,
                "max_holding_bars": 48,
            },
        )

        self.assertEqual(
            (
                position["sl"],
                management.reason_codes,
                management.facts["management_intents"]["SHORT"]["stop_price"],
                management.facts["management_policy"]["break_even"],
                management.facts["management_policy"]["time_stop"],
                management.facts["management_policy"]["liquidation"],
            ),
            (
                130.0,
                ("V2_ATR_STRUCTURAL_SHORT_STOP_MOVE",),
                125.0,
                {
                    "enabled": True,
                    "trigger_price": 90.0,
                    "stop_price": 100.0,
                    "active": True,
                },
                {"max_holding_bars": 144},
                {"enabled": False, "price": None},
            ),
        )

    def test_retrace_limit_execution_emits_standard_long_intent_without_filling(self):
        execution = evaluate_fixed_execution(
            "LONG",
            {
                "entry_price": 101.0,
                "limit_price": 100.0,
                "sl": 90.0,
                "tp1": 133.0,
                "tp2": 9_999_999.0,
                "size": 2.0,
                "entry_balance": 1_000.0,
                "rr_potential": 3.0,
                "actual_risk_usd": 22.0,
                "tp1_close_pct": 0.5,
                "position_sizing_mode": "risk_based",
                "target_notional_usd": 202.0,
                "actual_notional_usd": 202.0,
                "leverage": 1.0,
            },
        )

        self.assertEqual(
            (execution.status, execution.reason_codes, execution.facts),
            (
                "passed",
                ("V2_RETRACE_LIMIT_LONG_INTENT",),
                {
                    "execution_intents": {
                        "LONG": {
                            "intent_type": "retrace_limit",
                            "side": "LONG",
                            "created_at": "2026-01-02T05:00:00+00:00",
                            "expires_after_bars": 72,
                            "entry_price": 101.0,
                            "limit_price": 100.0,
                            "stop_price": 90.0,
                            "take_profit_1": 133.0,
                            "take_profit_2": 9_999_999.0,
                            "quantity": 2.0,
                            "entry_balance": 1_000.0,
                            "reward_risk": 3.0,
                            "actual_risk_usd": 22.0,
                            "take_profit_1_close_pct": 0.5,
                            "position_sizing_mode": "risk_based",
                            "target_notional_usd": 202.0,
                            "actual_notional_usd": 202.0,
                            "leverage": 1.0,
                            "entry_mode": "NFE_DL_LONG",
                            "live_take_profit_2": None,
                        }
                    }
                },
            ),
        )

    def test_completed_risk_decision_composes_directly_into_execution_intent(self):
        risk = evaluate_fixed_risk(
            "LONG",
            133.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={"tp1_close_pct": 0.5},
            market_changes={"balance": 1_000.0},
        )

        execution = evaluate_fixed_execution(
            "LONG", risk.facts["risk_decisions"]["LONG"]
        )

        self.assertEqual(
            {
                key: execution.facts["execution_intents"]["LONG"][key]
                for key in ("entry_balance", "take_profit_1_close_pct")
            },
            {"entry_balance": 1_000.0, "take_profit_1_close_pct": 0.5},
        )

    def test_retrace_limit_execution_emits_standard_short_intent(self):
        execution = evaluate_fixed_execution(
            "SHORT",
            {
                "entry_price": 99.0,
                "limit_price": 100.0,
                "sl": 110.0,
                "tp1": 75.0,
                "tp2": 0.01,
                "size": 2.0,
                "entry_balance": 1_000.0,
                "rr_potential": 2.0,
                "actual_risk_usd": 22.0,
                "tp1_close_pct": 0.5,
                "position_sizing_mode": "risk_based",
                "target_notional_usd": 198.0,
                "actual_notional_usd": 198.0,
                "leverage": 1.0,
            },
        )

        intent = execution.facts["execution_intents"]["SHORT"]
        self.assertEqual(
            {
                key: intent[key]
                for key in (
                    "side", "entry_price", "limit_price", "stop_price",
                    "take_profit_1", "take_profit_2", "entry_mode",
                    "live_take_profit_2",
                )
            },
            {
                "side": "SHORT",
                "entry_price": 99.0,
                "limit_price": 100.0,
                "stop_price": 110.0,
                "take_profit_1": 75.0,
                "take_profit_2": 0.01,
                "entry_mode": "NFE_DL_SHORT",
                "live_take_profit_2": None,
            },
        )

    def test_retrace_limit_execution_rejects_without_accepted_risk(self):
        execution = evaluate_fixed_execution("LONG", None)

        self.assertEqual(
            (execution.status, execution.reason_codes, execution.facts),
            (
                "rejected",
                ("V2_RETRACE_LIMIT_NO_INTENT",),
                {"execution_intents": {}},
            ),
        )

    def test_rr_cost_risk_gate_rejects_when_ltf_evidence_has_no_entry(self):
        risk = evaluate_fixed_risk("LONG", 133.0, {})

        self.assertEqual(
            (risk.status, risk.reason_codes, risk.facts),
            ("rejected", ("V2_RR_COST_REJECTED",), {"risk_decisions": {}}),
        )

    def test_rr_cost_risk_gate_matches_legacy_long_fee_adjusted_rr(self):
        risk = evaluate_fixed_risk(
            "LONG",
            133.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={"maker_fee": 0.01},
        )

        decision = risk.facts["risk_decisions"]["LONG"]
        self.assertEqual(
            (
                risk.status,
                risk.reason_codes,
                {key: decision[key] for key in (
                    "entry_price", "sl", "tp1", "fee_drag", "net_sl_distance", "reward_risk"
                )},
            ),
            (
                "passed",
                ("V2_RR_COST_LONG_ACCEPTED",),
                {
                    "entry_price": 100.0,
                    "sl": 90.0,
                    "tp1": 133.0,
                    "fee_drag": 1.0,
                    "net_sl_distance": 11.0,
                    "reward_risk": 3.0,
                },
            ),
        )

    def test_rr_cost_risk_gate_matches_legacy_short_dynamic_stop_and_execution_ratio(self):
        risk = evaluate_fixed_risk(
            "SHORT",
            75.0,
            {"entry_ob_high": 110.0, "entry_ob_low": 100.0},
            config_changes={"min_rr": 1.5, "use_dynamic_sl": True},
            market_changes={
                "signal_bar": {"close": 100.0, "execution_close": 200.0},
                "atr": 10.0,
            },
        )

        decision = risk.facts["risk_decisions"]["SHORT"]
        self.assertEqual(
            (
                risk.status,
                risk.reason_codes,
                {key: decision[key] for key in (
                    "entry_price", "sl", "tp1", "fee_drag", "net_sl_distance", "reward_risk"
                )},
            ),
            (
                "passed",
                ("V2_RR_COST_SHORT_ACCEPTED",),
                {
                    "entry_price": 200.0,
                    "sl": 230.0,
                    "tp1": 150.0,
                    "fee_drag": 0.0,
                    "net_sl_distance": 30.0,
                    "reward_risk": 50.0 / 30.0,
                },
            ),
        )

    def test_rr_cost_risk_gate_caps_risk_based_size_by_legacy_leverage(self):
        risk = evaluate_fixed_risk(
            "LONG",
            133.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={
                "limit_order_slippage": 0.0,
                "min_net_profit_r": 3.0,
                "tp1_close_pct": 1.0,
                "risk_pct": 1.0,
                "position_sizing_mode": "risk_based",
                "fixed_margin_usd": 100.0,
                "leverage": 2.0,
                "max_vol_pct": 1.0,
                "max_short_rr": None,
                "max_short_stop_atr": None,
            },
            market_changes={"balance": 1_000.0, "signal_volume": 1_000.0},
        )

        self.assertEqual(
            {
                key: (
                    round(risk.facts["risk_decisions"]["LONG"][key], 10)
                    if key == "reward_risk"
                    else risk.facts["risk_decisions"]["LONG"][key]
                )
                for key in (
                    "entry_price", "limit_price", "sl", "tp1", "tp2", "fee_drag",
                    "net_sl_distance", "reward_risk", "rr_potential", "size",
                    "actual_risk_usd", "target_notional_usd", "actual_notional_usd",
                    "leverage", "position_sizing_mode", "stop_atr",
                )
            },
            {
                "entry_price": 100.0,
                "limit_price": 100.0,
                "sl": 90.0,
                "tp1": 133.0,
                "tp2": 9_999_999.0,
                "fee_drag": 0.0,
                "net_sl_distance": 10.0,
                "reward_risk": 3.3,
                "rr_potential": 3.3,
                "size": 20.0,
                "actual_risk_usd": 200.0,
                "target_notional_usd": 10_000.0,
                "actual_notional_usd": 2_000.0,
                "leverage": 2.0,
                "position_sizing_mode": "risk_based",
                "stop_atr": None,
            },
        )

    def test_rr_cost_risk_gate_matches_legacy_fixed_margin_sizing(self):
        risk = evaluate_fixed_risk(
            "LONG",
            133.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={
                "position_sizing_mode": "fixed_margin",
                "fixed_margin_usd": 200.0,
                "leverage": 3.0,
            },
            market_changes={"balance": 1_000.0},
        )

        decision = risk.facts["risk_decisions"]["LONG"]
        self.assertEqual(
            {key: decision[key] for key in (
                "size",
                "actual_risk_usd",
                "target_notional_usd",
                "actual_notional_usd",
                "leverage",
                "position_sizing_mode",
            )},
            {
                "size": 6.0,
                "actual_risk_usd": 60.0,
                "target_notional_usd": 600.0,
                "actual_notional_usd": 600.0,
                "leverage": 1.0,
                "position_sizing_mode": "fixed_margin",
            },
        )

    def test_rr_cost_risk_gate_preserves_legacy_short_quality_rejection(self):
        risk = evaluate_fixed_risk(
            "SHORT",
            75.0,
            {"entry_ob_high": 110.0, "entry_ob_low": 100.0},
            config_changes={"min_rr": 1.0, "max_short_rr": 2.0},
            market_changes={"atr": 10.0},
        )

        self.assertEqual(
            (risk.status, risk.reason_codes, risk.facts),
            (
                "rejected",
                ("V2_SHORT_QUALITY_FILTER",),
                {
                    "risk_decisions": {},
                    "risk_rejections": {
                        "SHORT": {
                            "reason": "SHORT_QUALITY_FILTER",
                            "rr_potential": 2.5,
                            "stop_atr": 1.0,
                        }
                    },
                },
            ),
        )

    def test_rr_cost_risk_gate_preserves_legacy_leverage_rejection(self):
        risk = evaluate_fixed_risk(
            "LONG",
            133.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={"min_rr": 1.0},
            market_changes={"balance": 0.0},
        )

        self.assertEqual(
            (risk.status, risk.reason_codes, risk.facts),
            (
                "rejected",
                ("V2_INSUFFICIENT_MARGIN_FOR_LEVERAGE",),
                {
                    "risk_decisions": {},
                    "risk_rejections": {
                        "LONG": {
                            "reason": "INSUFFICIENT_MARGIN_FOR_LEVERAGE",
                            "entry_price": 100.0,
                            "leverage": 1.0,
                            "position_sizing_mode": "risk_based",
                        }
                    },
                },
            ),
        )

    def test_rr_cost_risk_gate_preserves_legacy_net_profit_rejection(self):
        risk = evaluate_fixed_risk(
            "LONG",
            105.0,
            {"entry_ob_high": 100.0, "entry_ob_low": 90.0},
            config_changes={"min_rr": 0.0, "min_net_profit_r": 1.0},
        )

        self.assertEqual(
            (risk.status, risk.reason_codes, risk.facts),
            (
                "rejected",
                ("V2_RETRACE_FILLED_BUT_RR_FILTERED",),
                {
                    "risk_decisions": {},
                    "risk_rejections": {
                        "LONG": {
                            "reason": "RETRACE_FILLED_BUT_RR_FILTERED",
                            "entry_price": 100.0,
                            "limit_price": 100.0,
                            "sl": 90.0,
                            "tp1": 105.0,
                            "tp2": 9_999_999.0,
                            "rr_potential": 0.5,
                        }
                    },
                },
            ),
        )

    def test_closed_bar_context_releases_only_available_htf_and_ltf_rows(self):
        signal_time = pd.Timestamp("2026-01-02 12:00:00", tz="UTC")
        htf = pd.DataFrame(
            {"close": [100.0, 101.0, 999.0]},
            index=pd.DatetimeIndex(
                ["2026-01-02 10:00:00", "2026-01-02 11:00:00", "2026-01-02 12:00:00"]
            ),
        )
        ltf = pd.DataFrame(
            {"close": [100.0, 101.0, 102.0, 999.0]},
            index=pd.DatetimeIndex(
                [
                    "2026-01-02 11:30:00",
                    "2026-01-02 11:45:00",
                    "2026-01-02 12:00:00",
                    "2026-01-02 12:15:00",
                ]
            ),
        )
        stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
        stages[0] = StageSelection(
            DecisionStage.MARKET_CONTEXT,
            ("v2.closed_bar_context",),
            plugin_config={
                "v2.closed_bar_context": {
                    "htf_timeframe": "1h",
                }
            },
        )

        result = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
            DecisionTemplate("v2_market_context_test", "1", tuple(stages)),
            DecisionContext(
                signal_time=signal_time,
                market={
                    "htf_ohlcv": htf,
                    "ltf_ohlcv": ltf,
                    "legacy_scan": StrategyDecision,
                    "decision_sink": [],
                },
            ),
        )

        self.assertEqual(
            result.plugin_results[0].to_dict(),
            {
                "plugin_id": "v2.closed_bar_context",
                "stage": "market_context",
                "status": "passed",
                "reason_codes": ["V2_CLOSED_BAR_CONTEXT_AVAILABLE"],
                "facts": {
                    "htf_rows": 2,
                    "ltf_rows": 3,
                    "latest_htf_open": "2026-01-02T11:00:00+00:00",
                    "latest_htf_release": "2026-01-02T12:00:00+00:00",
                    "latest_ltf_open": "2026-01-02T12:00:00+00:00",
                },
                "score_contribution": 0.0,
                "available_at": "2026-01-02T12:00:00+00:00",
                "time_safe": True,
                "profile": "default",
                "requirements": [],
            },
        )

    def test_direction_module_matches_legacy_long_and_short_permissions(self):
        signal_time = pd.Timestamp("2026-01-02 12:00:00", tz="UTC")
        frame = pd.DataFrame(
            {"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0]},
            index=pd.DatetimeIndex(["2026-01-02 10:00:00"]),
        )

        for mode, bias_1d, bias_4h, allow_long, allow_short, expected in (
            ("NONE", "NONE", "NONE", True, True, ("BOTH", True, True)),
            ("4H", "NONE", "LONG", True, True, ("LONG", True, False)),
            ("4H", "NONE", "SHORT", True, True, ("SHORT", False, True)),
            ("4H_1D", "LONG", "LONG", True, True, ("LONG", True, False)),
            ("4H_1D", "LONG", "SHORT", True, True, ("NONE", False, False)),
            ("NONE", "NONE", "NONE", False, True, ("SHORT", False, True)),
        ):
            with self.subTest(mode=mode, bias_1d=bias_1d, bias_4h=bias_4h):
                direction = evaluate_v2_direction(
                    frame,
                    signal_time,
                    mode=mode,
                    bias_1d=bias_1d,
                    bias_4h=bias_4h,
                    allow_long_entries=allow_long,
                    allow_short_entries=allow_short,
                )

                self.assertEqual(
                    (
                        direction.facts["permission_direction"],
                        direction.facts["allowed_long"],
                        direction.facts["allowed_short"],
                    ),
                    expected,
                )

    def test_direction_uses_confirmed_htf_structure_without_future_rows(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        index = pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h")
        htf = pd.DataFrame(
            {
                "open": [7.0, 10.0, 8.0, 15.0, 10.0],
                "high": [10.0, 15.0, 12.0, 16.0, 14.0],
                "low": [5.0, 8.0, 6.0, 9.0, 7.0],
                "close": [7.0, 10.0, 8.0, 16.0, 10.0],
            },
            index=index,
        )
        future = pd.DataFrame(
            {"open": [10.0], "high": [20.0], "low": [0.0], "close": [10.0]},
            index=[pd.Timestamp("2026-01-02 05:00:00")],
        )
        base = evaluate_v2_direction(htf, signal_time)
        with_future = evaluate_v2_direction(pd.concat((htf, future)), signal_time)

        self.assertEqual(
            (base.to_dict(), with_future.to_dict()),
            (
                {
                    "plugin_id": "v2.htf_structure_direction",
                    "stage": "direction",
                    "status": "passed",
                    "reason_codes": ["V2_DIRECTION_LONG_ALLOWED"],
                    "facts": {
                        "permission_direction": "BOTH",
                        "allowed_long": True,
                        "allowed_short": True,
                        "structure_long": True,
                        "structure_short": False,
                        "direction": "LONG",
                    },
                    "score_contribution": 0.0,
                    "available_at": signal_time.isoformat(),
                    "time_safe": True,
                    "profile": "default",
                    "requirements": [],
                },
            )
            * 2,
        )

    def test_direction_uses_confirmed_short_htf_structure(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        htf = pd.DataFrame(
            {
                "open": [12.0, 8.0, 10.0, 5.0, 9.0],
                "high": [15.0, 12.0, 14.0, 11.0, 13.0],
                "low": [10.0, 5.0, 8.0, 4.0, 6.0],
                "close": [12.0, 8.0, 10.0, 4.0, 9.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        result = evaluate_v2_direction(htf, signal_time)

        self.assertEqual(
            (result.status, result.reason_codes, result.facts),
            (
                "passed",
                ("V2_DIRECTION_SHORT_ALLOWED",),
                {
                    "permission_direction": "BOTH",
                    "direction": "SHORT",
                    "allowed_long": True,
                    "allowed_short": True,
                    "structure_long": False,
                    "structure_short": True,
                },
            ),
        )

    def test_target_exposes_legacy_target_and_invalidation_by_side(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        long_htf = pd.DataFrame(
            {
                "open": [7.0, 10.0, 8.0, 15.0, 10.0],
                "high": [10.0, 15.0, 12.0, 16.0, 14.0],
                "low": [5.0, 8.0, 6.0, 9.0, 7.0],
                "close": [7.0, 10.0, 8.0, 16.0, 10.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        short_htf = pd.DataFrame(
            {
                "open": [12.0, 8.0, 10.0, 5.0, 9.0],
                "high": [15.0, 12.0, 14.0, 11.0, 13.0],
                "low": [10.0, 5.0, 8.0, 4.0, 6.0],
                "close": [12.0, 8.0, 10.0, 4.0, 9.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
        stages[0] = StageSelection(
            DecisionStage.MARKET_CONTEXT,
            ("v2.closed_bar_context",),
            plugin_config={"v2.closed_bar_context": {"htf_timeframe": "1h"}},
        )
        stages[1] = StageSelection(
            DecisionStage.DIRECTION,
            ("v2.htf_structure_direction",),
            plugin_config={
                "v2.htf_structure_direction": {"htf_n": 1, "ob_range_type": "full"}
            },
        )
        stages[2] = StageSelection(
            DecisionStage.TARGET,
            ("v2.swing_liquidity_target",),
            plugin_config={
                "v2.swing_liquidity_target": {"htf_n": 1, "ob_range_type": "full"}
            },
        )

        for side, htf, target_price, invalidation in (
            ("LONG", long_htf, 15.0, 6.0),
            ("SHORT", short_htf, 5.0, 14.0),
        ):
            with self.subTest(side=side):
                target = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
                    DecisionTemplate("v2_target_test", "1", tuple(stages)),
                    DecisionContext(
                        signal_time=signal_time,
                        market={
                            "htf_ohlcv": htf,
                            "ltf_ohlcv": htf,
                            "mode": "NONE",
                            "bias_1d": "NONE",
                            "bias_4h": "NONE",
                            "allow_long_entries": True,
                            "allow_short_entries": True,
                            "legacy_scan": StrategyDecision,
                            "decision_sink": [],
                        },
                    ),
                ).plugin_results[2]

                self.assertEqual(
                    target.to_dict(),
                    {
                        "plugin_id": "v2.swing_liquidity_target",
                        "stage": "target",
                        "status": "passed",
                        "reason_codes": [f"V2_TARGET_{side}_AVAILABLE"],
                        "facts": {
                            "targets": {
                                side: {
                                    "target": target_price,
                                    "invalidation": invalidation,
                                }
                            }
                        },
                        "score_contribution": 0.0,
                        "available_at": signal_time.isoformat(),
                        "time_safe": True,
                        "profile": "default",
                        "requirements": [],
                    },
                )

    def test_htf_retrace_evidence_matches_legacy_condition_by_side(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        long_htf = pd.DataFrame(
            {
                "open": [7.0, 10.0, 8.0, 15.0, 10.0],
                "high": [10.0, 15.0, 12.0, 16.0, 14.0],
                "low": [5.0, 8.0, 6.0, 9.0, 7.0],
                "close": [7.0, 10.0, 8.0, 16.0, 10.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        short_htf = pd.DataFrame(
            {
                "open": [12.0, 8.0, 10.0, 5.0, 9.0],
                "high": [15.0, 12.0, 14.0, 11.0, 13.0],
                "low": [10.0, 5.0, 8.0, 4.0, 6.0],
                "close": [12.0, 8.0, 10.0, 4.0, 9.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
        for index, stage, plugin_id in (
            (0, DecisionStage.MARKET_CONTEXT, "v2.closed_bar_context"),
            (1, DecisionStage.DIRECTION, "v2.htf_structure_direction"),
            (2, DecisionStage.TARGET, "v2.swing_liquidity_target"),
            (3, DecisionStage.EVIDENCE, "v2.htf_ob_retrace"),
        ):
            config = (
                {"htf_timeframe": "1h"}
                if stage is DecisionStage.MARKET_CONTEXT
                else {"htf_n": 1, "ob_range_type": "full"}
            )
            stages[index] = StageSelection(
                stage,
                (plugin_id,),
                plugin_config={plugin_id: config},
            )

        for side, htf, signal_bar, ob_high, ob_low in (
            ("LONG", long_htf, {"high": 13.0, "low": 11.0, "close": 7.0}, 12.0, 6.0),
            ("SHORT", short_htf, {"high": 9.0, "low": 7.0, "close": 10.0}, 14.0, 8.0),
        ):
            with self.subTest(side=side):
                evidence = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
                    DecisionTemplate("v2_htf_retrace_test", "1", tuple(stages)),
                    DecisionContext(
                        signal_time=signal_time,
                        market={
                            "htf_ohlcv": htf,
                            "ltf_ohlcv": htf,
                            "signal_bar": signal_bar,
                            "mode": "NONE",
                            "bias_1d": "NONE",
                            "bias_4h": "NONE",
                            "allow_long_entries": True,
                            "allow_short_entries": True,
                            "legacy_scan": StrategyDecision,
                            "decision_sink": [],
                        },
                    ),
                ).plugin_results[3]

                self.assertEqual(
                    (evidence.status, evidence.reason_codes, evidence.facts),
                    (
                        "passed",
                        (f"V2_HTF_OB_RETRACE_{side}_CONFIRMED",),
                        {
                            "evidence": {
                                side: {
                                    "ob_high": ob_high,
                                    "ob_low": ob_low,
                                    "retraced": True,
                                }
                            }
                        },
                    ),
                )

    def test_ltf_confirmation_matches_legacy_structure_break_by_side(self):
        signal_time = pd.Timestamp("2026-01-02 05:00:00", tz="UTC")
        long_htf = pd.DataFrame(
            {
                "open": [7.0, 10.0, 8.0, 15.0, 10.0],
                "high": [10.0, 15.0, 12.0, 16.0, 14.0],
                "low": [5.0, 8.0, 6.0, 9.0, 7.0],
                "close": [7.0, 10.0, 8.0, 16.0, 10.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        long_ltf = pd.DataFrame(
            {
                "open": [7.0, 10.0, 8.0, 12.0, 15.0],
                "high": [10.0, 15.0, 12.0, 14.0, 16.0],
                "low": [5.0, 8.0, 6.0, 9.0, 10.0],
                "close": [7.0, 10.0, 8.0, 12.0, 16.0],
            },
            index=pd.date_range("2026-01-02 04:00:00", periods=5, freq="15min"),
        )
        short_htf = pd.DataFrame(
            {
                "open": [12.0, 8.0, 10.0, 5.0, 9.0],
                "high": [15.0, 12.0, 14.0, 11.0, 13.0],
                "low": [10.0, 5.0, 8.0, 4.0, 6.0],
                "close": [12.0, 8.0, 10.0, 4.0, 9.0],
            },
            index=pd.date_range("2026-01-02 00:00:00", periods=5, freq="1h"),
        )
        short_ltf = pd.DataFrame(
            {
                "open": [12.0, 8.0, 10.0, 6.0, 4.0],
                "high": [15.0, 12.0, 14.0, 11.0, 10.0],
                "low": [10.0, 5.0, 8.0, 4.0, 3.0],
                "close": [12.0, 8.0, 10.0, 6.0, 3.0],
            },
            index=pd.date_range("2026-01-02 04:00:00", periods=5, freq="15min"),
        )
        stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
        stages[0] = StageSelection(
            DecisionStage.MARKET_CONTEXT,
            ("v2.closed_bar_context",),
            plugin_config={"v2.closed_bar_context": {"htf_timeframe": "1h"}},
        )
        for index, stage, plugin_id in (
            (1, DecisionStage.DIRECTION, "v2.htf_structure_direction"),
            (2, DecisionStage.TARGET, "v2.swing_liquidity_target"),
        ):
            stages[index] = StageSelection(
                stage,
                (plugin_id,),
                plugin_config={plugin_id: {"htf_n": 1, "ob_range_type": "full"}},
            )
        stages[3] = StageSelection(
            DecisionStage.EVIDENCE,
            ("v2.htf_ob_retrace", "v2.ltf_structure_confirmation"),
            plugin_config={
                "v2.htf_ob_retrace": {"htf_n": 1, "ob_range_type": "full"},
                "v2.ltf_structure_confirmation": {
                    "ltf_n": 1,
                    "ob_range_type": "full",
                },
            },
        )

        for side, htf, ltf, signal_bar, break_level, entry_high, entry_low in (
            ("LONG", long_htf, long_ltf, {"high": 16.0, "low": 11.0, "close": 16.0}, 15.0, 12.0, 6.0),
            ("SHORT", short_htf, short_ltf, {"high": 9.0, "low": 3.0, "close": 3.0}, 5.0, 14.0, 8.0),
        ):
            with self.subTest(side=side):
                confirmation = DecisionPipeline(nfe_v2_plugin_registry()).evaluate(
                    DecisionTemplate("v2_ltf_confirmation_test", "1", tuple(stages)),
                    DecisionContext(
                        signal_time=signal_time,
                        market={
                            "htf_ohlcv": htf,
                            "ltf_ohlcv": ltf,
                            "signal_bar": signal_bar,
                            "mode": "NONE",
                            "bias_1d": "NONE",
                            "bias_4h": "NONE",
                            "allow_long_entries": True,
                            "allow_short_entries": True,
                            "legacy_scan": StrategyDecision,
                            "decision_sink": [],
                        },
                    ),
                ).plugin_results[4]

                self.assertEqual(
                    (confirmation.status, confirmation.reason_codes, confirmation.facts),
                    (
                        "passed",
                        (f"V2_LTF_STRUCTURE_{side}_CONFIRMED",),
                        {
                            "evidence": {
                                side: {
                                    "break_level": break_level,
                                    "close": signal_bar["close"],
                                    "entry_ob_high": entry_high,
                                    "entry_ob_low": entry_low,
                                }
                            }
                        },
                    ),
                )

    def test_ltf_confirmation_requires_htf_retrace_upstream(self):
        stages = list(NFE_V2_COMPATIBLE_TEMPLATE.stages)
        stages[3] = StageSelection(
            DecisionStage.EVIDENCE,
            ("v2.ltf_structure_confirmation", "v2.htf_ob_retrace"),
            plugin_config={
                "v2.ltf_structure_confirmation": {
                    "ltf_n": 1,
                    "ob_range_type": "full",
                },
                "v2.htf_ob_retrace": {"htf_n": 1, "ob_range_type": "full"},
            },
        )

        with self.assertRaisesRegex(
            DecisionEngineConfigError,
            "required provider is not upstream: v2.htf_ob_retrace before v2.ltf_structure_confirmation",
        ):
            nfe_v2_plugin_registry().resolve_template(
                DecisionTemplate("v2_evidence_order_test", "1", tuple(stages))
            )

    def test_registry_catalog_tracks_identified_and_transitional_modules_separately(self):
        catalog = nfe_v2_plugin_registry().catalog()

        self.assertEqual(
            catalog["counts"],
            {
                "identified": 0,
                "transitional": 7,
                "implemented": 0,
                "parity-verified": 8,
                "deprecated": 0,
            },
        )
        identified = {
            module["module_id"]
            for module in catalog["modules"]
            if module["status"] == "identified"
        }
        self.assertEqual(
            identified,
            set(),
        )
        self.assertEqual(
            {
                module["module_id"]
                for module in catalog["modules"]
                if module["status"] == "parity-verified"
            },
            {
                "v2.closed_bar_context",
                "v2.htf_structure_direction",
                "v2.swing_liquidity_target",
                "v2.htf_ob_retrace",
                "v2.ltf_structure_confirmation",
                "v2.rr_cost_risk_gate",
                "v2.retrace_limit_execution",
                "v2.atr_structural_management",
            },
        )

    def test_compatible_template_maps_and_validates_every_decision_stage(self):
        template = NFEV2DecisionTemplate(LegacyV2Stub(StrategyDecision()))

        self.assertEqual(
            [selection.stage for selection in template.template.stages],
            list(DecisionStage),
        )
        self.assertEqual(
            [selection.plugin_ids for selection in template.template.stages],
            [(NFE_V2_PLUGIN_IDS[stage],) for stage in DecisionStage],
        )
        self.assertEqual(template.template, NFE_V2_COMPATIBLE_TEMPLATE)

    def test_incomplete_template_configuration_fails_closed(self):
        incomplete = DecisionTemplate(
            template_id=NFE_V2_COMPATIBLE_TEMPLATE.template_id,
            version=NFE_V2_COMPATIBLE_TEMPLATE.version,
            stages=NFE_V2_COMPATIBLE_TEMPLATE.stages[:-1],
        )

        with self.assertRaisesRegex(DecisionEngineConfigError, "missing stage: management"):
            NFEV2DecisionTemplate(LegacyV2Stub(StrategyDecision()), template=incomplete)

    def test_wrong_plugin_metadata_fails_closed(self):
        plugins = {
            plugin_id: PluginMetadata(plugin_id, "1", stage, stage.value)
            for stage, plugin_id in NFE_V2_PLUGIN_IDS.items()
        }
        plugins[NFE_V2_PLUGIN_IDS[DecisionStage.EVIDENCE]] = PluginMetadata(
            NFE_V2_PLUGIN_IDS[DecisionStage.EVIDENCE],
            "1",
            DecisionStage.RISK,
            DecisionStage.RISK.value,
        )

        with self.assertRaisesRegex(DecisionEngineConfigError, "stage mismatch"):
            NFEV2DecisionTemplate(
                LegacyV2Stub(StrategyDecision()), registry=PluginRegistry(plugins)
            )

    def test_incompatible_plugin_metadata_version_fails_closed(self):
        plugins = {
            plugin_id: PluginMetadata(plugin_id, "1", stage, stage.value)
            for stage, plugin_id in NFE_V2_PLUGIN_IDS.items()
        }
        plugins[NFE_V2_PLUGIN_IDS[DecisionStage.EXECUTION]] = PluginMetadata(
            NFE_V2_PLUGIN_IDS[DecisionStage.EXECUTION],
            "2",
            DecisionStage.EXECUTION,
            DecisionStage.EXECUTION.value,
        )

        with self.assertRaisesRegex(DecisionEngineConfigError, "plugin version mismatch"):
            NFEV2DecisionTemplate(
                LegacyV2Stub(StrategyDecision()), registry=PluginRegistry(plugins)
            )

    def test_delegates_retrace_order_without_gating_or_rewriting(self):
        expected = StrategyDecision(retrace_order={"type": "LONG", "entry_price": 100.0})
        legacy = LegacyV2Stub(expected)
        template = NFEV2DecisionTemplate(legacy)
        args = (object(), pd.Series({"ATR_14": 10.0}), pd.Series({"close": 100.0}), pd.Timestamp("2026-01-01"), 10_000.0, object())

        actual = template.scan_entry_signal(*args)

        self.assertIs(actual, expected)
        self.assertEqual(legacy.scan_calls, [args])

    def test_delegates_retrace_order_from_a_supplied_nfe_v2_strategy(self):
        expected = StrategyDecision(retrace_order={"type": "SHORT", "entry_price": 200.0})
        legacy = NFEV2Strategy()
        template = NFEV2DecisionTemplate(legacy)
        args = (object(), pd.Series(dtype=float), pd.Series(dtype=float), pd.Timestamp("2026-01-01"), 10_000.0, object())

        with patch.object(legacy, "scan_entry_signal", return_value=expected) as scan:
            actual = template.scan_entry_signal(*args)

        self.assertIs(actual, expected)
        scan.assert_called_once_with(*args)
        self.assertEqual(
            [result.stage for result in template.last_pipeline_result.plugin_results],
            list(DecisionStage),
        )
        self.assertTrue(
            all(result.time_safe for result in template.last_pipeline_result.plugin_results)
        )
        self.assertTrue(
            all(
                result.score_contribution == 0.0
                for result in template.last_pipeline_result.plugin_results
            )
        )
        self.assertEqual(
            template.last_pipeline_result.plugin_results[-2].reason_codes,
            ("NFE_V2_RETRACE_ORDER_SHORT",),
        )

    def test_delegates_missed_and_no_decision_outcomes_without_gating(self):
        for expected in (StrategyDecision(missed=[{"reason": "NO_CAPACITY"}]), StrategyDecision()):
            with self.subTest(expected=expected):
                legacy = LegacyV2Stub(expected)
                template = NFEV2DecisionTemplate(legacy)

                actual = template.scan_entry_signal(
                    object(), pd.Series(dtype=float), pd.Series(dtype=float), pd.Timestamp("2026-01-01"), 10_000.0, object()
                )

                self.assertIs(actual, expected)
                execution = template.last_pipeline_result.plugin_results[-2]
                expected_reason = (
                    f"NFE_V2_MISSED_{expected.missed[0]['reason']}"
                    if expected.missed
                    else "NFE_V2_NO_DECISION"
                )
                self.assertEqual(execution.reason_codes, (expected_reason,))

    def test_real_nfe_v2_long_and_short_decisions_match_legacy_exactly(self):
        prev = pd.Series({"bias_1d": "NONE", "bias_4h": "NONE", "ATR_14": 10.0})
        curr = pd.Series({"open": 100.0, "high": 120.0, "low": 80.0, "close": 100.0})
        cfg = RunConfig(tp1_close_pct=0.5)
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                legacy, now = prepared_nfe_v2(side)
                compatible, _ = prepared_nfe_v2(side)
                backtester = NFEV2BacktesterStub(now, side)

                expected = legacy.scan_entry_signal(
                    backtester, prev, curr, now, 10_000.0, cfg
                )
                adapter = NFEV2DecisionTemplate(compatible)
                actual = adapter.scan_entry_signal(
                    backtester, prev, curr, now, 10_000.0, cfg
                )

                self.assertEqual(actual, expected)
                self.assertEqual(len(adapter.last_pipeline_result.plugin_results), 7)
                self.assertEqual(
                    adapter.last_pipeline_result.plugin_results[-2].reason_codes,
                    (f"NFE_V2_RETRACE_ORDER_{side}",),
                )

    def test_future_ltf_rows_do_not_change_closed_bar_pipeline_decision(self):
        prev = pd.Series({"bias_1d": "NONE", "bias_4h": "NONE", "ATR_14": 10.0})
        curr = pd.Series({"open": 100.0, "high": 120.0, "low": 80.0, "close": 100.0})
        cfg = RunConfig(tp1_close_pct=0.5)
        first, now = prepared_nfe_v2("LONG")
        second, _ = prepared_nfe_v2("LONG")
        first_adapter = NFEV2DecisionTemplate(first)
        second_adapter = NFEV2DecisionTemplate(second)

        first_decision = first_adapter.scan_entry_signal(
            NFEV2BacktesterStub(now, "LONG"), prev, curr, now, 10_000.0, cfg
        )
        second_decision = second_adapter.scan_entry_signal(
            NFEV2BacktesterStub(now, "LONG", future_row=True),
            prev,
            curr,
            now,
            10_000.0,
            cfg,
        )

        self.assertEqual(first_decision, second_decision)
        self.assertTrue(
            all(
                result.available_at == now.tz_localize("UTC")
                for result in second_adapter.last_pipeline_result.plugin_results
            )
        )

    def test_delegates_legacy_structural_trailing_stop_management(self):
        legacy = NFEV2Strategy()
        template = NFEV2DecisionTemplate(legacy)
        position = {"type": "LONG", "sl": 99.0}
        args = (position, object(), pd.Timestamp("2026-01-01"))

        def update_stop(active_position, _backtester, _curr_time):
            active_position["sl"] = 101.0

        with patch.object(legacy, "_update_trailing_stop", side_effect=update_stop) as update:
            result = template.after_manage_position(*args)

        self.assertIsNone(result)
        self.assertEqual(position["sl"], 101.0)
        update.assert_called_once_with(*args)

    def test_real_atr_structural_trailing_stop_matches_legacy_for_both_sides(self):
        for side, initial_sl, expected_sl in (("LONG", 90.0, 100.0), ("SHORT", 110.0, 100.0)):
            with self.subTest(side=side):
                legacy, now = prepared_nfe_v2(side)
                compatible, _ = prepared_nfe_v2(side)
                backtester = NFEV2BacktesterStub(now, side)
                legacy_position = {"type": side, "sl": initial_sl}
                compatible_position = dict(legacy_position)

                legacy.after_manage_position(legacy_position, backtester, now)
                NFEV2DecisionTemplate(compatible).after_manage_position(
                    compatible_position, backtester, now
                )

                self.assertEqual(compatible_position, legacy_position)
                self.assertEqual(compatible_position["sl"], expected_sl)


if __name__ == "__main__":
    unittest.main()
