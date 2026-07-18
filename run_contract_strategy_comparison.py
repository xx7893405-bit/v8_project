from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import duckdb
import pandas as pd

from backtest_config import StrategyConfig
from bears_strategy import BearSStrategy
from ccxt_market_data import DuckDBMarketDataFeed
from multi_timeframe_backtest import MultiTimeframeBacktester
from nfe_v2_strategy import NFEV2Strategy


MARKET = {"exchange": "binance", "market_type": "swap", "symbol": "BTC/USDT:USDT"}
FULL_START = pd.Timestamp("2021-01-01")
MTD_START = pd.Timestamp("2026-07-01")
DEFAULT_DATABASE = Path("data/market_data.duckdb")
DEFAULT_OUTPUT_ROOT = Path("reports/contract_benchmark")
RISK_PCT = 0.05
MAX_LEVERAGE = 20.0


def benchmark_config(max_holding_bars: int) -> StrategyConfig:
    return StrategyConfig(
        initial_balance=10_000.0,
        risk_pct=RISK_PCT,
        position_sizing_mode="risk_based",
        leverage=MAX_LEVERAGE,
        slippage_usd=15.0,
        limit_order_slippage_usd=5.0,
        stop_loss_slippage_usd=10.0,
        maker_fee=0.0002,
        taker_fee=0.0005,
        funding_rate_8h=0.0001,
        max_holding_bars=max_holding_bars,
        min_net_profit_r=3.0,
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
        mode="NONE",
    )


def snapshot_identity(database: Path, market: dict = MARKET) -> dict:
    stat = database.stat()
    connection = duckdb.connect(str(database), read_only=True)
    try:
        count, first, last = connection.execute(
            """
            SELECT COUNT(*), MIN(open_time), MAX(open_time)
            FROM ohlcv_1m
            WHERE exchange = ? AND market_type = ? AND symbol = ?
            """,
            [market["exchange"], market["market_type"], market["symbol"]],
        ).fetchone()
    finally:
        connection.close()
    if not count:
        raise FileNotFoundError(f"No canonical perpetual candles in {database}")
    facts = {
        **market,
        "rows": int(count),
        "first_open_time": str(pd.Timestamp(first)),
        "last_open_time": str(pd.Timestamp(last)),
        "file_size": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
    }
    digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:16]
    return {**facts, "fingerprint": digest}


def assert_same_snapshot(expected: dict, actual: dict) -> None:
    if actual != expected:
        raise RuntimeError(
            f"DuckDB snapshot changed during benchmark: {expected['fingerprint']} -> {actual['fingerprint']}"
        )


def clip_period(
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    available_start: pd.Timestamp,
    available_end: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = max(pd.Timestamp(requested_start), pd.Timestamp(available_start))
    end = min(pd.Timestamp(requested_end), pd.Timestamp(available_end))
    if start > end:
        raise ValueError(f"Period has no available data: {start} > {end}")
    return start, end


def calculate_metrics(trades: list[dict], missed: int, initial_balance: float) -> dict:
    if not trades:
        return {
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": None,
            "final_balance": round(initial_balance, 2),
            "missed": missed,
        }
    frame = pd.DataFrame(trades).sort_values("exit_time")
    pnl = frame["pnl"].astype(float)
    equity = pd.Series([initial_balance, *(initial_balance + pnl.cumsum()).tolist()])
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_loss = -float(losses.sum())
    final_balance = float(equity.iloc[-1])
    return {
        "return_pct": round((final_balance / initial_balance - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(drawdown.min()), 4),
        "trades": len(frame),
        "win_rate_pct": round(float((pnl > 0).mean() * 100.0), 4),
        "profit_factor": round(float(wins.sum()) / gross_loss, 4) if gross_loss else None,
        "final_balance": round(final_balance, 2),
        "missed": missed,
    }


def grouped_metrics(trades: list[dict], column: str) -> list[dict]:
    if not trades:
        return []
    frame = pd.DataFrame(trades).copy()
    if column == "year":
        frame[column] = pd.to_datetime(frame["exit_time"]).dt.year
    rows = []
    for value, group in frame.groupby(column, sort=True):
        initial = float(group.sort_values("exit_time").iloc[0]["entry_balance"])
        label = int(value) if column == "year" else str(value)
        rows.append({column: label, **calculate_metrics(group.to_dict("records"), 0, initial)})
    return rows


def _json_value(value):
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def json_ready(records: list[dict]) -> list[dict]:
    return [{key: _json_value(value) for key, value in row.items()} for row in records]


def strategy_specs() -> list[dict]:
    # The A module is integrated independently; lazy import keeps helper tests usable meanwhile.
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
        {"name": "nfe_v2", "class": NFEV2Strategy, "kwargs": {**common, "ltf": "15m"}, "max_holding_bars": 96},
        {
            "name": "nfe_v2_a",
            "class": NFEV2AStrategy,
            "kwargs": {**common, "ltf": "5m", "entry_delay": "90m"},
            "max_holding_bars": 288,
        },
        {"name": "bears", "class": BearSStrategy, "kwargs": {}, "max_holding_bars": 24},
    ]


def run_period(
    spec: dict,
    period_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    database: Path,
    identity: dict,
    output_dir: Path,
) -> dict:
    cfg = benchmark_config(spec["max_holding_bars"])
    strategy = spec["class"](**spec["kwargs"])
    feed = DuckDBMarketDataFeed(database_path=str(database), **MARKET, start=str(FULL_START), end=str(end))
    started = monotonic()
    backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_feed=feed, strategy=strategy)
    session = backtester.run_session(start_at=start, **cfg.to_run_config().__dict__)
    assert_same_snapshot(identity, snapshot_identity(database))
    metrics = calculate_metrics(session.trades, len(session.missed_trades), cfg.initial_balance)
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
        "signal_timeframe": strategy.signal_timeframe(),
        "strategy_parameters": {key: _json_value(value) for key, value in vars(strategy).items() if not key.startswith("_") and key != "precomputed_htf_df"},
        "backtest_config": asdict(cfg),
        "runtime_seconds": round(monotonic() - started, 2),
        "metrics": metrics,
        "by_year": grouped_metrics(session.trades, "year"),
        "by_side": grouped_metrics(session.trades, "type"),
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
    markdown_rows = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *("| " + " | ".join(str(row[column]) for column in columns) + " |" for row in rows),
    ]
    (output_dir / "summary.md").write_text(
        "# Contract strategy benchmark\n\n" + "\n".join(markdown_rows) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare V2, A and BearS on one Binance perpetual DuckDB snapshot.")
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
        "results": results,
    }
    write_reports(results, payload, output_dir)
    print(pd.DataFrame([{"strategy": row["strategy"], "period": row["period"], **row["metrics"]} for row in results]).to_string(index=False))
    print(f"Reports: {output_dir}")


if __name__ == "__main__":
    main()
