from __future__ import annotations

import argparse

from ccxt_market_data import CcxtOHLCVSync, CcxtSyncConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize spot and perpetual 1m candles.")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--spot-symbol", default="BTC/USDT")
    parser.add_argument("--perp-symbol", default="BTC/USDT:USDT")
    parser.add_argument("--database", default="data/market_data.duckdb")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--start")
    return parser.parse_args()


def sync_market(args: argparse.Namespace, market_type: str, symbol: str) -> int:
    sync = CcxtOHLCVSync(
        CcxtSyncConfig(
            exchange=args.exchange,
            symbol=symbol,
            market_type=market_type,
            database_path=args.database,
            initial_lookback_days=args.lookback_days,
        )
    )
    try:
        return sync.sync_once(start=args.start)
    finally:
        sync.close()


def main() -> None:
    args = parse_args()
    spot_rows = sync_market(args, "spot", args.spot_symbol)
    perp_rows = sync_market(args, "swap", args.perp_symbol)
    print(f"Synchronized spot={spot_rows} rows, perpetual={perp_rows} rows")


if __name__ == "__main__":
    main()
