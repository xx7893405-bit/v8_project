from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_config import StrategyConfig
from ccxt_market_data import CcxtOHLCVSync, CcxtSyncConfig, DuckDBMarketDataFeed
from nfe_strategy import NFEDoubleLevelStrategy
from nfe_v2_strategy import NFEV2Strategy
from nfe_v4_strategy import NFEV4Strategy
from strategy_engine import MultiTimeframeBacktester
from v8_strategy import V8FvgOverlapStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize closed candles and evaluate the NFE strategy once."
    )
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--market-type", choices=["spot", "swap", "future"], default="swap")
    parser.add_argument("--database", default="data/market_data.duckdb")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--risk-pct", type=float, default=0.05)
    parser.add_argument("--min-strategy-amount", type=float, default=100.0)
    parser.add_argument("--max-leverage", type=float, default=1.0)
    parser.add_argument(
        "--strategy",
        choices=["nfe", "nfe-v2", "nfe-v4", "v8"],
        default="nfe-v2",
        help="Strategy to replay and evaluate (default: nfe-v2)",
    )
    parser.add_argument(
        "--account-id",
        default="paper-nfe-v2",
        help="Stable paper-account identifier included in state and events",
    )
    parser.add_argument(
        "--account-name",
        help="Human-readable account name shown by the monitor",
    )
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    parser.add_argument("--state-path", default="runtime/oracle_strategy_state.json")
    parser.add_argument("--events-path", default="runtime/oracle_strategy_events.jsonl")
    parser.add_argument(
        "--forward-start-path", default="runtime/oracle_forward_start.json"
    )
    parser.add_argument("--start-at", help="Fixed UTC strategy accounting start time")
    return parser.parse_args()


