"""Decision Engine compatibility adapter for the frozen NFE V2 strategy.

The seven executable providers record which legacy V2 responsibility owns each
Decision Engine stage.  The execution provider invokes the supplied legacy
strategy, so no score or additional factor can change its decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence

import pandas as pd

from decision_engine import (
    DecisionEngineConfigError,
    DecisionContext,
    DecisionPipeline,
    DecisionStage,
    DecisionTemplate,
    PluginMetadata,
    PluginResult,
    PluginRegistry,
    StageSelection,
)
from nfe_strategy import NFEDoubleLevelStrategy
from strategy_base import BacktestStrategy, StrategyDecision

if TYPE_CHECKING:
    from backtest_config import RunConfig
    from strategy_engine import MultiTimeframeBacktester


NFE_V2_TEMPLATE_ID = "nfe_v2_compatible"
NFE_V2_TEMPLATE_VERSION = "1"
V2_MODULAR_TEMPLATE_ID = "v2_modular"
V2_MODULAR_TEMPLATE_VERSION = "1"

# Each mapping identifies an already-existing V2 responsibility.  The adapter
# deliberately does not evaluate these as new factors; legacy V2 remains the
# single source of entry, pending-order, and trailing-stop behaviour.
NFE_V2_PLUGIN_IDS: Mapping[DecisionStage, str] = {
    DecisionStage.MARKET_CONTEXT: "nfe_v2.closed_bar_context",
    DecisionStage.DIRECTION: "nfe_v2.htf_structure",
    DecisionStage.TARGET: "nfe_v2.liquidity_target",
    DecisionStage.EVIDENCE: "nfe_v2.ltf_retrace_confirmation",
    DecisionStage.RISK: "nfe_v2.rr_quality",
    DecisionStage.EXECUTION: "nfe_v2.retrace_limit_order",
    DecisionStage.MANAGEMENT: "nfe_v2.structural_trailing_stop",
}


class V2ClosedBarContextPlugin:
    """Expose the exact HTF release and LTF prefix visible to legacy V2."""

    metadata = PluginMetadata(
        "v2.closed_bar_context",
        "1",
        DecisionStage.MARKET_CONTEXT,
        "closed-bar HTF/LTF market context",
        status="parity-verified",
        inputs=("htf_ohlcv", "ltf_ohlcv"),
        outputs=("market_context", "available_at"),
        config_fields=("htf_timeframe",),
        required_config_fields=("htf_timeframe",),
    )

    @staticmethod
    def _utc_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
        index = pd.DatetimeIndex(frame.index)
        return index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        htf_index = self._utc_index(context.market["htf_ohlcv"])
        ltf_index = self._utc_index(context.market["ltf_ohlcv"])
        htf_delta = pd.Timedelta(config["htf_timeframe"])
        available_htf = htf_index[htf_index + htf_delta <= context.signal_time]
        available_ltf = ltf_index[ltf_index <= context.signal_time]
        latest_htf_open = available_htf[-1]
        latest_ltf_open = available_ltf[-1]
        return PluginResult.passed(
            self.metadata.plugin_id,
            self.metadata.stage,
            "V2_CLOSED_BAR_CONTEXT_AVAILABLE",
            available_at=context.signal_time,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
            facts={
                "htf_rows": len(available_htf),
                "ltf_rows": len(available_ltf),
                "latest_htf_open": latest_htf_open.isoformat(),
                "latest_htf_release": (latest_htf_open + htf_delta).isoformat(),
                "latest_ltf_open": latest_ltf_open.isoformat(),
            },
        )


def _available_htf_structure(
    context: DecisionContext,
    upstream_results: Sequence[PluginResult],
    config: Mapping[str, object],
) -> pd.Series:
    market_context = next(
        result for result in upstream_results if result.stage is DecisionStage.MARKET_CONTEXT
    )
    latest_htf_open = pd.Timestamp(market_context.facts["latest_htf_open"])
    cached = context.market.get("precomputed_htf_structure")
    if cached is not None:
        return cached.loc[cached.index.asof(context.signal_time)]
    htf = context.market["htf_ohlcv"].copy()
    htf.index = V2ClosedBarContextPlugin._utc_index(htf)
    htf = htf.loc[:latest_htf_open]
    structure = NFEDoubleLevelStrategy(
        htf_n=int(config["htf_n"]),
        ob_range_type=str(config["ob_range_type"]),
    )._precompute_htf_structures(htf)
    return structure.loc[structure.index.asof(context.signal_time)]


class V2HTFStructureDirectionPlugin:
    """Apply the long/short permission portion of the legacy V2 direction flow."""

    metadata = PluginMetadata(
        "v2.htf_structure_direction",
        "1",
        DecisionStage.DIRECTION,
        "confirmed HTF swing and BOS direction",
        status="parity-verified",
        inputs=("market_context", "htf_swings"),
        outputs=("direction",),
        config_fields=("htf_n", "ob_range_type"),
        required_config_fields=("htf_n", "ob_range_type"),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        market = context.market
        allowed_long = bool(market["allow_long_entries"])
        allowed_short = bool(market["allow_short_entries"])
        mode = market["mode"]
        bias_1d = market.get("bias_1d", "NONE")
        bias_4h = market.get("bias_4h", "NONE")
        if mode == "4H":
            allowed_long &= bias_4h == "LONG"
            allowed_short &= bias_4h == "SHORT"
        elif mode == "4H_1D":
            allowed_long &= bias_4h == "LONG" and bias_1d == "LONG"
            allowed_short &= bias_4h == "SHORT" and bias_1d == "SHORT"

        permission_direction = (
            "BOTH"
            if allowed_long and allowed_short
            else "LONG"
            if allowed_long
            else "SHORT"
            if allowed_short
            else "NONE"
        )

        state = _available_htf_structure(context, upstream_results, config)
        structure_long = pd.notna(state["htf_long_ob_high"])
        structure_short = pd.notna(state["htf_short_ob_low"])
        can_long = allowed_long and structure_long
        can_short = allowed_short and structure_short
        direction = (
            "BOTH"
            if can_long and can_short
            else "LONG"
            if can_long
            else "SHORT"
            if can_short
            else "NONE"
        )
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if direction != "NONE" else "rejected",
            reason_codes=(f"V2_DIRECTION_{direction}_ALLOWED",),
            facts={
                "permission_direction": permission_direction,
                "direction": direction,
                "allowed_long": allowed_long,
                "allowed_short": allowed_short,
                "structure_long": bool(structure_long),
                "structure_short": bool(structure_short),
            },
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2SwingLiquidityTargetPlugin:
    """Expose the active legacy V2 swing target and invalidation by side."""

    metadata = PluginMetadata(
        "v2.swing_liquidity_target",
        "1",
        DecisionStage.TARGET,
        "HTF swing liquidity target and invalidation",
        status="parity-verified",
        inputs=("direction", "htf_swings"),
        outputs=("target", "invalidation"),
        config_fields=("htf_n", "ob_range_type"),
        required_config_fields=("htf_n", "ob_range_type"),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        state = _available_htf_structure(context, upstream_results, config)
        direction = upstream_results[-1].facts["direction"]
        targets = {}
        if direction in ("LONG", "BOTH") and pd.notna(state["htf_target_high"]):
            targets["LONG"] = {
                "target": float(state["htf_target_high"]),
                "invalidation": float(state["htf_long_ob_low"]),
            }
        if direction in ("SHORT", "BOTH") and pd.notna(state["htf_target_low"]):
            targets["SHORT"] = {
                "target": float(state["htf_target_low"]),
                "invalidation": float(state["htf_short_ob_high"]),
            }
        target_direction = (
            "BOTH" if len(targets) == 2 else next(iter(targets), "NONE")
        )
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if targets else "rejected",
            reason_codes=(f"V2_TARGET_{target_direction}_AVAILABLE",),
            facts={"targets": targets},
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2HTFOrderBlockRetracePlugin:
    """Confirm the legacy V2 high-timeframe Order Block retrace."""

    metadata = PluginMetadata(
        "v2.htf_ob_retrace",
        "1",
        DecisionStage.EVIDENCE,
        "HTF Order Block retrace evidence",
        status="parity-verified",
        inputs=("market_context", "target", "htf_order_blocks"),
        outputs=("evidence",),
        config_fields=("htf_n", "ob_range_type"),
        required_config_fields=("htf_n", "ob_range_type"),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        state = _available_htf_structure(context, upstream_results, config)
        targets = upstream_results[-1].facts["targets"]
        bar = context.market["signal_bar"]
        evidence = {}
        if (
            "LONG" in targets
            and bar["low"] <= state["htf_long_ob_high"]
            and bar["close"] >= state["htf_long_ob_low"]
        ):
            evidence["LONG"] = {
                "ob_high": float(state["htf_long_ob_high"]),
                "ob_low": float(state["htf_long_ob_low"]),
                "retraced": True,
            }
        if (
            "SHORT" in targets
            and bar["high"] >= state["htf_short_ob_low"]
            and bar["close"] <= state["htf_short_ob_high"]
        ):
            evidence["SHORT"] = {
                "ob_high": float(state["htf_short_ob_high"]),
                "ob_low": float(state["htf_short_ob_low"]),
                "retraced": True,
            }
        evidence_direction = next(iter(evidence), "NONE")
        reason = (
            f"V2_HTF_OB_RETRACE_{evidence_direction}_CONFIRMED"
            if evidence
            else "V2_HTF_OB_RETRACE_NONE"
        )
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if evidence else "rejected",
            reason_codes=(reason,),
            facts={"evidence": evidence},
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2LTFStructureConfirmationPlugin:
    """Confirm the legacy V2 lower-timeframe structure break after HTF retrace."""

    metadata = PluginMetadata(
        "v2.ltf_structure_confirmation",
        "1",
        DecisionStage.EVIDENCE,
        "LTF confirmed structure break evidence",
        status="parity-verified",
        inputs=("direction", "ltf_swings"),
        outputs=("evidence",),
        requirements=("v2.htf_ob_retrace",),
        config_fields=("ltf_n", "ob_range_type"),
        required_config_fields=("ltf_n", "ob_range_type"),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        htf_evidence = upstream_results[-1].facts["evidence"]
        if not htf_evidence:
            return PluginResult(
                plugin_id=self.metadata.plugin_id,
                stage=self.metadata.stage,
                status="rejected",
                reason_codes=("V2_LTF_STRUCTURE_NONE",),
                facts={"evidence": {}},
                available_at=context.signal_time,
                time_safe=True,
                profile=self.metadata.profile,
                requirements=self.metadata.requirements,
            )
        market_context = next(
            result for result in upstream_results if result.stage is DecisionStage.MARKET_CONTEXT
        )
        latest_ltf_open = pd.Timestamp(market_context.facts["latest_ltf_open"])
        ltf = context.market["ltf_ohlcv"].copy()
        ltf.index = V2ClosedBarContextPlugin._utc_index(ltf)
        ltf = ltf.loc[:latest_ltf_open]
        swing_highs, swing_lows = NFEDoubleLevelStrategy()._find_recent_swings_from_slice(
            ltf,
            n=int(config["ltf_n"]),
            ob_range_type=str(config["ob_range_type"]),
        )
        close = float(context.market["signal_bar"]["close"])
        evidence = {}
        if (
            "LONG" in htf_evidence
            and swing_highs
            and swing_lows
            and close > swing_highs[-1]["high"]
        ):
            latest_high = swing_highs[-1]
            latest_low = swing_lows[-1]
            evidence["LONG"] = {
                "break_level": float(latest_high["high"]),
                "close": close,
                "entry_ob_high": float(latest_low["ob_high"]),
                "entry_ob_low": float(latest_low["ob_low"]),
            }
        if (
            "SHORT" in htf_evidence
            and swing_highs
            and swing_lows
            and close < swing_lows[-1]["low"]
        ):
            latest_high = swing_highs[-1]
            latest_low = swing_lows[-1]
            evidence["SHORT"] = {
                "break_level": float(latest_low["low"]),
                "close": close,
                "entry_ob_high": float(latest_high["ob_high"]),
                "entry_ob_low": float(latest_high["ob_low"]),
            }
        evidence_direction = next(iter(evidence), "NONE")
        reason = (
            f"V2_LTF_STRUCTURE_{evidence_direction}_CONFIRMED"
            if evidence
            else "V2_LTF_STRUCTURE_NONE"
        )
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if evidence else "rejected",
            reason_codes=(reason,),
            facts={"evidence": evidence},
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2RRCostRiskGatePlugin:
    """Apply the legacy V2 fee-adjusted reward-risk gate."""

    metadata = PluginMetadata(
        "v2.rr_cost_risk_gate",
        "1",
        DecisionStage.RISK,
        "reward-risk, cost, sizing and leverage gate",
        status="parity-verified",
        inputs=("target", "evidence", "cost_config", "atr"),
        outputs=("risk_decision",),
        requirements=("v2.ltf_structure_confirmation",),
        config_fields=(
            "maker_fee",
            "taker_fee",
            "min_rr",
            "use_dynamic_sl",
            "sl_padding",
            "sl_padding_atr_mult",
            "limit_order_slippage",
            "min_net_profit_r",
            "tp1_close_pct",
            "risk_pct",
            "position_sizing_mode",
            "fixed_margin_usd",
            "leverage",
            "max_vol_pct",
            "max_short_rr",
            "max_short_stop_atr",
        ),
        required_config_fields=(
            "maker_fee",
            "taker_fee",
            "min_rr",
            "use_dynamic_sl",
            "sl_padding",
            "sl_padding_atr_mult",
            "limit_order_slippage",
            "min_net_profit_r",
            "tp1_close_pct",
            "risk_pct",
            "position_sizing_mode",
            "fixed_margin_usd",
            "leverage",
            "max_vol_pct",
            "max_short_rr",
            "max_short_stop_atr",
        ),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        targets = next(
            result.facts["targets"]
            for result in upstream_results
            if result.stage is DecisionStage.TARGET
        )
        evidence = {}
        for result in reversed(upstream_results):
            stage_evidence = result.facts.get("evidence", {})
            if result.stage is DecisionStage.EVIDENCE and any(
                "entry_ob_high" in side_evidence
                for side_evidence in stage_evidence.values()
            ):
                evidence = stage_evidence
                break
        bar = context.market["signal_bar"]
        close = float(bar["close"])
        execution_close = float(bar.get("execution_close", close))
        execution_ratio = execution_close / close if close > 0 else 1.0
        atr = float(context.market["atr"])
        price_scale = float(context.market.get("price_scale", 1.0))
        padding = (
            atr * float(config["sl_padding_atr_mult"])
            if bool(config["use_dynamic_sl"]) and atr > 0
            else float(config["sl_padding"]) * price_scale
        )
        maker_fee = float(config["maker_fee"])
        taker_fee = float(config["taker_fee"])
        min_rr = float(config["min_rr"])
        decisions = {}
        rejections = {}
        for side, side_evidence in evidence.items():
            if side not in targets:
                continue
            if side == "LONG":
                entry_price = float(side_evidence["entry_ob_high"])
                sl = float(side_evidence["entry_ob_low"]) - padding
            else:
                entry_price = float(side_evidence["entry_ob_low"])
                sl = float(side_evidence["entry_ob_high"]) + padding
            tp1 = float(targets[side]["target"])
            entry_price *= execution_ratio
            sl *= execution_ratio
            tp1 *= execution_ratio
            fee_drag = entry_price * maker_fee + sl * taker_fee
            stop_distance = (
                entry_price - sl if side == "LONG" else sl - entry_price
            )
            net_sl_distance = stop_distance + fee_drag
            if net_sl_distance <= 0:
                continue
            reward = tp1 - entry_price if side == "LONG" else entry_price - tp1
            reward_risk = reward / net_sl_distance
            if reward_risk < min_rr:
                continue

            limit_price = entry_price
            limit_slippage = float(config["limit_order_slippage"]) * price_scale
            effective_entry = (
                entry_price + limit_slippage
                if side == "LONG"
                else entry_price - limit_slippage
            )
            effective_stop_distance = (
                effective_entry - sl if side == "LONG" else sl - effective_entry
            )
            effective_net_sl_distance = effective_stop_distance + (
                effective_entry * maker_fee + sl * taker_fee
            )
            if effective_net_sl_distance <= 0:
                continue
            tp2 = (9_999_999.0 if side == "LONG" else 0.01) * execution_ratio
            tp1_close_pct = float(config["tp1_close_pct"])
            if side == "LONG":
                rr_potential = (
                    (tp1 - effective_entry) * tp1_close_pct
                    + (tp2 - effective_entry) * (1.0 - tp1_close_pct)
                ) / effective_net_sl_distance
            else:
                rr_potential = (
                    (effective_entry - tp1) * tp1_close_pct
                    + (effective_entry - tp2) * (1.0 - tp1_close_pct)
                ) / effective_net_sl_distance
            if rr_potential < float(config["min_net_profit_r"]):
                rejections[side] = {
                    "reason": "RETRACE_FILLED_BUT_RR_FILTERED",
                    "entry_price": effective_entry,
                    "limit_price": limit_price,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "rr_potential": rr_potential,
                }
                continue

            balance = float(context.market["balance"])
            volume_cap = float(context.market["signal_volume"]) * float(config["max_vol_pct"])
            leverage_limit = max(float(config["leverage"]), 1.0)
            sizing_mode = str(config["position_sizing_mode"])
            if sizing_mode == "fixed_margin":
                target_notional = float(config["fixed_margin_usd"]) * leverage_limit
                raw_size = target_notional / effective_entry
            else:
                raw_size = balance * float(config["risk_pct"]) / effective_net_sl_distance
                target_notional = raw_size * effective_entry
            size = min(raw_size, volume_cap)
            size = min(size, max(0.0, balance * leverage_limit) / effective_entry)
            if size <= 0:
                rejections[side] = {
                    "reason": "INSUFFICIENT_MARGIN_FOR_LEVERAGE",
                    "entry_price": effective_entry,
                    "leverage": float(config["leverage"]),
                    "position_sizing_mode": sizing_mode,
                }
                continue
            actual_notional = size * effective_entry
            actual_risk = size * effective_net_sl_distance
            target_notional = min(target_notional, volume_cap * effective_entry)
            effective_leverage = (
                min(leverage_limit, max(1.0, actual_notional / balance))
                if balance > 0
                else 1.0
            )

            stop_atr = abs(sl - effective_entry) / atr if atr > 0 else None
            max_short_rr = config["max_short_rr"]
            max_short_stop_atr = config["max_short_stop_atr"]
            if side == "SHORT" and (
                (max_short_rr is not None and rr_potential > float(max_short_rr))
                or (
                    max_short_stop_atr is not None
                    and (stop_atr is None or stop_atr > float(max_short_stop_atr))
                )
            ):
                rejections[side] = {
                    "reason": "SHORT_QUALITY_FILTER",
                    "rr_potential": rr_potential,
                    "stop_atr": stop_atr,
                }
                continue
            decisions[side] = {
                "entry_price": effective_entry,
                "limit_price": limit_price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "fee_drag": fee_drag,
                "net_sl_distance": effective_net_sl_distance,
                "reward_risk": reward_risk,
                "rr_potential": rr_potential,
                "size": size,
                "actual_risk_usd": actual_risk,
                "target_notional_usd": target_notional,
                "actual_notional_usd": actual_notional,
                "leverage": effective_leverage,
                "position_sizing_mode": sizing_mode,
                "stop_atr": stop_atr,
                "entry_balance": balance,
                "tp1_close_pct": tp1_close_pct,
            }

        direction = "BOTH" if len(decisions) == 2 else next(iter(decisions), "NONE")
        reason = (
            f"V2_RR_COST_{direction}_ACCEPTED"
            if decisions
            else f"V2_{next(iter(rejections.values()))['reason']}"
            if rejections
            else "V2_RR_COST_REJECTED"
        )
        facts = {"risk_decisions": decisions}
        if rejections:
            facts["risk_rejections"] = rejections
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if decisions else "rejected",
            reason_codes=(reason,),
            facts=facts,
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2RetraceLimitExecutionPlugin:
    """Convert an accepted V2 risk decision into a standard limit-order intent."""

    metadata = PluginMetadata(
        "v2.retrace_limit_execution",
        "1",
        DecisionStage.EXECUTION,
        "retrace limit entry, stop, target and size intent",
        status="parity-verified",
        inputs=("risk_decision",),
        outputs=("execution_intent",),
        requirements=("v2.rr_cost_risk_gate",),
        config_fields=("expiry_bars",),
        required_config_fields=("expiry_bars",),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        risk_decisions = next(
            result.facts["risk_decisions"]
            for result in upstream_results
            if result.stage is DecisionStage.RISK
        )
        intents = {}
        for side, decision in risk_decisions.items():
            intents[side] = {
                "intent_type": "retrace_limit",
                "side": side,
                "created_at": context.signal_time.isoformat(),
                "expires_after_bars": int(config["expiry_bars"]),
                "entry_price": decision["entry_price"],
                "limit_price": decision["limit_price"],
                "stop_price": decision["sl"],
                "take_profit_1": decision["tp1"],
                "take_profit_2": decision["tp2"],
                "quantity": decision["size"],
                "entry_balance": decision["entry_balance"],
                "reward_risk": decision["rr_potential"],
                "actual_risk_usd": decision["actual_risk_usd"],
                "take_profit_1_close_pct": decision["tp1_close_pct"],
                "position_sizing_mode": decision["position_sizing_mode"],
                "target_notional_usd": decision["target_notional_usd"],
                "actual_notional_usd": decision["actual_notional_usd"],
                "leverage": decision["leverage"],
                "entry_mode": f"NFE_DL_{side}",
                "live_take_profit_2": None,
            }
        direction = "BOTH" if len(intents) == 2 else next(iter(intents), "NONE")
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if intents else "rejected",
            reason_codes=((
                f"V2_RETRACE_LIMIT_{direction}_INTENT"
                if intents
                else "V2_RETRACE_LIMIT_NO_INTENT"
            ),),
            facts={"execution_intents": intents},
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


class V2ATRStructuralManagementPlugin:
    """Emit the legacy V2 ATR structural trailing-stop decision as an intent."""

    metadata = PluginMetadata(
        "v2.atr_structural_management",
        "1",
        DecisionStage.MANAGEMENT,
        "ATR structural trailing-stop management intent",
        status="parity-verified",
        inputs=("active_position", "ltf_swings", "atr"),
        outputs=("management_intent",),
        config_fields=(
            "use_trailing_stop",
            "use_dynamic_sl",
            "sl_padding",
            "sl_padding_atr_mult",
            "ltf_n",
            "ob_range_type",
            "enable_be",
            "be_trigger_ratio",
            "max_holding_bars",
        ),
        required_config_fields=(
            "use_trailing_stop",
            "use_dynamic_sl",
            "sl_padding",
            "sl_padding_atr_mult",
            "ltf_n",
            "ob_range_type",
            "enable_be",
            "be_trigger_ratio",
            "max_holding_bars",
        ),
    )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        position = context.market.get("active_position")
        intents = {}
        if bool(config["use_trailing_stop"]) and position is not None:
            ltf = context.market["ltf_ohlcv"].copy()
            ltf.index = V2ClosedBarContextPlugin._utc_index(ltf)
            ltf = ltf.loc[:context.signal_time]
            if len(ltf) >= 50:
                atr = float(ltf.iloc[-2].get("ATR_14", 0.0))
                price_scale = float(context.market.get("price_scale", 1.0))
                padding = (
                    atr * float(config["sl_padding_atr_mult"])
                    if bool(config["use_dynamic_sl"]) and atr > 0
                    else float(config["sl_padding"]) * price_scale
                )
                swing_highs, swing_lows = NFEDoubleLevelStrategy()._find_recent_swings_from_slice(
                    ltf,
                    n=int(config["ltf_n"]),
                    ob_range_type=str(config["ob_range_type"]),
                )
                side = position["type"]
                current_sl = float(position["sl"])
                new_sl = None
                if side == "LONG" and swing_lows:
                    candidate = float(swing_lows[-1]["low"]) - padding
                    new_sl = candidate if candidate > current_sl else None
                elif side == "SHORT" and swing_highs:
                    candidate = float(swing_highs[-1]["high"]) + padding
                    new_sl = candidate if candidate < current_sl else None
                if new_sl is not None:
                    intents[side] = {
                        "intent_type": "move_stop",
                        "side": side,
                        "created_at": context.signal_time.isoformat(),
                        "stop_price": new_sl,
                        "reason": "ATR_STRUCTURAL_TRAILING",
                    }

        policy = None
        required_policy_fields = (
            "type",
            "entry_price",
            "tp1",
            "tp2",
            "tp1_close_pct",
        )
        if position is not None and all(field in position for field in required_policy_fields):
            side = position["type"]
            entry_price = float(position["entry_price"])
            tp1 = float(position["tp1"])
            be_trigger_ratio = float(config["be_trigger_ratio"])
            be_trigger = (
                entry_price + (tp1 - entry_price) * be_trigger_ratio
                if side == "LONG"
                else entry_price - (entry_price - tp1) * be_trigger_ratio
            )
            max_holding = int(config["max_holding_bars"])
            if bool(position.get("be_active", False)):
                max_holding *= 3
            liquidation_price = position.get("liquidation_price")
            policy = {
                "side": side,
                "event_order": [
                    "liquidation",
                    "stop_loss",
                    "take_profit_1",
                    "take_profit_2",
                    "break_even_after_bar",
                    "time_stop",
                ],
                "take_profit_1": {
                    "price": tp1,
                    "close_pct": float(position["tp1_close_pct"]),
                    "already_hit": bool(position.get("tp1_hit", False)),
                },
                "take_profit_2": {"price": float(position["tp2"])},
                "break_even": {
                    "enabled": bool(config["enable_be"]),
                    "trigger_price": be_trigger,
                    "stop_price": entry_price,
                    "active": bool(position.get("be_active", False)),
                },
                "time_stop": {"max_holding_bars": max_holding},
                "liquidation": {
                    "enabled": (
                        float(position.get("leverage", 1.0)) > 1.0
                        and liquidation_price is not None
                    ),
                    "price": liquidation_price,
                },
            }

        direction = next(iter(intents), position.get("type", "NONE") if position else "NONE")
        reason = (
            f"V2_ATR_STRUCTURAL_{direction}_STOP_MOVE"
            if intents
            else f"V2_MANAGEMENT_{direction}_POLICY"
            if policy is not None
            else "V2_ATR_STRUCTURAL_NO_CHANGE"
        )
        facts = {"management_intents": intents}
        if policy is not None:
            facts["management_policy"] = policy
        return PluginResult(
            plugin_id=self.metadata.plugin_id,
            stage=self.metadata.stage,
            status="passed" if intents or policy is not None else "rejected",
            reason_codes=(reason,),
            facts=facts,
            available_at=context.signal_time,
            time_safe=True,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
        )


V2_IDENTIFIED_MODULES = ()

NFE_V2_COMPATIBLE_TEMPLATE = DecisionTemplate(
    template_id=NFE_V2_TEMPLATE_ID,
    version=NFE_V2_TEMPLATE_VERSION,
    stages=tuple(
        StageSelection(stage=stage, plugin_ids=(NFE_V2_PLUGIN_IDS[stage],))
        for stage in DecisionStage
    ),
)

V2_MODULAR_PLUGIN_IDS: Mapping[DecisionStage, tuple[str, ...]] = {
    DecisionStage.MARKET_CONTEXT: ("v2.closed_bar_context",),
    DecisionStage.DIRECTION: ("v2.htf_structure_direction",),
    DecisionStage.TARGET: ("v2.swing_liquidity_target",),
    DecisionStage.EVIDENCE: (
        "v2.htf_ob_retrace",
        "v2.ltf_structure_confirmation",
    ),
    DecisionStage.RISK: ("v2.rr_cost_risk_gate",),
    DecisionStage.EXECUTION: ("v2.retrace_limit_execution",),
    DecisionStage.MANAGEMENT: ("v2.atr_structural_management",),
}


def build_v2_modular_template(
    strategy: NFEV2Strategy,
    backtest_config: object,
    run_config: object,
) -> DecisionTemplate:
    """Build the complete modular V2 configuration snapshot."""

    configs = {
        "v2.closed_bar_context": {"htf_timeframe": strategy.htf},
        "v2.htf_structure_direction": {
            "htf_n": strategy.htf_n,
            "ob_range_type": strategy.ob_range_type,
        },
        "v2.swing_liquidity_target": {
            "htf_n": strategy.htf_n,
            "ob_range_type": strategy.ob_range_type,
        },
        "v2.htf_ob_retrace": {
            "htf_n": strategy.htf_n,
            "ob_range_type": strategy.ob_range_type,
        },
        "v2.ltf_structure_confirmation": {
            "ltf_n": strategy.ltf_n,
            "ob_range_type": strategy.ob_range_type,
        },
        "v2.rr_cost_risk_gate": {
            "maker_fee": backtest_config.maker_fee,
            "taker_fee": backtest_config.taker_fee,
            "min_rr": strategy.min_rr,
            "use_dynamic_sl": strategy.use_dynamic_sl,
            "sl_padding": strategy.sl_padding,
            "sl_padding_atr_mult": strategy.sl_padding_atr_mult,
            "limit_order_slippage": backtest_config.limit_order_slippage_usd,
            "min_net_profit_r": backtest_config.min_net_profit_r,
            "tp1_close_pct": run_config.tp1_close_pct,
            "risk_pct": backtest_config.risk_pct,
            "position_sizing_mode": backtest_config.position_sizing_mode,
            "fixed_margin_usd": backtest_config.fixed_margin_usd,
            "leverage": backtest_config.leverage,
            "max_vol_pct": backtest_config.max_vol_pct,
            "max_short_rr": strategy.max_short_rr,
            "max_short_stop_atr": strategy.max_short_stop_atr,
        },
        "v2.retrace_limit_execution": {"expiry_bars": 72},
        "v2.atr_structural_management": {
            "use_trailing_stop": strategy.use_trailing_stop,
            "use_dynamic_sl": strategy.use_dynamic_sl,
            "sl_padding": strategy.sl_padding,
            "sl_padding_atr_mult": strategy.sl_padding_atr_mult,
            "ltf_n": strategy.ltf_n,
            "ob_range_type": strategy.ob_range_type,
            "enable_be": run_config.enable_be,
            "be_trigger_ratio": run_config.be_trigger_ratio,
            "max_holding_bars": backtest_config.max_holding_bars,
        },
    }
    return DecisionTemplate(
        template_id=V2_MODULAR_TEMPLATE_ID,
        version=V2_MODULAR_TEMPLATE_VERSION,
        stages=tuple(
            StageSelection(
                stage=stage,
                plugin_ids=V2_MODULAR_PLUGIN_IDS[stage],
                plugin_config={
                    plugin_id: configs[plugin_id]
                    for plugin_id in V2_MODULAR_PLUGIN_IDS[stage]
                },
            )
            for stage in DecisionStage
        ),
    )


class _NFEV2Provider:
    """Executable compatibility provider; only execution invokes legacy V2."""

    def __init__(self, stage: DecisionStage) -> None:
        self.metadata = PluginMetadata(
            NFE_V2_PLUGIN_IDS[stage],
            NFE_V2_TEMPLATE_VERSION,
            stage,
            f"legacy V2 {stage.value} compatibility",
            status="transitional",
        )

    def evaluate(
        self,
        context: DecisionContext,
        upstream_results: Sequence[PluginResult],
        config: Mapping[str, object],
    ) -> PluginResult:
        reason = f"NFE_V2_{self.metadata.stage.value.upper()}_COMPATIBLE"
        facts: dict[str, object] = {"compatibility_mode": True}
        if self.metadata.stage is DecisionStage.EXECUTION:
            decision = context.market["legacy_scan"]()
            context.market["decision_sink"].append(decision)
            if decision.retrace_order is not None:
                side = decision.retrace_order.get("type", "UNKNOWN")
                reason = f"NFE_V2_RETRACE_ORDER_{side}"
                facts["outcome"] = "retrace_order"
            elif decision.breakout_order is not None:
                side = decision.breakout_order.get("type", "UNKNOWN")
                reason = f"NFE_V2_BREAKOUT_ORDER_{side}"
                facts["outcome"] = "breakout_order"
            elif decision.missed:
                reason = f"NFE_V2_MISSED_{decision.missed[0].get('reason', 'UNKNOWN')}"
                facts["outcome"] = "missed"
            else:
                reason = "NFE_V2_NO_DECISION"
                facts["outcome"] = "no_decision"
        return PluginResult.passed(
            self.metadata.plugin_id,
            self.metadata.stage,
            reason,
            available_at=context.signal_time,
            profile=self.metadata.profile,
            requirements=self.metadata.requirements,
            facts=facts,
        )


def nfe_v2_plugin_registry(
    extra_plugins: Mapping[str, object] | None = None,
) -> PluginRegistry:
    """Return V2 providers plus explicitly supplied composition modules."""

    plugins = {
        plugin_id: _NFEV2Provider(stage)
        for stage, plugin_id in NFE_V2_PLUGIN_IDS.items()
    }
    plugins.update(
        {metadata.plugin_id: metadata for metadata in V2_IDENTIFIED_MODULES}
    )
    plugins[V2ClosedBarContextPlugin.metadata.plugin_id] = V2ClosedBarContextPlugin()
    plugins[V2HTFStructureDirectionPlugin.metadata.plugin_id] = V2HTFStructureDirectionPlugin()
    plugins[V2SwingLiquidityTargetPlugin.metadata.plugin_id] = V2SwingLiquidityTargetPlugin()
    plugins[V2HTFOrderBlockRetracePlugin.metadata.plugin_id] = V2HTFOrderBlockRetracePlugin()
    plugins[V2LTFStructureConfirmationPlugin.metadata.plugin_id] = V2LTFStructureConfirmationPlugin()
    plugins[V2RRCostRiskGatePlugin.metadata.plugin_id] = V2RRCostRiskGatePlugin()
    plugins[V2RetraceLimitExecutionPlugin.metadata.plugin_id] = V2RetraceLimitExecutionPlugin()
    plugins[V2ATRStructuralManagementPlugin.metadata.plugin_id] = V2ATRStructuralManagementPlugin()
    for plugin_id, plugin in (extra_plugins or {}).items():
        if plugin_id in plugins:
            raise DecisionEngineConfigError(f"duplicate plugin id: {plugin_id}")
        plugins[plugin_id] = plugin
    return PluginRegistry(plugins)


def validate_nfe_v2_template(
    template: DecisionTemplate,
    registry: PluginRegistry,
) -> DecisionTemplate:
    """Reject incomplete or substituted mappings before an adapter is usable."""

    if not isinstance(template, DecisionTemplate):
        raise DecisionEngineConfigError("invalid NFE V2 template")
    if template.template_id != NFE_V2_TEMPLATE_ID:
        raise DecisionEngineConfigError(
            f"template id mismatch: {template.template_id}, expected {NFE_V2_TEMPLATE_ID}"
        )
    if template.version != NFE_V2_TEMPLATE_VERSION:
        raise DecisionEngineConfigError(
            f"template version mismatch: {template.version}, expected {NFE_V2_TEMPLATE_VERSION}"
        )

    selections = {selection.stage: selection for selection in template.stages}
    for stage in DecisionStage:
        selection = selections.get(stage)
        if selection is None:
            raise DecisionEngineConfigError(f"missing stage: {stage.value}")
        expected_plugin_ids = (NFE_V2_PLUGIN_IDS[stage],)
        if selection.plugin_ids != expected_plugin_ids:
            raise DecisionEngineConfigError(
                f"plugin mapping mismatch: {stage.value} must use {expected_plugin_ids[0]}"
            )

    if len(selections) != len(template.stages):
        # Let the core registry preserve its public duplicate-stage diagnostic.
        registry.resolve_template(template)
    if len(selections) != len(DecisionStage):
        unexpected = next(stage for stage in selections if stage not in DecisionStage)
        raise DecisionEngineConfigError(f"unexpected stage: {unexpected}")

    resolved_template = registry.resolve_template(template)
    for stage in DecisionStage:
        plugin_id = NFE_V2_PLUGIN_IDS[stage]
        metadata = registry.metadata_for(plugin_id)
        if metadata.version != NFE_V2_TEMPLATE_VERSION:
            raise DecisionEngineConfigError(
                f"plugin version mismatch: {plugin_id} is {metadata.version}, "
                f"expected {NFE_V2_TEMPLATE_VERSION}"
            )
    return resolved_template


class NFEV2DecisionTemplate:
    """Expose unchanged NFE V2 behaviour through the Decision Engine seam."""

    def __init__(
        self,
        legacy_strategy: BacktestStrategy,
        *,
        template: DecisionTemplate = NFE_V2_COMPATIBLE_TEMPLATE,
        registry: PluginRegistry | None = None,
    ) -> None:
        if not callable(getattr(legacy_strategy, "scan_entry_signal", None)):
            raise DecisionEngineConfigError("legacy strategy has no entry-signal hook")
        if not callable(getattr(legacy_strategy, "after_manage_position", None)):
            raise DecisionEngineConfigError("legacy strategy has no management hook")
        self.legacy_strategy = legacy_strategy
        self.registry = registry or nfe_v2_plugin_registry()
        self.template = validate_nfe_v2_template(template, self.registry)
        self.pipeline = DecisionPipeline(self.registry)
        self.last_pipeline_result = None

    def scan_entry_signal(
        self,
        backtester: "MultiTimeframeBacktester",
        prev: "pd.Series",
        curr: "pd.Series",
        curr_time: "pd.Timestamp",
        balance: float,
        cfg: "RunConfig",
    ) -> StrategyDecision:
        """Run all compatibility providers; execution preserves legacy outcome."""

        decision_sink: list[StrategyDecision] = []
        pipeline_time = pd.Timestamp(curr_time)
        if pipeline_time.tzinfo is None:
            pipeline_time = pipeline_time.tz_localize("UTC")
        self.last_pipeline_result = None
        self.last_pipeline_result = self.pipeline.evaluate(
            self.template,
            DecisionContext(
                signal_time=pipeline_time,
                market={
                    "legacy_scan": lambda: self.legacy_strategy.scan_entry_signal(
                        backtester, prev, curr, curr_time, balance, cfg
                    ),
                    "decision_sink": decision_sink,
                },
            ),
        )
        return decision_sink[0]

    def after_manage_position(
        self,
        active_position: dict,
        backtester: "MultiTimeframeBacktester",
        curr_time: "pd.Timestamp",
    ):
        """Delegate V2 structural trailing-stop updates unchanged."""

        return self.legacy_strategy.after_manage_position(
            active_position, backtester, curr_time
        )

    def __getattr__(self, name: str):
        """Preserve optional BacktestStrategy capabilities such as timeframe lookup."""

        return getattr(self.legacy_strategy, name)


class V2ModularDecisionTemplate:
    """Translate modular V2 intents into the frozen BacktestStrategy contract."""

    def __init__(
        self,
        strategy: NFEV2Strategy,
        *,
        registry: PluginRegistry | None = None,
        template: DecisionTemplate | None = None,
    ) -> None:
        self.strategy = strategy
        self.registry = registry or nfe_v2_plugin_registry()
        self.template = (
            self.registry.resolve_template(template) if template is not None else None
        )
        self.pipeline = DecisionPipeline(self.registry)
        self.last_pipeline_result = None
        self.last_run_config = None

    def signal_timeframe(self) -> str:
        return self.strategy.ltf

    def _market_context(
        self,
        backtester: "MultiTimeframeBacktester",
        prev: "pd.Series",
        curr: "pd.Series",
        balance: float,
        cfg: "RunConfig",
        active_position: dict | None,
    ) -> dict[str, object]:
        htf = (
            backtester.df_1h
            if self.strategy.htf == "1h"
            else backtester.df_4h
            if self.strategy.htf == "4h"
            else None
        )
        if htf is None:
            raise DecisionEngineConfigError(
                f"unsupported V2 HTF: {self.strategy.htf}"
            )
        if self.strategy.precomputed_htf_df is None:
            precomputed_source = htf.copy()
            precomputed_source.index = V2ClosedBarContextPlugin._utc_index(
                precomputed_source
            )
            self.strategy.precomputed_htf_df = self.strategy._precompute_htf_structures(
                precomputed_source
            )
        return {
            "htf_ohlcv": htf,
            "precomputed_htf_structure": self.strategy.precomputed_htf_df,
            "ltf_ohlcv": backtester.get_timeframe_df(self.strategy.ltf),
            "signal_bar": curr,
            "mode": cfg.mode,
            "bias_1d": prev.get("bias_1d", "NONE"),
            "bias_4h": prev.get("bias_4h", "NONE"),
            "allow_long_entries": cfg.allow_long_entries,
            "allow_short_entries": cfg.allow_short_entries,
            "atr": float(prev.get("ATR_14", 0.0)),
            "price_scale": float(getattr(backtester, "price_scale", 1.0)),
            "balance": balance,
            "signal_volume": float(prev.get("volume", 0.0)),
            "active_position": active_position,
        }

    @staticmethod
    def _pipeline_time(curr_time: "pd.Timestamp") -> "pd.Timestamp":
        value = pd.Timestamp(curr_time)
        return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")

    def scan_entry_signal(
        self,
        backtester: "MultiTimeframeBacktester",
        prev: "pd.Series",
        curr: "pd.Series",
        curr_time: "pd.Timestamp",
        balance: float,
        cfg: "RunConfig",
    ) -> StrategyDecision:
        self.last_run_config = cfg
        template = self.template or build_v2_modular_template(
            self.strategy, backtester.config, cfg
        )
        self.last_pipeline_result = self.pipeline.evaluate(
            template,
            DecisionContext(
                signal_time=self._pipeline_time(curr_time),
                market=self._market_context(
                    backtester, prev, curr, balance, cfg, None
                ),
            ),
        )
        execution = next(
            result
            for result in self.last_pipeline_result.plugin_results
            if result.plugin_id == "v2.retrace_limit_execution"
        )
        if execution.facts["execution_intents"]:
            intent = next(iter(execution.facts["execution_intents"].values()))
            size = float(intent["quantity"])
            return StrategyDecision(
                retrace_order={
                    "type": intent["side"],
                    "created_idx": None,
                    "entry_price": intent["entry_price"],
                    "limit_price": intent["limit_price"],
                    "sl": intent["stop_price"],
                    "tp1": intent["take_profit_1"],
                    "tp2": intent["take_profit_2"],
                    "size": size,
                    "entry_balance": intent["entry_balance"],
                    "rr_potential": intent["reward_risk"],
                    "actual_risk_usd": intent["actual_risk_usd"],
                    "tp1_hit": False,
                    "be_active": False,
                    "accumulated_funding": 0.0,
                    "tp1_close_pct": intent["take_profit_1_close_pct"],
                    "remaining_size": size,
                    "realized_pnl": 0.0,
                    "realized_fee": 0.0,
                    "tp1_realized": False,
                    "entry_mode": intent["entry_mode"],
                    "position_sizing_mode": intent["position_sizing_mode"],
                    "target_notional_usd": intent["target_notional_usd"],
                    "actual_notional_usd": intent["actual_notional_usd"],
                    "leverage": intent["leverage"],
                    "live_tp2": intent["live_take_profit_2"],
                }
            )
        risk = next(
            result
            for result in self.last_pipeline_result.plugin_results
            if result.plugin_id == "v2.rr_cost_risk_gate"
        )
        missed = [
            {"time": curr_time, "type": side, **rejection}
            for side, rejection in risk.facts.get("risk_rejections", {}).items()
        ]
        return StrategyDecision(missed=missed)

    def after_manage_position(
        self,
        active_position: dict,
        backtester: "MultiTimeframeBacktester",
        curr_time: "pd.Timestamp",
    ) -> None:
        if self.last_run_config is None:
            raise DecisionEngineConfigError(
                "V2 modular management requires an entry-scan config snapshot"
            )
        ltf = backtester.get_timeframe_df(self.strategy.ltf).loc[:curr_time]
        if len(ltf) < 2:
            return
        prev = ltf.iloc[-2]
        curr = ltf.iloc[-1]
        template = self.template or build_v2_modular_template(
            self.strategy, backtester.config, self.last_run_config
        )
        self.last_pipeline_result = self.pipeline.evaluate(
            template,
            DecisionContext(
                signal_time=self._pipeline_time(curr_time),
                market=self._market_context(
                    backtester,
                    prev,
                    curr,
                    float(active_position.get("entry_balance", 0.0)),
                    self.last_run_config,
                    active_position,
                ),
            ),
        )
        management = next(
            result
            for result in self.last_pipeline_result.plugin_results
            if result.plugin_id == "v2.atr_structural_management"
        )
        intent = management.facts["management_intents"].get(active_position["type"])
        if intent is not None:
            active_position["sl"] = intent["stop_price"]
