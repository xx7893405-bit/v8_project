from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

import pandas as pd

from bears_strategy import BearSStrategy
from ccxt_market_data import DuckDBMarketDataFeed
from multi_timeframe_backtest import MultiTimeframeBacktester
from run_contract_strategy_comparison import (
    DEFAULT_DATABASE,
    FULL_START,
    MARKET,
    MTD_START,
    assert_same_snapshot,
    benchmark_config,
    clip_period,
    json_ready,
    snapshot_identity,
)


DEFAULT_OUTPUT_ROOT = Path("reports/entry_quality_benchmark")
FILTER_COUNTERS = (
    "stop_too_tight_count",
    "delay_target_invalidated_count",
    "fib_filtered_setups",
    "triple_filtered_setups",
)


def strategy_specs() -> list[dict[str, Any]]:
    """Return the seven frozen, single-variable comparisons."""
    from nfe_v2_a_strategy import NFEV2AStrategy

    v2a_common = {
        "htf": "1h",
        "htf_n": 5,
        "ltf_n": 3,
        "ob_range_type": "full",
        "min_rr": 3.0,
        "sl_padding": 20.0,
        "use_dynamic_sl": True,
        "sl_padding_atr_mult": 0.5,
        "use_trailing_stop": True,
        "ltf": "5m",
        "entry_delay": "90m",
    }
    return [
        {
            "name": "v2a_baseline",
            "class": NFEV2AStrategy,
            "kwargs": dict(v2a_common),
            "max_holding_bars": 288,
        },
        {
            "name": "v2a_min_stop_0_10",
            "class": NFEV2AStrategy,
            "kwargs": {**v2a_common, "min_stop_pct": 0.001},
            "max_holding_bars": 288,
        },
        {
            "name": "v2a_delay_target_revalidate",
            "class": NFEV2AStrategy,
            "kwargs": {**v2a_common, "invalidate_target_during_delay": True},
            "max_holding_bars": 288,
        },
        {"name": "bears_baseline", "class": BearSStrategy, "kwargs": {}, "max_holding_bars": 24},
        {
            "name": "bears_fib_05",
            "class": BearSStrategy,
            "kwargs": {"allowed_fib_ratios": (0.5,)},
            "max_holding_bars": 24,
        },
        {
            "name": "bears_triple",
            "class": BearSStrategy,
            "kwargs": {"require_triple": True},
            "max_holding_bars": 24,
        },
        {
            "name": "bears_fib_05_triple_diag",
            "class": BearSStrategy,
            "kwargs": {"allowed_fib_ratios": (0.5,), "require_triple": True},
            "max_holding_bars": 24,
        },
    ]


