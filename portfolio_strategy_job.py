from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed
from backtest_config import StrategyConfig
from multi_timeframe_backtest import MultiTimeframeBacktester
from oracle_strategy_job import build_strategy
from portfolio_runtime import PortfolioAccount


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build_portfolio(config: dict, previous: dict) -> PortfolioAccount:
    symbols = config["symbols"]
    if previous:
        account = PortfolioAccount.from_snapshot(previous["portfolio"])
        for symbol, values in symbols.items():
            if symbol in account.symbols:
                if account.symbols[symbol].strategy != values["strategy"]:
                    raise ValueError(f"{symbol} already belongs to another strategy")
                continue
            account.add_symbol(
                symbol,
                strategy=values["strategy"],
                margin_budget=float(values["margin_budget"]),
                min_strategy_amount=float(values["min_strategy_amount"]),
            )
        return account
    return PortfolioAccount.from_config(float(config["account_balance"]), symbols)


def run_account(config: dict, state_path: Path, events_path: Path) -> dict:
    previous = load_json(state_path)
    portfolio = build_portfolio(config, previous)
    snapshots = previous.get("snapshots", {})
    events: list[dict] = []
    for symbol, values in config["symbols"].items():
        previous_snapshot = snapshots.get(symbol)
        resume_snapshot = copy.deepcopy(previous_snapshot) if previous_snapshot else None
        if resume_snapshot is not None:
            resume_snapshot["balance"] = portfolio.strategy_amount(symbol)
        strategy_config = StrategyConfig(
            initial_balance=portfolio.strategy_amount(symbol),
            risk_pct=float(config.get("risk_pct", 0.01)),
            leverage=float(config.get("max_leverage", 3.0)),
            min_strategy_amount=portfolio.symbols[symbol].min_strategy_amount,
            allow_new_entries=portfolio.can_open_new_position(symbol),
        )
        public_symbol = values.get("public_symbol", symbol.replace("/", "").split(":")[0])
        feed = ExchangeApiMarketDataFeed(
            ApiFeedConfig(
                exchange=config.get("exchange", "binance"),
                symbol=public_symbol,
                okx_symbol=values.get("okx_symbol", symbol.replace("/", "-" ).split(":")[0]),
                lookback_days=int(config.get("lookback_days", 45)),
                micro_lookback_days=int(config.get("micro_lookback_days", 45)),
            )
        )
        backtester = MultiTimeframeBacktester(
            config=strategy_config.to_backtest_config(),
            data_feed=feed,
            strategy=build_strategy(values["strategy"], config.get("htf", "1h"), config.get("ltf", "15m")),
        )
        snapshot = backtester.build_runtime_snapshot(strategy_config, resume_snapshot=resume_snapshot)
        previous_trade_count = len(previous_snapshot.get("trades", [])) if previous_snapshot else 0
        for trade in snapshot.get("trades", [])[previous_trade_count:]:
            event = portfolio.apply_realized_pnl(symbol, float(trade.get("pnl", 0.0)))
            if event:
                event.update({"account_id": config["account_id"], "detected_at": datetime.now(timezone.utc).isoformat()})
                events.append(event)
        snapshot["strategy_halted"] = not portfolio.can_open_new_position(symbol)
        snapshots[symbol] = snapshot

    if events_path.suffix == ".jsonl":
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    payload = {
        "account_id": config["account_id"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio.snapshot(),
        "snapshots": snapshots,
        "event_count": len(events),
        "unallocated_balance": portfolio.unallocated_balance,
    }
    atomic_json_write(state_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one multi-symbol paper portfolio cycle.")
    parser.add_argument("--config", required=True, help="Account JSON configuration")
    parser.add_argument("--state-path")
    parser.add_argument("--events-path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_json(Path(args.config))
    account_id = config["account_id"]
    state_path = Path(args.state_path or f"runtime/accounts/{account_id}/portfolio_state.json")
    events_path = Path(args.events_path or f"runtime/accounts/{account_id}/portfolio_events.jsonl")
    print(json.dumps(run_account(config, state_path, events_path), ensure_ascii=False))


if __name__ == "__main__":
    main()
