from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backtest_config import StrategyConfig
from ccxt_market_data import CcxtOHLCVSync, CcxtSyncConfig, DuckDBMarketDataFeed
from nfe_strategy import NFEDoubleLevelStrategy
from strategy_engine import MultiTimeframeBacktester


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize closed candles and evaluate the NFE strategy once."
    )
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--market-type", choices=["spot", "swap", "future"], default="swap")
    parser.add_argument("--database", default="data/market_data.duckdb")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--ltf", choices=["5m", "15m"], default="15m")
    parser.add_argument("--htf", choices=["1h", "4h"], default="1h")
    parser.add_argument("--state-path", default="runtime/oracle_strategy_state.json")
    return parser.parse_args()


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


def main() -> None:
    args = parse_args()
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
    strategy = NFEDoubleLevelStrategy(
        htf=args.htf,
        ltf=args.ltf,
        htf_n=5,
        ltf_n=3,
        ob_range_type="full",
        min_rr=3.0,
        sl_padding=20.0,
    )
    config = StrategyConfig(
        initial_balance=10000.0,
        risk_pct=0.01,
        position_sizing_mode="risk_based",
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
    snapshot = backtester.build_runtime_snapshot(config)
    decision, reason = classify_decision(snapshot)
    payload = {
        "status": "ok",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "market": {
            "exchange": args.exchange,
            "symbol": args.symbol,
            "market_type": args.market_type,
            "signal_timeframe": args.ltf,
            "structure_timeframe": args.htf,
        },
        "synchronized_rows": synchronized_rows,
        "decision": decision,
        "reason": reason,
        "snapshot": snapshot,
    }
    atomic_json_write(Path(args.state_path), payload)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