def calculate_entry_quality_metrics(
    trades: list[dict],
    missed: int,
    initial_balance: float,
    signal_timeframe: str,
) -> dict[str, Any]:
    """Calculate performance and entry-quality metrics from the trade ledger."""
    empty = {
        "return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trades": 0,
        "win_rate_pct": 0.0,
        "profit_factor": None,
        "final_balance": round(initial_balance, 2),
        "missed": missed,
        "avg_rr_realized": None,
        "breakeven_win_rate_pct": None,
        "quick_exit_count": 0,
        "quick_exit_rate_pct": 0.0,
        "top_win_share_pct": None,
    }
    if not trades:
        return empty

    frame = pd.DataFrame(trades).sort_values("exit_time").copy()
    pnl = frame["pnl"].astype(float)
    rr = frame["rr_realized"].astype(float)
    equity = pd.Series([initial_balance, *(initial_balance + pnl.cumsum()).tolist()])
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    positive_rr = rr[rr > 0]
    negative_rr = rr[rr < 0]
    gross_loss = -float(losses.sum())
    avg_win_r = float(positive_rr.mean()) if not positive_rr.empty else None
    avg_loss_r = abs(float(negative_rr.mean())) if not negative_rr.empty else None
    breakeven = (
        avg_loss_r / (avg_win_r + avg_loss_r) * 100.0
        if avg_win_r is not None and avg_loss_r is not None and avg_win_r + avg_loss_r > 0
        else None
    )
    duration = pd.to_datetime(frame["exit_time"]) - pd.to_datetime(frame["entry_time"])
    quick_exit_count = int((duration <= pd.Timedelta(signal_timeframe)).sum())
    final_balance = float(equity.iloc[-1])
    return {
        "return_pct": round((final_balance / initial_balance - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(drawdown.min()), 4),
        "trades": len(frame),
        "win_rate_pct": round(float((pnl > 0).mean() * 100.0), 4),
        "profit_factor": round(float(wins.sum()) / gross_loss, 4) if gross_loss else None,
        "final_balance": round(final_balance, 2),
        "missed": missed,
        "avg_rr_realized": round(float(rr.mean()), 4),
        "breakeven_win_rate_pct": round(breakeven, 4) if breakeven is not None else None,
        "quick_exit_count": quick_exit_count,
        "quick_exit_rate_pct": round(quick_exit_count / len(frame) * 100.0, 4),
        "top_win_share_pct": round(float(wins.max() / wins.sum() * 100.0), 4) if not wins.empty else None,
    }


def filter_counts(strategy: object) -> dict[str, int]:
    return {name: int(getattr(strategy, name, 0)) for name in FILTER_COUNTERS}


def grouped_entry_quality_metrics(
    trades: list[dict], column: str, signal_timeframe: str
) -> list[dict[str, Any]]:
    if not trades:
        return []
    frame = pd.DataFrame(trades).copy()
    if column == "year":
        frame[column] = pd.to_datetime(frame["exit_time"]).dt.year
    rows = []
    for value, group in frame.groupby(column, sort=True):
        ordered = group.sort_values("exit_time")
        initial_balance = float(ordered.iloc[0]["entry_balance"])
        label = int(value) if column == "year" else str(value)
        rows.append(
            {
                column: label,
                **calculate_entry_quality_metrics(
                    ordered.to_dict("records"),
                    missed=0,
                    initial_balance=initial_balance,
                    signal_timeframe=signal_timeframe,
                ),
            }
        )
    return rows


def _strategy_parameters(strategy: object) -> dict[str, Any]:
    result = {}
    for key, value in vars(strategy).items():
        if key.startswith("_") or key == "precomputed_htf_df":
            continue
        if isinstance(value, (pd.Timestamp, pd.Timedelta, Path)):
            value = str(value)
        elif isinstance(value, tuple):
            value = list(value)
        result[key] = value
    return result


def run_period(
    spec: dict[str, Any],
    period_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    database: Path,
    identity: dict,
    output_dir: Path,
) -> dict[str, Any]:
    cfg = benchmark_config(spec["max_holding_bars"])
    strategy = spec["class"](**spec["kwargs"])
    signal_timeframe = strategy.signal_timeframe()
    feed = DuckDBMarketDataFeed(database_path=str(database), **MARKET, start=str(FULL_START), end=str(end))
    started = monotonic()
    backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_feed=feed, strategy=strategy)
    session = backtester.run_session(start_at=start, **cfg.to_run_config().__dict__)
    assert_same_snapshot(identity, snapshot_identity(database))
    metrics = calculate_entry_quality_metrics(
        session.trades, len(session.missed_trades), cfg.initial_balance, signal_timeframe
    )
    if abs(metrics["final_balance"] - session.balance) > 0.011:
        raise RuntimeError(f"PnL ledger mismatch for {spec['name']} {period_name}")
    trade_file = output_dir / f"{spec['name']}_{period_name}_trades.json"
    trade_file.write_text(
        json.dumps(json_ready(session.trades), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    return {
        "strategy": spec["name"],
        "period": period_name,
        "start": str(start),
        "end": str(end),
        "signal_timeframe": signal_timeframe,
        "strategy_parameters": _strategy_parameters(strategy),
        "backtest_config": asdict(cfg),
        "runtime_seconds": round(monotonic() - started, 2),
        "metrics": {**metrics, **filter_counts(strategy)},
        "by_year": grouped_entry_quality_metrics(session.trades, "year", signal_timeframe),
        "by_side": grouped_entry_quality_metrics(session.trades, "type", signal_timeframe),
        "trades_file": trade_file.name,
    }


def write_reports(results: list[dict], payload: dict, output_dir: Path) -> None:
    rows = [{"strategy": item["strategy"], "period": item["period"], **item["metrics"]} for item in results]
    summary = pd.DataFrame(rows)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    columns = list(summary.columns)
    table = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *("| " + " | ".join(str(row.get(column)) for column in columns) + " |" for row in rows),
    ]
    (output_dir / "summary.md").write_text(
        "# V2A / BearS entry quality benchmark\n\n" + "\n".join(table) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run seven frozen V2A/BearS entry-quality comparisons.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()

    identity = snapshot_identity(args.database)
    available_start = pd.Timestamp(identity["first_open_time"])
    cutoff = pd.Timestamp(identity["last_open_time"])
    periods = {
        "full": clip_period(FULL_START, cutoff, available_start, cutoff),
        "mtd_2026_07": clip_period(MTD_START, cutoff, available_start, cutoff),
    }
    output_dir = args.output_root / f"{args.run_id}_{identity['fingerprint']}"
    output_dir.mkdir(parents=True, exist_ok=False)
    results = [
        run_period(spec, period, start, end, args.database, identity, output_dir)
        for spec in strategy_specs()
        for period, (start, end) in periods.items()
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(args.database.resolve()),
        "snapshot": identity,
        "periods": {name: {"start": str(bounds[0]), "end": str(bounds[1])} for name, bounds in periods.items()},
        "specifications": [
            {key: value for key, value in spec.items() if key != "class"} for spec in strategy_specs()
        ],
        "results": results,
    }
    write_reports(results, payload, output_dir)
    print(pd.DataFrame([{"strategy": row["strategy"], "period": row["period"], **row["metrics"]} for row in results]).to_string(index=False))
    print(f"Reports: {output_dir}")


if __name__ == "__main__":
    main()
