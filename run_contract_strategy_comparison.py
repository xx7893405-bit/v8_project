from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from secrets import token_hex
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import duckdb
import pandas as pd

from backtest_config import StrategyConfig
from bears_strategy import BearSStrategy
from ccxt_market_data import DuckDBMarketDataFeed, require_fidelity_data
from download_perpetual_history import verify_manifest
from multi_timeframe_backtest import MultiTimeframeBacktester
from nfe_v2_strategy import NFEV2Strategy
from run_artifacts import (
    METRICS_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    canonical_artifact_references,
    create_run_directory,
    render_review_markdown,
    render_summary_markdown,
    validate_run_artifact,
    validate_run_id,
)


MARKET = {"exchange": "binance", "market_type": "swap", "symbol": "BTC/USDT:USDT"}
FULL_START = pd.Timestamp("2021-01-01")
MTD_START = pd.Timestamp("2026-07-01")
DEFAULT_DATABASE = Path("data/btcusdt_perp_1m_202101_present.duckdb")
DEFAULT_DATA_MANIFEST = Path("data/btcusdt_perp_1m_202101_present.manifest.json")
DEFAULT_BASELINE = Path(
    "reports/contract_benchmark/20260718_btcusdt_perp_risk5_lev20_ea28b7ca3c90c46b/summary.json"
)
DEFAULT_OUTPUT_ROOT = Path("reports/contract_fidelity")
RISK_PCT = 0.05
MAX_LEVERAGE = 20.0
RESEARCH_WARNING = (
    "Research profile uses trade-price marks and fixed 0.0001/8h funding; "
    "it cannot be claimed as live-parity or fidelity evidence."
)
MDD_WARNING = "Candidate MDD uses mark-to-market session equity events; frozen baseline MDD was realized-only."
FIDELITY_UNSUPPORTED = (
    "fidelity profile is unsupported: strategy_engine does not consume historical mark-price and funding data"
)
BASELINE_CONFIG_KEYS = (
    "risk_pct",
    "leverage",
    "maker_fee",
    "taker_fee",
    "slippage_usd",
    "limit_order_slippage_usd",
    "stop_loss_slippage_usd",
    "funding_rate_8h",
)
SNAPSHOT_IDENTITY_KEYS = (
    "exchange",
    "market_type",
    "symbol",
    "rows",
    "first_open_time",
    "last_open_time",
    "file_size",
    "file_mtime_ns",
    "fingerprint",
)


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


def _utc_iso(value) -> str:
    timestamp = pd.Timestamp(value)
    timestamp = (
        timestamp.tz_localize("UTC")
        if timestamp.tzinfo is None
        else timestamp.tz_convert("UTC")
    )
    return timestamp.isoformat()


