from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable

import pandas as pd

from bears_strategy import BearSStrategy
from multi_timeframe_backtest import MultiTimeframeBacktester
from nfe_v2_strategy import NFEV2Strategy
from run_contract_strategy_comparison import benchmark_config, calculate_metrics, grouped_metrics


FULL_START = pd.Timestamp("2021-01-01")
DEFAULT_SPOT_CSV = Path("202101-202607_merged/btc_1m.csv")
DEFAULT_PERP_DATABASE = Path("data/btcusdt_perp_1m_202101_present.duckdb")
DEFAULT_OUTPUT_ROOT = Path("reports/spot_perp_benchmark")


def strategy_specs() -> list[dict]:
    from nfe_v2_a_strategy import NFEV2AStrategy

    common = {
        "htf": "1h",
        "htf_n": 5,
        "ltf_n": 3,
        "ob_range_type": "full",
        "min_rr": 3.0,
        "sl_padding": 20.0,
        "use_dynamic_sl": True,
        "sl_padding_atr_mult": 0.5,
        "use_trailing_stop": True,
    }
    return [
        {
            "name": "nfe_v2",
            "class": NFEV2Strategy,
            "kwargs": {**common, "ltf": "15m"},
            "signal_timeframe": "15m",
            "max_holding_bars": 96,
        },
        {
            "name": "nfe_v2_a",
            "class": NFEV2AStrategy,
            "kwargs": {**common, "ltf": "5m", "entry_delay": "90m"},
            "signal_timeframe": "5m",
            "max_holding_bars": 288,
        },
        {
            "name": "bears",
            "class": BearSStrategy,
            "kwargs": {},
            "signal_timeframe": "1h",
            "max_holding_bars": 24,
        },
    ]


def _finite(value: float) -> float | None:
    return round(float(value), 8) if pd.notna(value) else None


def calculate_market_metrics(spot_1m: pd.DataFrame, perp_1m: pd.DataFrame) -> dict:
    closes = pd.concat(
        [spot_1m["close"].rename("spot"), perp_1m["close"].rename("perp")], axis=1, join="inner"
    ).dropna()
    if closes.empty:
        raise ValueError("Spot and perpetual feeds have no aligned 1m closes")
    basis_bps = (closes["perp"] / closes["spot"] - 1.0) * 10_000.0
    returns = closes.pct_change().dropna()
    return {
        "aligned_1m_rows": int(len(closes)),
        "close_correlation": _finite(closes["spot"].corr(closes["perp"])),
        "return_correlation": _finite(returns["spot"].corr(returns["perp"])) if len(returns) else None,
        "median_basis_bps": _finite(basis_bps.median()),
        "p95_abs_basis_bps": _finite(basis_bps.abs().quantile(0.95)),
    }


def match_trade_entries(spot_trades: list[dict], perp_trades: list[dict], tolerance: str) -> dict:
    delta_limit = pd.Timedelta(tolerance)
    spot = [{**trade, "_time": pd.Timestamp(trade["entry_time"])} for trade in spot_trades]
    perp = [{**trade, "_time": pd.Timestamp(trade["entry_time"])} for trade in perp_trades]
    candidates: list[tuple[pd.Timedelta, int, int]] = []
    for spot_index, spot_trade in enumerate(spot):
        for perp_index, perp_trade in enumerate(perp):
            if spot_trade.get("type") != perp_trade.get("type"):
                continue
            delta = abs(spot_trade["_time"] - perp_trade["_time"])
            if delta <= delta_limit:
                candidates.append((delta, spot_index, perp_index))
    matched_spot: set[int] = set()
    matched_perp: set[int] = set()
    matches = []
    for delta, spot_index, perp_index in sorted(candidates, key=lambda row: (row[0], row[1], row[2])):
        if spot_index in matched_spot or perp_index in matched_perp:
            continue
        matched_spot.add(spot_index)
        matched_perp.add(perp_index)
        matches.append(
            {
                "side": spot[spot_index].get("type"),
                "spot_entry_time": str(spot[spot_index]["_time"]),
                "perp_entry_time": str(perp[perp_index]["_time"]),
                "entry_delta_seconds": float(delta.total_seconds()),
            }
        )
    matched = len(matches)
    return {
        "tolerance": tolerance,
        "matched_count": matched,
        "spot_match_rate_pct": round(matched / len(spot) * 100.0, 4) if spot else 0.0,
        "perp_match_rate_pct": round(matched / len(perp) * 100.0, 4) if perp else 0.0,
        "spot_only": len(spot) - matched,
        "perp_only": len(perp) - matched,
        "matches": matches,
    }


