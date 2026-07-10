from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from multi_timeframe_backtest import build_default_backtester, build_default_strategy


OUTPUT_PREFIX = "v8_post_entry_path_diagnostic"
CHECKPOINT_BARS = [1, 4, 8, 12]


def _favorable_move(side: str, entry_price: float, high_price: float, low_price: float) -> float:
    if side == "LONG":
        return high_price - entry_price
    return entry_price - low_price


def _adverse_move(side: str, entry_price: float, high_price: float, low_price: float) -> float:
    if side == "LONG":
        return entry_price - low_price
    return high_price - entry_price


def _path_metrics(df: pd.DataFrame, trade: Dict[str, Any], bars: int) -> Dict[str, float | None]:
    entry_time = pd.Timestamp(trade["entry_time"])
    pos = df.index.get_indexer([entry_time])[0]
    if pos < 0:
        return {"mfe": None, "mae": None, "close_move": None}

    window = df.iloc[pos : pos + bars]
    if window.empty:
        return {"mfe": None, "mae": None, "close_move": None}

    entry_price = float(trade["entry_price"])
    side = trade["type"]
    max_high = float(window["high"].max())
    min_low = float(window["low"].min())
    last_close = float(window.iloc[-1]["close"])

    mfe = _favorable_move(side, entry_price, max_high, min_low)
    mae = _adverse_move(side, entry_price, max_high, min_low)
    close_move = (last_close - entry_price) if side == "LONG" else (entry_price - last_close)

    risk_unit = abs(entry_price - float(trade["sl"]))
    if risk_unit <= 0:
        return {"mfe": mfe, "mae": mae, "close_move": close_move}

    return {
        "mfe": mfe / risk_unit,
        "mae": mae / risk_unit,
        "close_move": close_move / risk_unit,
    }


def _mean(series: List[float | None]) -> float | None:
    s = pd.Series(series, dtype="float64").dropna()
    if s.empty:
        return None
    return float(s.mean())


def _rate(values: List[bool]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values) * 100.0)


def _round(v: float | None, digits: int = 4) -> float | None:
    return None if v is None else round(v, digits)


def _summarize_side(df: pd.DataFrame, trades: List[Dict[str, Any]], side: str) -> Dict[str, Any]:
    side_trades = [trade for trade in trades if trade["type"] == side]
    checkpoints: Dict[str, Dict[str, float | None]] = {}

    for bars in CHECKPOINT_BARS:
        metrics = [_path_metrics(df, trade, bars) for trade in side_trades]
        mfe_values = [m["mfe"] for m in metrics]
        mae_values = [m["mae"] for m in metrics]
        close_values = [m["close_move"] for m in metrics]
        checkpoints[f"bar_{bars}"] = {
            "avg_mfe_r": _round(_mean(mfe_values)),
            "avg_mae_r": _round(_mean(mae_values)),
            "avg_close_move_r": _round(_mean(close_values)),
            "pct_close_positive": _round(_rate([(value or 0.0) > 0 for value in close_values if value is not None]), 2),
            "pct_mfe_ge_1r": _round(_rate([(value or 0.0) >= 1.0 for value in mfe_values if value is not None]), 2),
            "pct_mae_ge_1r": _round(_rate([(value or 0.0) >= 1.0 for value in mae_values if value is not None]), 2),
        }

    return {
        "side": side,
        "trade_count": len(side_trades),
        "result_counts": pd.Series([trade["result"] for trade in side_trades], dtype="object").value_counts().to_dict() if side_trades else {},
        "checkpoints": checkpoints,
    }


def main() -> None:
    backtester = build_default_backtester()
    strategy = build_default_strategy()
    trades, _ = backtester.run_strategy(strategy)
    df = backtester.df_15m_indicators

    diagnostics = [
        _summarize_side(df, trades, "LONG"),
        _summarize_side(df, trades, "SHORT"),
    ]

    json_path = Path(f"{OUTPUT_PREFIX}.json")
    json_path.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")

    flat_rows = []
    for item in diagnostics:
        row: Dict[str, Any] = {"side": item["side"], "trade_count": item["trade_count"], "result_counts": json.dumps(item["result_counts"], ensure_ascii=False)}
        for key, metrics in item["checkpoints"].items():
            for metric_name, value in metrics.items():
                row[f"{key}_{metric_name}"] = value
        flat_rows.append(row)
    csv_path = Path(f"{OUTPUT_PREFIX}.csv")
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")

    print("Post-Entry Path Diagnostic")
    for item in diagnostics:
        print("-" * 80)
        print(f"SIDE: {item['side']} trades={item['trade_count']} results={item['result_counts']}")
        for key, metrics in item["checkpoints"].items():
            print(
                f"{key}: avg_mfe_r={metrics['avg_mfe_r']}, avg_mae_r={metrics['avg_mae_r']}, "
                f"avg_close_move_r={metrics['avg_close_move_r']}, close_pos={metrics['pct_close_positive']}%, "
                f"mfe_ge_1r={metrics['pct_mfe_ge_1r']}%, mae_ge_1r={metrics['pct_mae_ge_1r']}%"
            )

    print(f"\nSaved: {json_path.name}, {csv_path.name}")


if __name__ == "__main__":
    main()
