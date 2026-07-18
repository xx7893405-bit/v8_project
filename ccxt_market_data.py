from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import ccxt
import duckdb
import pandas as pd

from backtest_config import M1_COLUMNS
from market_data import MarketDataFeed, audit_datetime_index


OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
RESAMPLE_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
EXPECTED_MINUTES = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass(frozen=True)
class CcxtSyncConfig:
    exchange: str = "binance"
    symbol: str = "BTC/USDT:USDT"
    market_type: str = "swap"
    database_path: str = "data/market_data.duckdb"
    sync_interval_minutes: int = 15
    initial_lookback_days: int = 7
    overlap_minutes: int = 5
    close_delay_seconds: int = 5
    fetch_limit: int = 1000
    max_retries: int = 4


class CcxtOHLCVSync:
    """Incrementally synchronize closed 1m candles into a local DuckDB store."""

    def __init__(self, config: Optional[CcxtSyncConfig] = None):
        self.config = config or CcxtSyncConfig()
        self._validate_config()
        self.exchange = self._build_exchange()
        database_path = Path(self.config.database_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(database_path))
        self._ensure_schema()

    def _validate_config(self) -> None:
        if self.config.sync_interval_minutes <= 0:
            raise ValueError("sync_interval_minutes must be greater than zero")
        if self.config.initial_lookback_days <= 0:
            raise ValueError("initial_lookback_days must be greater than zero")
        if self.config.fetch_limit <= 0:
            raise ValueError("fetch_limit must be greater than zero")

    def _build_exchange(self):
        exchange_class = getattr(ccxt, self.config.exchange, None)
        if exchange_class is None:
            raise ValueError(f"Unsupported CCXT exchange: {self.config.exchange}")
        exchange = exchange_class(
            {
                "enableRateLimit": True,
                "options": {"defaultType": self.config.market_type},
            }
        )
        exchange.load_markets()
        if not exchange.has.get("fetchOHLCV"):
            raise RuntimeError(f"{self.config.exchange} does not support fetchOHLCV")
        if self.config.symbol not in exchange.markets:
            raise ValueError(
                f"Symbol {self.config.symbol!r} is unavailable on {self.config.exchange}; "
                "use the CCXT unified symbol format"
            )
        return exchange

    def _ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv_1m (
                exchange VARCHAR NOT NULL,
                market_type VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                open_time TIMESTAMP NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume DOUBLE NOT NULL,
                ingested_at TIMESTAMP NOT NULL,
                PRIMARY KEY (exchange, market_type, symbol, open_time)
            )
            """
        )

    def _last_open_time_ms(self) -> Optional[int]:
        row = self.connection.execute(
            """
            SELECT MAX(open_time)
            FROM ohlcv_1m
            WHERE exchange = ? AND market_type = ? AND symbol = ?
            """,
            [self.config.exchange, self.config.market_type, self.config.symbol],
        ).fetchone()
        if not row or row[0] is None:
            return None
        return int(pd.Timestamp(row[0], tz="UTC").timestamp() * 1000)

    def _fetch_batch(self, since_ms: int) -> list[list]:
        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            try:
                return self.exchange.fetch_ohlcv(
                    self.config.symbol,
                    timeframe="1m",
                    since=since_ms,
                    limit=self.config.fetch_limit,
                )
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
                last_error = exc
                time.sleep(min(2**attempt, 8))
        if last_error is not None:
            raise last_error
        return []

    def sync_once(self, start: Optional[str] = None) -> int:
        now_ms = self.exchange.milliseconds()
        closed_before_ms = now_ms - self.config.close_delay_seconds * 1000
        latest_ms = self._last_open_time_ms()

        if start is not None:
            since_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        elif latest_ms is not None:
            since_ms = latest_ms - self.config.overlap_minutes * 60_000
        else:
            since_ms = now_ms - self.config.initial_lookback_days * 86_400_000

        inserted = 0
        while since_ms + 60_000 <= closed_before_ms:
            rows = self._fetch_batch(since_ms)
            if not rows:
                break

            closed_rows = [row[:6] for row in rows if int(row[0]) + 60_000 <= closed_before_ms]
            if closed_rows:
                ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
                records = [
                    [
                        self.config.exchange,
                        self.config.market_type,
                        self.config.symbol,
                        datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                        float(row[5]),
                        ingested_at,
                    ]
                    for row in closed_rows
                ]
                self.connection.executemany(
                    """
                    INSERT OR REPLACE INTO ohlcv_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    records,
                )
                inserted += len(records)

            last_open_ms = int(rows[-1][0])
            next_since_ms = last_open_ms + 60_000
            if next_since_ms <= since_ms or len(rows) < self.config.fetch_limit:
                break
            since_ms = next_since_ms

        return inserted

    def run_forever(self) -> None:
        interval_seconds = self.config.sync_interval_minutes * 60
        while True:
            started_at = time.time()
            try:
                count = self.sync_once()
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                print(f"[{timestamp}] synchronized {count} closed 1m candles")
            except Exception as exc:
                print(f"1m synchronization failed: {exc}")

            next_boundary = math.floor(started_at / interval_seconds + 1) * interval_seconds
            time.sleep(max(1.0, next_boundary - time.time() + self.config.close_delay_seconds))

    def close(self) -> None:
        self.connection.close()
        close_exchange = getattr(self.exchange, "close", None)
        if callable(close_exchange):
            close_exchange()