def build_strategy(name: str, htf: str, ltf: str):
    if name == "v8":
        return V8FvgOverlapStrategy()

    if name == "nfe-v4":
        return NFEV4Strategy(
            htf=htf,
            ltf=ltf,
            htf_n=5,
            ltf_n=3,
            ob_range_type="full",
            min_rr=3.0,
            sl_padding=20.0,
            defensive_atr_mult=0.6,
        )

    strategy_class = NFEV2Strategy if name == "nfe-v2" else NFEDoubleLevelStrategy
    return strategy_class(
        htf=htf,
        ltf=ltf,
        htf_n=5,
        ltf_n=3,
        ob_range_type="full",
        min_rr=3.0,
        sl_padding=20.0,
    )


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def publish_status(payload: dict) -> None:
    url, token = os.getenv("STATUS_PUSH_URL"), os.getenv("STATUS_PUSH_TOKEN")
    site_token = os.getenv("STATUS_SITE_TOKEN")
    if not url or not token or not site_token:
        print("warning: status push skipped; missing STATUS_PUSH_URL, STATUS_PUSH_TOKEN, or STATUS_SITE_TOKEN")
        return
    request = urllib.request.Request(
        url, json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "OAI-Sites-Authorization": f"Bearer {site_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError(f"status push returned {response.status}")
    except Exception as error:
        print(f"warning: status push failed: {error}")


def strategy_events(payload: dict, events_path: Path) -> list[dict]:
    snapshot = payload["snapshot"]
    candidates = [("ENTRY", snapshot["active_position"])] if snapshot.get("active_position") else []
    candidates += [("TRADE_CLOSED", trade) for trade in snapshot.get("trades", [])]
    written = set()
    if events_path.exists():
        written = {
            json.loads(line)["event_id"]
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    events = []
    for event_type, trade in candidates:
        event_id = ":".join(
            [
                str(payload["run_id"]), event_type, str(trade.get("type")),
                str(trade.get("entry_time")), str(trade.get("exit_time", "")),
            ]
        )
        if event_id in written:
            continue
        events.append(
            {
                "event_id": event_id,
                "run_id": payload["run_id"],
                "account_id": payload["account_id"],
                "event_type": event_type,
                "detected_at": payload["evaluated_at"],
                "evaluated_at": payload["evaluated_at"],
                "as_of": snapshot.get("as_of"),
                "strategy": payload.get("strategy"),
                "decision": payload.get("decision"),
                "balance": snapshot.get("balance"),
                **trade,
            }
        )
    if snapshot.get("strategy_halted") and not payload.get("previous_strategy_halted", False):
        event_id = f"{payload['run_id']}:STRATEGY_HALTED_MIN_AMOUNT"
        if event_id not in written:
            events.append(
                {
                    "event_id": event_id,
                    "run_id": payload["run_id"],
                    "account_id": payload["account_id"],
                    "event_type": "STRATEGY_HALTED_MIN_AMOUNT",
                    "detected_at": payload["evaluated_at"],
                    "evaluated_at": payload["evaluated_at"],
                    "as_of": snapshot.get("as_of"),
                    "strategy": payload.get("strategy"),
                    "decision": "HALTED",
                    "balance": snapshot.get("balance"),
                    "min_strategy_amount": payload.get("min_strategy_amount"),
                    "reason": "strategy_balance_below_minimum",
                }
            )
    return events


def append_jsonl(path: Path, events: list[dict]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def classify_decision(snapshot: dict) -> tuple[str, str]:
    active = snapshot.get("active_position")
    if active:
        side = str(active.get("type", "UNKNOWN")).upper()
        return side, "ACTIVE_POSITION"
    pending = snapshot.get("pending_retest_order") or snapshot.get("pending_breakout_order")
    if pending:
        side = str(pending.get("type", "WAIT")).upper()
        return side if side in {"LONG", "SHORT"} else "WAIT", "PENDING_ORDER"
    return "FLAT", "NO_SETUP"


def load_or_create_forward_run(path: Path, requested_start: str | None = None) -> tuple[str, str]:
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if requested_start is not None:
        timestamp = pd.Timestamp(requested_start)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        forward_start = timestamp.isoformat()
    else:
        forward_start = str(existing.get("forward_start") or datetime.now(timezone.utc).isoformat())
    if existing.get("forward_start") == forward_start:
        # Existing runs created before run IDs use a stable legacy ID, avoiding a replay.
        run_id = str(existing.get("run_id") or f"legacy-{forward_start}")
    else:
        run_id = uuid.uuid4().hex
    atomic_json_write(path, {"forward_start": forward_start, "run_id": run_id})
    return forward_start, run_id


def load_or_create_forward_start(path: Path, requested_start: str | None = None) -> str:
    return load_or_create_forward_run(path, requested_start)[0]


def load_resume_snapshot(path: Path, forward_start: str, run_id: str | None = None) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("forward_start") != forward_start:
        return None
    if run_id and payload.get("run_id", f"legacy-{forward_start}") != run_id:
        return None
    return payload.get("snapshot")


def main() -> None:
    args = parse_args()
    if not 0 < args.risk_pct <= 1:
        raise ValueError("risk-pct must be greater than 0 and no greater than 1")
    if args.min_strategy_amount < 0:
        raise ValueError("min-strategy-amount cannot be negative")
    if not 1 <= args.max_leverage <= 1000:
        raise ValueError("max-leverage must be between 1 and 1000")
    sync = CcxtOHLCVSync(
        CcxtSyncConfig(
            exchange=args.exchange,
            symbol=args.symbol,
            market_type=args.market_type,
            database_path=args.database,
            initial_lookback_days=args.lookback_days,
        )
    )
    try:
        synchronized_rows = sync.sync_once()
    finally:
        sync.close()

    feed = DuckDBMarketDataFeed(
        database_path=args.database,
        exchange=args.exchange,
        market_type=args.market_type,
        symbol=args.symbol,
    )
    strategy = build_strategy(args.strategy, args.htf, args.ltf)
    forward_start, run_id = load_or_create_forward_run(
        Path(args.forward_start_path), args.start_at
    )
    config = StrategyConfig(
        initial_balance=10000.0,
        risk_pct=args.risk_pct,
        position_sizing_mode="risk_based",
        leverage=args.max_leverage,
        maker_fee=0.0002,
        taker_fee=0.0005,
        max_holding_bars=96,
        min_net_profit_r=3.0,
        mode="NONE",
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
    )
    backtester = MultiTimeframeBacktester(
        config=config.to_backtest_config(), data_feed=feed, strategy=strategy
    )
    start_at = pd.Timestamp(forward_start).tz_convert("UTC").tz_localize(None)
    state_path = Path(args.state_path)
    previous_snapshot = load_resume_snapshot(state_path, forward_start, run_id)
    previous_as_of = previous_snapshot.get("as_of") if previous_snapshot else None
    previous_strategy_halted = bool(previous_snapshot and previous_snapshot.get("strategy_halted"))
    previous_balance = float(previous_snapshot.get("balance", 10000.0)) if previous_snapshot else 10000.0
    snapshot = backtester.build_runtime_snapshot(
        StrategyConfig(
            **{
                **config.__dict__,
                "allow_new_entries": not previous_strategy_halted and previous_balance >= args.min_strategy_amount,
                "min_strategy_amount": args.min_strategy_amount,
            }
        ),
        start_at=start_at,
        resume_snapshot=previous_snapshot,
    )
    snapshot["strategy_halted"] = bool(
        args.min_strategy_amount > 0 and snapshot["balance"] < args.min_strategy_amount
    ) or previous_strategy_halted
    decision, reason = classify_decision(snapshot)
    if snapshot["strategy_halted"] and snapshot.get("active_position") is None:
        decision, reason = "HALTED", "MIN_STRATEGY_AMOUNT"
    payload = {
        "status": "ok",
        "account_id": args.account_id,
        "account_name": args.account_name or args.account_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "market": {
            "exchange": args.exchange,
            "symbol": args.symbol,
            "market_type": args.market_type,
            "signal_timeframe": args.ltf,
            "structure_timeframe": args.htf,
        },
        "strategy": args.strategy,
        "risk_pct": args.risk_pct,
        "min_strategy_amount": args.min_strategy_amount,
        "max_leverage": args.max_leverage,
        "forward_start": forward_start,
        "run_id": run_id,
        "synchronized_rows": synchronized_rows,
        "processed_new_signal_bars": (
            previous_as_of is None or snapshot["as_of"] != previous_as_of
        ),
        "decision": decision,
        "reason": reason,
        "previous_strategy_halted": previous_strategy_halted,
        "snapshot": snapshot,
    }
    events_path = Path(args.events_path)
    append_jsonl(events_path, strategy_events(payload, events_path))
    atomic_json_write(state_path, payload)
    publish_status(payload)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