def run_one(spec: dict, market: str, feed, start: pd.Timestamp, end: pd.Timestamp, output_dir: Path) -> dict:
    config = benchmark_config(spec["max_holding_bars"])
    strategy = spec["class"](**spec["kwargs"])
    started = monotonic()
    backtester = MultiTimeframeBacktester(config=config.to_backtest_config(), data_feed=feed, strategy=strategy)
    session = backtester.run_session(start_at=start, **config.to_run_config().__dict__)
    metrics = calculate_metrics(session.trades, len(session.missed_trades), config.initial_balance)
    if abs(metrics["final_balance"] - session.balance) > 0.011:
        raise RuntimeError(f"PnL ledger mismatch for {spec['name']} {market}")
    trade_file = output_dir / f"{spec['name']}_{market}_trades.json"
    trade_file.write_text(
        json.dumps(_json_ready(session.trades), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    return {
        "strategy": spec["name"],
        "market": market,
        "start": str(start),
        "end": str(end),
        "signal_timeframe": spec["signal_timeframe"],
        "strategy_parameters": _json_ready({key: value for key, value in vars(strategy).items() if not key.startswith("_") and key != "precomputed_htf_df"}),
        "backtest_config": asdict(config),
        "runtime_seconds": round(monotonic() - started, 2),
        "metrics": metrics,
        "by_year": grouped_metrics(session.trades, "year"),
        "by_side": grouped_metrics(session.trades, "type"),
        "trades_file": trade_file.name,
        "trades": session.trades,
    }


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (pd.Timestamp, pd.Timedelta, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def build_comparison(
    spot_feed,
    perp_feed,
    audit: dict,
    output_dir: Path,
    runner: Callable = run_one,
) -> tuple[list[dict], dict, list[dict]]:
    start = max(FULL_START, pd.Timestamp(audit["common_first"]))
    end = pd.Timestamp(audit["common_last"])
    if start > end:
        raise ValueError(f"Common period has no data: {start} > {end}")
    market_metrics = calculate_market_metrics(spot_feed.load_timeframe("1m"), perp_feed.load_timeframe("1m"))
    if market_metrics["aligned_1m_rows"] != int(audit["common_rows"]):
        raise RuntimeError(
            f"Aligned feed changed after audit: {audit['common_rows']} -> {market_metrics['aligned_1m_rows']} rows"
        )
    results = []
    for spec in strategy_specs():
        results.append(runner(spec, "spot", spot_feed, start, end, output_dir))
        results.append(runner(spec, "perp", perp_feed, start, end, output_dir))
    overlaps = []
    for spec in strategy_specs():
        selected = {(item["strategy"], item["market"]): item for item in results}
        overlap = match_trade_entries(
            selected[(spec["name"], "spot")]["trades"],
            selected[(spec["name"], "perp")]["trades"],
            spec["signal_timeframe"],
        )
        overlaps.append({"strategy": spec["name"], **overlap})
    return results, market_metrics, overlaps


def write_reports(results: list[dict], payload: dict, output_dir: Path) -> None:
    rows = [{"strategy": item["strategy"], "market": item["market"], **item["metrics"]} for item in results]
    pd.DataFrame(rows).to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    year_rows = [
        {"strategy": item["strategy"], "market": item["market"], **group}
        for item in results
        for group in item.get("by_year", [])
    ]
    side_rows = [
        {"strategy": item["strategy"], "market": item["market"], **group}
        for item in results
        for group in item.get("by_side", [])
    ]
    pd.DataFrame(year_rows).to_csv(output_dir / "by_year.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(side_rows).to_csv(output_dir / "by_side.csv", index=False, encoding="utf-8-sig")
    overlap_rows = [{key: value for key, value in row.items() if key != "matches"} for row in payload["trade_overlap"]]
    pd.DataFrame(overlap_rows).to_csv(output_dir / "trade_overlap.csv", index=False, encoding="utf-8-sig")
    serializable = _json_ready(payload)
    (output_dir / "summary.json").write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    def markdown_table(table_rows: list[dict]) -> str:
        if not table_rows:
            return "No rows."
        columns = list(table_rows[0])
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *("| " + " | ".join(str(row[column]) for column in columns) + " |" for row in table_rows),
        ]
        return "\n".join(lines)
    market_lines = [f"- {key}: {value}" for key, value in payload["market_metrics"].items()]
    (output_dir / "summary.md").write_text(
        "# Spot vs perpetual strategy benchmark\n\n"
        + markdown_table(rows)
        + "\n\n## Market metrics\n\n"
        + "\n".join(market_lines)
        + "\n\n## Trade overlap\n\n"
        + markdown_table(overlap_rows)
        + "\n\n## By year\n\n"
        + markdown_table(year_rows)
        + "\n\n## By side\n\n"
        + markdown_table(side_rows)
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare V2, V2A and BearS on aligned spot/perpetual candles.")
    parser.add_argument("--spot-csv", type=Path, default=DEFAULT_SPOT_CSV)
    parser.add_argument("--perp-database", type=Path, default=DEFAULT_PERP_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    return parser.parse_args()


def main() -> None:
    from paired_market_data import load_aligned_market_feeds

    args = parse_args()
    spot_feed, perp_feed, audit = load_aligned_market_feeds(args.spot_csv, args.perp_database)
    fingerprint = audit["common_fingerprint"]
    output_dir = args.output_root / f"{args.run_id}_{fingerprint}"
    output_dir.mkdir(parents=True, exist_ok=False)
    results, market_metrics, overlaps = build_comparison(spot_feed, perp_feed, audit, output_dir)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"spot_csv": str(args.spot_csv.resolve()), "perp_database": str(args.perp_database.resolve())},
        "snapshot": audit,
        "period": {"start": results[0]["start"], "end": results[0]["end"]},
        "market_metrics": market_metrics,
        "trade_overlap": overlaps,
        "results": [{key: value for key, value in item.items() if key != "trades"} for item in results],
    }
    write_reports(results, payload, output_dir)
    print(pd.DataFrame([{"strategy": row["strategy"], "market": row["market"], **row["metrics"]} for row in results]).to_string(index=False))
    print(f"Reports: {output_dir}")


if __name__ == "__main__":
    main()