class DuckDBMarketDataFeed(MarketDataFeed):
    """Read locally synchronized 1m candles and derive higher timeframes."""

    def __init__(
        self,
        database_path: str = "data/market_data.duckdb",
        exchange: str = "binance",
        market_type: str = "swap",
        symbol: str = "BTC/USDT:USDT",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        self.connection = duckdb.connect(database_path, read_only=True)
        self.exchange = exchange
        self.market_type = market_type
        self.symbol = symbol
        self.start = start
        self.end = end
        self._m1_cache: Optional[pd.DataFrame] = None

    def _load_1m(self) -> pd.DataFrame:
        if self._m1_cache is not None:
            return self._m1_cache
        conditions = ["exchange = ?", "market_type = ?", "symbol = ?"]
        params: list[object] = [self.exchange, self.market_type, self.symbol]
        if self.start is not None:
            conditions.append("open_time >= ?")
            params.append(pd.Timestamp(self.start).to_pydatetime())
        if self.end is not None:
            conditions.append("open_time <= ?")
            params.append(pd.Timestamp(self.end).to_pydatetime())
        query = f"""
            SELECT open_time AS datetime, open, high, low, close, volume
            FROM ohlcv_1m
            WHERE {' AND '.join(conditions)}
            ORDER BY open_time
        """
        df = self.connection.execute(query, params).fetchdf()
        if df.empty:
            raise FileNotFoundError("No matching 1m candles in local DuckDB store")
        df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index).tz_localize(None)
        self._m1_cache = df[OHLCV_COLUMNS].astype(float)
        return self._m1_cache

    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        if timeframe not in RESAMPLE_RULES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        m1 = self._load_1m()
        if timeframe == "1m":
            result = m1.copy()
        else:
            result = m1.resample(RESAMPLE_RULES[timeframe], label="left", closed="left").agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            minute_counts = m1["close"].resample(
                RESAMPLE_RULES[timeframe], label="left", closed="left"
            ).count()
            result = result.loc[minute_counts == EXPECTED_MINUTES[timeframe]]
            result = result.dropna(subset=["open", "high", "low", "close"])
        if columns is not None:
            return result[list(columns)].copy()
        return result

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        return self._load_1m().loc[start_time:end_time, list(columns)].copy()

    def audit_1m(self) -> dict:
        return audit_datetime_index(self._load_1m().index, "1min")


class DualMarketDataFeed(MarketDataFeed):
    """Use one market for signals and another market for simulated execution."""

    def __init__(
        self,
        signal_feed: DuckDBMarketDataFeed,
        execution_feed: DuckDBMarketDataFeed,
    ):
        self.signal_feed = signal_feed
        self.execution_feed = execution_feed

    def load_timeframe(
        self, timeframe: str, columns: Optional[Sequence[str]] = None
    ) -> pd.DataFrame:
        signal = self.signal_feed.load_timeframe(timeframe)
        execution = self.execution_feed.load_timeframe(timeframe)
        execution = execution.rename(columns={column: f"execution_{column}" for column in OHLCV_COLUMNS})
        combined = signal.join(execution, how="inner")
        if combined.empty:
            raise FileNotFoundError(
                f"Signal and execution markets have no aligned {timeframe} candles"
            )
        if columns is not None:
            return combined[list(columns)].copy()
        return combined

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        # Stops, take-profits and their intra-bar order must use execution prices.
        return self.execution_feed.load_micro_window(start_time, end_time, columns)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize closed 1m candles through CCXT.")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--market-type", choices=["spot", "swap", "future"], default="swap")
    parser.add_argument("--database", default="data/market_data.duckdb")
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--start", help="Optional UTC starting point for the first backfill")
    parser.add_argument("--once", action="store_true", help="Synchronize once instead of running continuously")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sync = CcxtOHLCVSync(
        CcxtSyncConfig(
            exchange=args.exchange,
            symbol=args.symbol,
            market_type=args.market_type,
            database_path=args.database,
            sync_interval_minutes=args.interval_minutes,
            initial_lookback_days=args.lookback_days,
        )
    )
    try:
        if args.once:
            count = sync.sync_once(start=args.start)
            print(f"Synchronized {count} closed 1m candles")
        else:
            sync.run_forever()
    finally:
        sync.close()


if __name__ == "__main__":
    main()
