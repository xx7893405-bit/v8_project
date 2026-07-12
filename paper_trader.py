from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from market_data import CSVMarketDataFeed, MarketDataFeed
from multi_timeframe_backtest import build_default_strategy
from strategy_engine import MultiTimeframeBacktester
from trading_runtime import PaperTradingConfig, RuntimeSnapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run paper trading snapshots with CSV or exchange API data.")
    parser.add_argument("--data-source", choices=["csv", "api"], default="csv")
    parser.add_argument("--data-dir", default=".")
    parser.add_argument("--exchange", choices=["binance", "okx"], default="binance")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--okx-symbol", default="BTC-USDT")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--micro-lookback-days", type=int, default=45)
    parser.add_argument("--poll-interval", type=int, default=60)
    parser.add_argument("--cycles", type=int, default=1, help="Use 0 for infinite polling.")
    parser.add_argument("--state-path", default="paper_trading_state.json")
    parser.add_argument("--journal-path", default="paper_trading_journal.json")
    parser.add_argument("--min-strategy-amount", type=float, default=100.0)
    return parser.parse_args()


def build_feed(args: argparse.Namespace) -> MarketDataFeed:
    if args.data_source == "csv":
        return CSVMarketDataFeed(data_dir=args.data_dir)
    return ExchangeApiMarketDataFeed(
        ApiFeedConfig(
            exchange=args.exchange,
            symbol=args.symbol,
            okx_symbol=args.okx_symbol,
            lookback_days=args.lookback_days,
            micro_lookback_days=args.micro_lookback_days,
        )
    )


def append_journal(path: Path, snapshot: dict) -> None:
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = []
    data.append(snapshot)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def main() -> None:
    args = parse_args()
    runtime = PaperTradingConfig(
        data_source=args.data_source,
        poll_interval_seconds=args.poll_interval,
        cycles=args.cycles,
        state_path=args.state_path,
        journal_path=args.journal_path,
    )
    strategy = build_default_strategy()
    if args.min_strategy_amount < 0:
        raise ValueError("min-strategy-amount cannot be negative")
    strategy = strategy.__class__(
        **{**strategy.__dict__, "min_strategy_amount": args.min_strategy_amount}
    )

    iteration = 0
    while runtime.cycles == 0 or iteration < runtime.cycles:
        previous_snapshot = None
        if Path(runtime.state_path).exists():
            with open(runtime.state_path, "r", encoding="utf-8") as fh:
                previous_snapshot = json.load(fh)
        previous_halted = bool(previous_snapshot and previous_snapshot.get("strategy_halted"))
        previous_balance = float(previous_snapshot.get("balance", strategy.initial_balance)) if previous_snapshot else strategy.initial_balance
        cycle_strategy = strategy.__class__(
            **{
                **strategy.__dict__,
                "allow_new_entries": not previous_halted and previous_balance >= args.min_strategy_amount,
            }
        )
        try:
            feed = build_feed(args)
            backtester = MultiTimeframeBacktester(
                config=cycle_strategy.to_backtest_config(),
                data_feed=feed,
                data_dir=args.data_dir,
            )
            snapshot_payload = backtester.build_runtime_snapshot(
                cycle_strategy, resume_snapshot=previous_snapshot
            )
        except FileNotFoundError as exc:
            print(f"paper trader failed: missing data file: {exc}")
            return
        except Exception as exc:
            print(f"paper trader failed: {exc}")
            return
        snapshot_payload["strategy_halted"] = bool(
            args.min_strategy_amount > 0 and snapshot_payload["balance"] < args.min_strategy_amount
        ) or previous_halted
        snapshot = RuntimeSnapshot(mode="paper", **snapshot_payload)

        with open(runtime.state_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot.to_dict(), fh, indent=2, ensure_ascii=False)
        append_journal(Path(runtime.journal_path), snapshot.to_dict())

        print(f"[paper] as_of={snapshot.as_of} balance={snapshot.balance:.2f} trades={snapshot.trade_count} missed={snapshot.missed_count}")
        if snapshot.active_position is not None:
            print(
                "[paper] active_position="
                f"{snapshot.active_position['type']} entry={snapshot.active_position['entry_price']} "
                f"sl={snapshot.active_position['sl']} tp2={snapshot.active_position['tp2']}"
            )
        elif snapshot.pending_retest_order is not None:
            print(
                "[paper] pending_retest="
                f"{snapshot.pending_retest_order['type']} entry={snapshot.pending_retest_order['entry_price']}"
            )
        elif snapshot.pending_breakout_order is not None:
            print(f"[paper] pending_breakout={snapshot.pending_breakout_order['type']}")
        else:
            print("[paper] no active or pending setup.")

        iteration += 1
        if runtime.cycles != 0 and iteration >= runtime.cycles:
            break
        time.sleep(runtime.poll_interval_seconds)


if __name__ == "__main__":
    main()
