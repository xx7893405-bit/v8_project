from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from multi_timeframe_backtest import build_default_backtester, build_default_strategy


OUTPUT_PREFIX = "v8_long_short_diagnostic"
BAR_MINUTES = 15


def _mean_or_none(values: Iterable[float]) -> float | None:
    series = pd.Series(list(values), dtype="float64")
    if series.empty:
        return None
    value = series.mean()
    return None if pd.isna(value) else float(value)


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _context_from_trade(df: pd.DataFrame, trade: Dict[str, Any]) -> Dict[str, float | None]:
    entry_time = pd.Timestamp(trade["entry_time"])
    idx = df.index.searchsorted(entry_time, side="left") - 1
    if idx < 0 or idx >= len(df):
        return {"trend_strength_4h": None, "vwap_sd_expansion": None}
    row = df.iloc[idx]
    return {
        "trend_strength_4h": None if pd.isna(row["trend_strength_4h"]) else float(row["trend_strength_4h"]),
        "vwap_sd_expansion": None if pd.isna(row["VWAP_SD_EXPANSION"]) else float(row["VWAP_SD_EXPANSION"]),
    }


def _context_from_missed(df: pd.DataFrame, missed: Dict[str, Any]) -> Dict[str, float | None]:
    signal_time = missed.get("signal_time") or missed.get("time")
    if signal_time is None:
        return {"trend_strength_4h": None, "vwap_sd_expansion": None}
    ts = pd.Timestamp(signal_time)
    idx = df.index.searchsorted(ts, side="right") - 1
    if idx < 0 or idx >= len(df):
        return {"trend_strength_4h": None, "vwap_sd_expansion": None}
    row = df.iloc[idx]
    return {
        "trend_strength_4h": None if pd.isna(row["trend_strength_4h"]) else float(row["trend_strength_4h"]),
        "vwap_sd_expansion": None if pd.isna(row["VWAP_SD_EXPANSION"]) else float(row["VWAP_SD_EXPANSION"]),
    }


def _bars_held(trade: Dict[str, Any]) -> float:
    entry_time = pd.Timestamp(trade["entry_time"])
    exit_time = pd.Timestamp(trade["exit_time"])
    return (exit_time - entry_time).total_seconds() / 60.0 / BAR_MINUTES


def _summarize_side(side: str, trades: List[Dict[str, Any]], missed: List[Dict[str, Any]], df: pd.DataFrame) -> Dict[str, Any]:
    side_trades = [trade for trade in trades if trade["type"] == side]
    side_missed = [item for item in missed if item["type"] == side]
    trade_contexts = [_context_from_trade(df, trade) for trade in side_trades]
    missed_contexts = [_context_from_missed(df, item) for item in side_missed]

    result_counts = (
        pd.Series([trade["result"] for trade in side_trades], dtype="object").value_counts().to_dict()
        if side_trades
        else {}
    )
    miss_reason_counts = (
        pd.Series([item["reason"] for item in side_missed], dtype="object").value_counts().to_dict()
        if side_missed
        else {}
    )

    total_signals = len(side_trades) + len(side_missed)
    rr_filtered = miss_reason_counts.get("BREAKOUT_RR_FILTERED", 0)
    time_stops = [trade for trade in side_trades if trade["result"] == "TIME_STOP"]

    return {
        "side": side,
        "signals_total": total_signals,
        "executed_trades": len(side_trades),
        "missed_signals": len(side_missed),
        "execution_rate_pct": _round_or_none((len(side_trades) / total_signals) * 100 if total_signals else None, 2),
        "rr_filtered_pct": _round_or_none((rr_filtered / total_signals) * 100 if total_signals else None, 2),
        "win_rate_pct": _round_or_none(
            (sum(trade["result"] == "TAKE_PROFIT_ALL" for trade in side_trades) / len(side_trades)) * 100 if side_trades else None,
            2,
        ),
        "avg_trade_r": _round_or_none(_mean_or_none(trade["rr_realized"] for trade in side_trades)),
        "avg_rr_potential": _round_or_none(_mean_or_none(trade["rr_potential"] for trade in side_trades)),
        "avg_bars_held": _round_or_none(_mean_or_none(_bars_held(trade) for trade in side_trades), 2),
        "avg_pnl_usd": _round_or_none(_mean_or_none(trade["pnl"] for trade in side_trades), 2),
        "sum_pnl_usd": _round_or_none(sum(trade["pnl"] for trade in side_trades), 2),
        "avg_signal_trend_strength_4h": _round_or_none(_mean_or_none(ctx["trend_strength_4h"] for ctx in trade_contexts)),
        "avg_signal_vwap_sd_expansion": _round_or_none(_mean_or_none(ctx["vwap_sd_expansion"] for ctx in trade_contexts)),
        "avg_missed_trend_strength_4h": _round_or_none(_mean_or_none(ctx["trend_strength_4h"] for ctx in missed_contexts)),
        "avg_missed_vwap_sd_expansion": _round_or_none(_mean_or_none(ctx["vwap_sd_expansion"] for ctx in missed_contexts)),
        "avg_missed_rr": _round_or_none(_mean_or_none(item.get("rr") for item in side_missed if item.get("rr") is not None)),
        "time_stop_avg_pnl": _round_or_none(_mean_or_none(trade["pnl"] for trade in time_stops), 2),
        "result_counts": result_counts,
        "miss_reason_counts": miss_reason_counts,
    }


