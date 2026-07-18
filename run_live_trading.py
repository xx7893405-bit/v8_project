from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from backtest_config import StrategyConfig
from execution_engine import CcxtExecutionClient, DryRunExecutionClient, LiveExecutionEngine
from oracle_strategy_job import atomic_json_write, build_strategy
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare live-trading actions from the latest strategy snapshot.")
    parser.add_argument("--exchange", choices=["binance", "okx"], default="binance")
    parser.add_argument("--symbol", default="BTCUSDT", help="Raw public API symbol for Binance")
    parser.add_argument("--ccxt-symbol", default="BTC/USDT:USDT", help="Unified perpetual symbol used for orders")
    parser.add_argument("--okx-symbol", default="BTC-USDT-SWAP", help="OKX perpetual-swap instrument id")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--micro-lookback-days", type=int, default=45)
    parser.add_argument("--strategy", choices=["nfe", "nfe-v2", "nfe-v4", "v8"], default="nfe-v2")
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    parser.add_argument("--risk-pct", type=float, default=0.01)
    parser.add_argument("--max-risk-pct", type=float, default=0.02)
    parser.add_argument("--min-strategy-amount", type=float, default=100.0)
    parser.add_argument("--max-leverage", type=float, default=3.0)
    parser.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    parser.add_argument("--state-path", default="runtime/live_trading_state.json")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--live", dest="dry_run", action="store_false")
    parser.add_argument("--sandbox", dest="sandbox", action="store_true", default=True)
    parser.add_argument("--no-sandbox", dest="sandbox", action="store_false")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 < args.risk_pct <= args.max_risk_pct <= 1:
        raise ValueError("risk-pct must be > 0, <= max-risk-pct, and max-risk-pct <= 1")
    if not 1 <= args.max_leverage <= 100:
        raise ValueError("max-leverage must be between 1 and 100")
    if args.min_strategy_amount < 0:
        raise ValueError("min-strategy-amount cannot be negative")
    strategy = StrategyConfig(
        initial_balance=10_000.0,
        risk_pct=args.risk_pct,
        leverage=args.max_leverage,
        min_strategy_amount=args.min_strategy_amount,
        max_holding_bars=96,
        mode="NONE",
        enable_be=True,
        tp1_close_pct=0.5,
        be_trigger_ratio=1.5,
    )
    strategy_impl = build_strategy(args.strategy, args.htf, args.ltf)
    state_path = Path(args.state_path)
    previous_payload = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    previous_snapshot = previous_payload.get("snapshot")
    try:
        feed = ExchangeApiMarketDataFeed(
            ApiFeedConfig(
                exchange=args.exchange,
                symbol=args.symbol,
                okx_symbol=args.okx_symbol,
                lookback_days=args.lookback_days,
                micro_lookback_days=args.micro_lookback_days,
            )
        )
        backtester = MultiTimeframeBacktester(
            config=strategy.to_backtest_config(), data_feed=feed, strategy=strategy_impl
        )
        if previous_snapshot is None:
            signal_df = backtester._get_signal_frame()
            start_at = signal_df.index[-1] if not signal_df.empty else None
            snapshot = backtester.build_runtime_snapshot(strategy, start_at=start_at)
        else:
            snapshot = backtester.build_runtime_snapshot(strategy, resume_snapshot=previous_snapshot)
    except Exception as exc:
        print(f"live trading prep failed: {exc}")
        return

    active_position = snapshot["active_position"]
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"exchange": args.exchange, "symbol": args.ccxt_symbol, "ltf": args.ltf, "htf": args.htf},
        "strategy": args.strategy,
        "snapshot": snapshot,
    }
    if previous_snapshot is None:
        atomic_json_write(state_path, payload)
        print("Initialized live state from the latest closed bar; historical positions were not mirrored.")
        return
    if active_position is None:
        atomic_json_write(state_path, payload)
        print("No active simulated position to mirror into live execution.")
        return

    entry_time = str(active_position.get("entry_time") or "unknown")
    active_position["live_entry_tag"] = f"entry-{active_position['type']}-{''.join(ch for ch in entry_time if ch.isdigit())[-12:]}"[:32]
    previous_position = previous_snapshot.get("active_position") if previous_snapshot else None
    is_new_entry = not previous_position or previous_position.get("entry_time") != active_position.get("entry_time")

    if args.dry_run:
        client = DryRunExecutionClient()
    else:
        if os.getenv("ALLOW_LIVE_TRADING") != "YES":
            raise RuntimeError("Set ALLOW_LIVE_TRADING=YES explicitly before using --live")
        client = CcxtExecutionClient.from_environment(
            args.exchange, args.ccxt_symbol, sandbox=args.sandbox, margin_mode=args.margin_mode
        )
    engine = LiveExecutionEngine(client)
    entry_result, exit_results = engine.reconcile_position(active_position, allow_entry=is_new_entry)
    payload["last_execution"] = {
        "entry_status": entry_result.status,
        "entry_order_id": entry_result.exchange_order_id,
        "exit_statuses": [result.status for result in exit_results],
    }
    atomic_json_write(state_path, payload)

    print(f"entry: {entry_result.status} {entry_result.message}")
    for result in exit_results:
        print(f"exit: {result.status} {result.message}")


if __name__ == "__main__":
    main()