def _canonical_utc_timestamp(value, field: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {field}") from error
    if pd.isna(timestamp):
        raise ValueError(f"invalid {field}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def _normalize_equity_row(row: dict) -> dict:
    if "time" not in row:
        raise ValueError("equity row missing time")
    if "event_time" in row:
        raise ValueError("equity row has conflicting time fields")
    normalized = dict(row)
    normalized["event_time"] = _canonical_utc_timestamp(
        normalized.pop("time"), "equity time"
    )
    return normalized


def _normalize_trade_row(row: dict) -> dict:
    if "entry_time" not in row or "exit_time" not in row:
        raise ValueError("trade row missing lifecycle timestamp")
    if {"time", "event_time"} & row.keys():
        raise ValueError("trade row has conflicting timestamp fields")
    normalized = dict(row)
    normalized["entry_time"] = _canonical_utc_timestamp(
        normalized["entry_time"], "trade entry_time"
    )
    normalized["exit_time"] = _canonical_utc_timestamp(
        normalized["exit_time"], "trade exit_time"
    )
    if pd.Timestamp(normalized["exit_time"]) < pd.Timestamp(normalized["entry_time"]):
        raise ValueError("trade exit_time precedes entry_time")
    return normalized


def calculate_metrics(
    trades: list[dict], missed: int, initial_balance: float, equity_events: list[dict] | None = None
) -> dict:
    frame = pd.DataFrame(trades).sort_values("exit_time") if trades else pd.DataFrame()
    pnl = frame["pnl"].astype(float) if trades else pd.Series(dtype=float)
    final_balance = initial_balance + float(pnl.sum())
    if equity_events:
        equity = pd.Series([float(row["equity"]) for row in equity_events])
    else:
        equity = pd.Series([initial_balance, *(initial_balance + pnl.cumsum()).tolist()])
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_loss = -float(losses.sum())
    return {
        "return_pct": round((final_balance / initial_balance - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(drawdown.min()), 4),
        "trades": len(frame),
        "win_rate_pct": round(float((pnl > 0).mean() * 100.0), 4) if trades else 0.0,
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
    if isinstance(value, (pd.Timestamp, pd.Timedelta, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def json_ready(records: list[dict]) -> list[dict]:
    return [{key: _json_value(value) for key, value in row.items()} for row in records]


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
) -> tuple[dict, list[dict], list[dict], dict]:
    cfg = benchmark_config(spec["max_holding_bars"])
    strategy = spec["class"](**spec["kwargs"])
    feed = DuckDBMarketDataFeed(database_path=str(database), **MARKET, start=str(FULL_START), end=str(end))
    started = monotonic()
    backtester = MultiTimeframeBacktester(config=cfg.to_backtest_config(), data_feed=feed, strategy=strategy)
    session = backtester.run_session(start_at=start, **cfg.to_run_config().__dict__)
    assert_same_snapshot(identity, snapshot_identity(database))
    metrics = calculate_metrics(
        session.trades, len(session.missed_trades), cfg.initial_balance, session.equity_events
    )
    realized = [row for row in session.equity_events if row["mark_source"] == "realized_balance"]
    if (
        not realized
        or abs(float(realized[-1]["equity"]) - session.balance) > 0.01
        or abs(metrics["final_balance"] - session.balance) > 0.01
    ):
        raise RuntimeError(f"Ending equity mismatch for {spec['name']} {period_name}")
    trades = [
        _normalize_trade_row(
            {"strategy": spec["name"], "period": period_name, **row}
        )
        for row in json_ready(session.trades)
    ]
    equity = [
        _normalize_equity_row(
            {"strategy": spec["name"], "period": period_name, **row}
        )
        for row in json_ready(session.equity_events)
    ]
    result = {
        "strategy": spec["name"],
        "period": period_name,
        "start": str(start),
        "end": str(end),
        "signal_timeframe": strategy.signal_timeframe(),
        "strategy_parameters": {
            key: _json_value(value)
            for key, value in vars(strategy).items()
            if not key.startswith("_") and key != "precomputed_htf_df"
        },
        "backtest_config": asdict(cfg),
        "runtime_seconds": round(monotonic() - started, 2),
        "metrics": metrics,
        "by_year": grouped_metrics(session.trades, "year"),
        "by_side": grouped_metrics(session.trades, "type"),
    }
    diagnostic = {
        "strategy": spec["name"],
        "period": period_name,
        "trade_rows": len(trades),
        "equity_rows": len(equity),
        "last_realized_equity": float(realized[-1]["equity"]),
        "session_balance": float(session.balance),
        "reconciliation_error": abs(float(realized[-1]["equity"]) - session.balance),
    }
    return result, trades, equity, diagnostic


def git_identity() -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def write_parquet(records: list[dict], path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("artifact_rows", pd.DataFrame(records))
        connection.execute("COPY artifact_rows TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def validate_baseline(
    baseline_path: Path,
    candidate_snapshot: dict,
    candidate_periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> tuple[dict, dict]:
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    snapshot = baseline.get("snapshot")
    if not isinstance(snapshot, dict) or any(key not in snapshot for key in SNAPSHOT_IDENTITY_KEYS):
        raise RuntimeError("baseline identity is incomplete")
    mismatches = [
        f"snapshot.{key}"
        for key in SNAPSHOT_IDENTITY_KEYS
        if snapshot[key] != candidate_snapshot.get(key)
    ]
    expected_periods = {
        name: {"start": str(bounds[0]), "end": str(bounds[1])}
        for name, bounds in candidate_periods.items()
    }
    if baseline.get("periods") != expected_periods:
        mismatches.append("periods")

    expected_config = benchmark_config(96)
    expected_pairs = {(spec["name"], period) for spec in strategy_specs() for period in candidate_periods}
    rows = baseline.get("results")
    if not isinstance(rows, list) or {(row.get("strategy"), row.get("period")) for row in rows} != expected_pairs:
        mismatches.append("results")
        rows = []
    for row in rows:
        bounds = expected_periods[row["period"]]
        if row.get("start") != bounds["start"] or row.get("end") != bounds["end"]:
            mismatches.append(f"{row['strategy']}.{row['period']}.bounds")
        config = row.get("backtest_config")
        if not isinstance(config, dict):
            mismatches.append(f"{row['strategy']}.{row['period']}.config")
            continue
        for key in BASELINE_CONFIG_KEYS:
            if key not in config or config[key] != getattr(expected_config, key):
                mismatches.append(f"{row['strategy']}.{row['period']}.{key}")
    if mismatches:
        raise RuntimeError("baseline identity mismatch: " + ", ".join(sorted(set(mismatches))))
    baseline_run_id = baseline.get("run_id", baseline_path.parent.name)
    validate_run_id(baseline_run_id)
    identity = {
        "run_id": baseline_run_id,
        "content_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "snapshot_id": snapshot["fingerprint"],
    }
    if baseline.get("generated_at") is not None:
        identity["generated_at"] = baseline["generated_at"]
    return baseline, identity


def baseline_comparison(
    results: list[dict], baseline: dict, identity: dict
) -> tuple[dict, list[dict]]:
    baseline_rows = {(row["strategy"], row["period"]): row["metrics"] for row in baseline["results"]}
    metric_names = (
        "return_pct",
        "max_drawdown_pct",
        "trades",
        "win_rate_pct",
        "profit_factor",
        "final_balance",
    )
    comparisons = []
    for result in results:
        old = baseline_rows[(result["strategy"], result["period"])]
        new = result["metrics"]
        deltas = {
            key: None if old.get(key) is None or new.get(key) is None else round(new[key] - old[key], 4)
            for key in metric_names
        }
        comparisons.append(
            {
                "strategy": result["strategy"],
                "period": result["period"],
                "start": _utc_iso(result["start"]),
                "end": _utc_iso(result["end"]),
                "metrics": new,
                "baseline_deltas": deltas,
            }
        )
    return identity, comparisons


def write_reports(
    results: list[dict],
    all_trades: list[dict],
    all_equity: list[dict],
    diagnostics: list[dict],
    manifest: dict,
    baseline: dict,
    baseline_identity: dict,
    output_dir: Path,
) -> None:
    baseline_identity, comparisons = baseline_comparison(results, baseline, baseline_identity)
    warnings = ([RESEARCH_WARNING] if manifest["profile"] == "research" else []) + [MDD_WARNING]
    manifest["baseline"] = baseline_identity
    manifest["warnings"] = warnings[:5]
    summary = {
        "schema_version": RUN_SCHEMA_VERSION,
        "metrics_version": METRICS_SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "created_at": manifest["created_at"],
        "provenance": {
            key: manifest[key]
            for key in ("strategy", "data", "git", "period", "assumptions")
        },
        "verdict": "research_only" if warnings else "fidelity_candidate",
        "profile": manifest["profile"],
        "results": comparisons,
        "warnings": warnings[:5],
        "baseline": baseline_identity,
        "artifacts": canonical_artifact_references(),
    }
    manifest["artifacts"] = canonical_artifact_references()
    validate_run_artifact(manifest, summary)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    write_parquet(all_trades, output_dir / "trades.parquet")
    write_parquet(all_equity, output_dir / "equity.parquet")
    write_parquet(diagnostics, output_dir / "diagnostics.parquet")
    summary_markdown = render_summary_markdown(summary)
    (output_dir / "summary.md").write_text(summary_markdown, encoding="utf-8")
    (output_dir / "review.md").write_text(
        render_review_markdown(summary), encoding="utf-8"
    )
    (output_dir / "report.md").write_text(summary_markdown, encoding="utf-8")
    (output_dir / "run.log").write_text(
        "completed=true\n"
        f"profile={manifest['profile']}\n"
        f"sessions={len(results)}\n"
        f"trades={len(all_trades)}\n"
        f"equity_events={len(all_equity)}\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare V2, A and BearS on one Binance perpetual snapshot.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_DATA_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--profile", choices=("fidelity", "research"), default="fidelity")
    return parser.parse_args(argv)


@contextmanager
def _publication_reservation(output_root: Path, run_id: str):
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = output_root / run_id
    if output_dir.exists():
        raise FileExistsError(output_dir)

    reservation = output_root / f".{run_id}.reservation"
    try:
        reservation.mkdir()
    except FileExistsError as error:
        raise FileExistsError(output_dir) from error

    token = token_hex(16)
    owner = reservation / "owner"
    owner_written = False
    try:
        owner.write_text(token, encoding="utf-8")
        owner_written = True
        if output_dir.exists():
            raise FileExistsError(output_dir)
        yield output_dir
    finally:
        try:
            if owner_written and owner.read_text(encoding="utf-8") == token:
                owner.unlink()
                reservation.rmdir()
            elif not owner_written:
                owner.unlink(missing_ok=True)
                reservation.rmdir()
        except OSError:
            pass


def main() -> None:
    args = parse_args()
    validate_run_id(args.run_id)
    with _publication_reservation(args.output_root, args.run_id) as output_dir:
        _run(args, output_dir)


def _run(args: argparse.Namespace, output_dir: Path) -> None:

    verified = verify_manifest(args.database, args.manifest)
    identity = snapshot_identity(args.database)
    available_start = pd.Timestamp(identity["first_open_time"])
    cutoff = pd.Timestamp(identity["last_open_time"])
    periods = {
        "full": clip_period(FULL_START, cutoff, available_start, cutoff),
        "mtd_2026_07": clip_period(MTD_START, cutoff, available_start, cutoff),
    }
    fidelity_coverage = None
    if args.profile == "fidelity":
        require_fidelity_data(args.database, *periods["full"])
        raise RuntimeError(FIDELITY_UNSUPPORTED)
    if not args.baseline.is_file():
        raise FileNotFoundError(f"Baseline report does not exist: {args.baseline}")
    baseline, baseline_identity = validate_baseline(args.baseline, identity, periods)

    results, all_trades, all_equity, diagnostics = [], [], [], []
    specs = strategy_specs()
    for spec in specs:
        for period, (start, end) in periods.items():
            result, trades, equity, diagnostic = run_period(spec, period, start, end, args.database, identity)
            results.append(result)
            all_trades.extend(trades)
            all_equity.extend(equity)
            diagnostics.append(diagnostic)
    assert_same_snapshot(identity, snapshot_identity(args.database))
    git = git_identity()
    configuration = [
        {
            "name": spec["name"],
            "kwargs": {
                key: _json_value(value) for key, value in spec["kwargs"].items()
            },
            "backtest_config": asdict(benchmark_config(spec["max_holding_bars"])),
        }
        for spec in specs
    ]
    config_id = "sha256:" + hashlib.sha256(
        json.dumps(
            configuration, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    full_start, full_end = periods["full"]
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "metrics_version": METRICS_SCHEMA_VERSION,
        "experiment_id": "BENCH-005",
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": {
            "name": "contract_strategy_comparison",
            "config_id": config_id,
        },
        "data": {
            "snapshot_id": identity["fingerprint"],
            "content_sha256": verified["sha256"],
            "market_type": MARKET["market_type"],
            "symbol": MARKET["symbol"],
        },
        "git": {"revision": git["commit"]},
        "period": {"start": _utc_iso(full_start), "end": _utc_iso(full_end)},
        "assumptions": {
            "costs": {
                "maker_fee": 0.0002,
                "taker_fee": 0.0005,
                "funding_rate_8h": 0.0001,
                "slippage_usd": 15.0,
                "limit_order_slippage_usd": 5.0,
                "stop_loss_slippage_usd": 10.0,
            },
            "leverage": {"risk_pct": RISK_PCT, "max_leverage": MAX_LEVERAGE},
        },
        "artifacts": canonical_artifact_references(),
        "profile": args.profile,
        "random_seed": None,
        "git_dirty": git["dirty"],
        "fidelity_coverage": fidelity_coverage,
        "configuration": configuration,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        dir=args.output_root, prefix=f".{args.run_id}."
    ) as staging_root:
        staging_dir = create_run_directory(Path(staging_root) / args.run_id)
        write_reports(
            results,
            all_trades,
            all_equity,
            diagnostics,
            manifest,
            baseline,
            baseline_identity,
            staging_dir,
        )
        if output_dir.exists():
            raise FileExistsError(output_dir)
        staging_dir.rename(output_dir)
    print(json.dumps({"status": "complete", "profile": args.profile, "summary": str(output_dir / "summary.json")}))


if __name__ == "__main__":
    main()