def main() -> None:
    backtester = build_default_backtester()
    strategy = build_default_strategy()
    trades, missed = backtester.run_strategy(strategy)

    diagnostics = [
        _summarize_side("LONG", trades, missed, backtester.df_15m_indicators),
        _summarize_side("SHORT", trades, missed, backtester.df_15m_indicators),
    ]

    output_json = Path(f"{OUTPUT_PREFIX}.json")
    output_csv = Path(f"{OUTPUT_PREFIX}.csv")
    output_json.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")

    rows = []
    for item in diagnostics:
        flat = {k: v for k, v in item.items() if k not in {"result_counts", "miss_reason_counts"}}
        flat["result_counts"] = json.dumps(item["result_counts"], ensure_ascii=False)
        flat["miss_reason_counts"] = json.dumps(item["miss_reason_counts"], ensure_ascii=False)
        rows.append(flat)
    pd.DataFrame(rows).to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("Long/Short Diagnostic Summary")
    for item in diagnostics:
        print("-" * 80)
        print(f"SIDE: {item['side']}")
        print(
            f"signals={item['signals_total']}, executed={item['executed_trades']}, missed={item['missed_signals']}, "
            f"exec_rate={item['execution_rate_pct']}%, rr_filtered={item['rr_filtered_pct']}%"
        )
        print(
            f"win={item['win_rate_pct']}%, avg_trade_r={item['avg_trade_r']}, avg_rr_potential={item['avg_rr_potential']}, "
            f"avg_bars_held={item['avg_bars_held']}, avg_pnl_usd={item['avg_pnl_usd']}, sum_pnl_usd={item['sum_pnl_usd']}"
        )
        print(
            f"signal_ctx trend={item['avg_signal_trend_strength_4h']}, expansion={item['avg_signal_vwap_sd_expansion']}; "
            f"missed_ctx trend={item['avg_missed_trend_strength_4h']}, expansion={item['avg_missed_vwap_sd_expansion']}, missed_rr={item['avg_missed_rr']}"
        )
        print(f"time_stop_avg_pnl={item['time_stop_avg_pnl']}")
        print(f"results={item['result_counts']}")
        print(f"miss_reasons={item['miss_reason_counts']}")

    print(f"\nSaved: {output_json.name}, {output_csv.name}")


if __name__ == "__main__":
    main()
