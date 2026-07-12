from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Sequence

import pandas as pd
import requests

from backtest_config import M1_COLUMNS
from market_data import MarketDataFeed


API_TIMEFRAME_RULES = {
    "5m": "5min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

BINANCE_INTERVALS = {
    "1m": "1m",
    "15m": "15m",
}

OKX_INTERVALS = {
    "1m": "1m",
    "15m": "15m",
}


@dataclass(frozen=True)
class ApiFeedConfig:
    exchange: str = "binance"
    symbol: str = "BTCUSDT"
    okx_symbol: str = "BTC-USDT"
    lookback_days: int = 45
    micro_lookback_days: int = 45
    request_timeout: int = 15
    pause_seconds: float = 0.15


class ExchangeApiMarketDataFeed(MarketDataFeed):
    def __init__(self, config: Optional[ApiFeedConfig] = None):
        self.config = config or ApiFeedConfig()
        self.session = requests.Session()
        self._timeframe_cache: Dict[str, pd.DataFrame] = {}
        self._micro_cache: Optional[pd.DataFrame] = None

    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        df = self._get_timeframe_df(timeframe)
        if columns is not None:
            return df[list(columns)].copy()
        return df.copy()

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        if self._micro_cache is None:
            self._micro_cache = self._fetch_remote_ohlcv("1m", self.config.micro_lookback_days)
        if self._micro_cache.empty:
            return pd.DataFrame(columns=list(columns))
        return self._micro_cache.loc[start_time:end_time, list(columns)].copy()

    def _get_timeframe_df(self, timeframe: str) -> pd.DataFrame:
        if timeframe not in self._timeframe_cache:
            if timeframe == "15m":
                self._timeframe_cache[timeframe] = self._fetch_remote_ohlcv("15m", self.config.lookback_days)
            elif timeframe == "5m":
                base_df = self._fetch_remote_ohlcv("1m", self.config.lookback_days)
                self._timeframe_cache[timeframe] = self._resample_from_15m(base_df, timeframe)
            elif timeframe in API_TIMEFRAME_RULES:
                base_df = self._get_timeframe_df("15m")
                self._timeframe_cache[timeframe] = self._resample_from_15m(base_df, timeframe)
            else:
                raise ValueError(f"Unsupported timeframe: {timeframe}")
        return self._timeframe_cache[timeframe]

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df[["open", "high", "low", "close", "volume"]].astype(float)

    @staticmethod
    def _resample_from_15m(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        rule = API_TIMEFRAME_RULES[timeframe]
        resampled = df.resample(rule, label="left", closed="left").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        return resampled.dropna(subset=["open", "high", "low", "close"])

    def _fetch_remote_ohlcv(self, timeframe: str, lookback_days: int) -> pd.DataFrame:
        exchange = self.config.exchange.lower()
        if exchange == "binance":
            return self._fetch_binance_ohlcv(timeframe, lookback_days)
        if exchange == "okx":
            return self._fetch_okx_ohlcv(timeframe, lookback_days)
        raise ValueError(f"Unsupported exchange: {self.config.exchange}")

    def _fetch_binance_ohlcv(self, timeframe: str, lookback_days: int) -> pd.DataFrame:
        url = "https://api.binance.com/api/v3/klines"
        interval = BINANCE_INTERVALS[timeframe]
        end_time = pd.Timestamp.utcnow().tz_localize(None)
        start_time = end_time - timedelta(days=lookback_days)
        all_rows: List[list] = []
        current_start_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)

        while current_start_ms < end_time_ms:
            response = self.session.get(
                url,
                params={
                    "symbol": self.config.symbol,
                    "interval": interval,
                    "limit": 1000,
                    "startTime": current_start_ms,
                    "endTime": end_time_ms,
                },
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                break
            all_rows.extend(rows)

            last_open_ms = int(rows[-1][0])
            if len(rows) < 1000 or last_open_ms >= end_time_ms:
                break
            current_start_ms = last_open_ms + 1
            time.sleep(self.config.pause_seconds)

        df = pd.DataFrame(
            all_rows,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_asset_volume",
                "taker_buy_quote_asset_volume",
                "ignore",
            ],
        )
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df.set_index("datetime")
        return self._normalize_ohlcv(df)

    def _fetch_okx_ohlcv(self, timeframe: str, lookback_days: int) -> pd.DataFrame:
        url = "https://www.okx.com/api/v5/market/history-candles"
        bar = OKX_INTERVALS[timeframe]
        end_time = pd.Timestamp.utcnow().tz_localize(None)
        start_time = end_time - timedelta(days=lookback_days)
        all_rows: List[list] = []
        after_cursor: Optional[str] = None

        while True:
            params = {
                "instId": self.config.okx_symbol,
                "bar": bar,
                "limit": "300",
            }
            if after_cursor is not None:
                params["after"] = after_cursor

            response = self.session.get(url, params=params, timeout=self.config.request_timeout)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", [])
            if not rows:
                break

            filtered_rows = []
            oldest_seen = None
            for row in rows:
                ts = pd.to_datetime(int(row[0]), unit="ms")
                if ts < start_time:
                    continue
                filtered_rows.append(row)
                oldest_seen = row[0]

            all_rows.extend(filtered_rows)

            if oldest_seen is None or len(rows) < 300:
                break

            earliest_in_batch = pd.to_datetime(int(rows[-1][0]), unit="ms")
            if earliest_in_batch < start_time:
                break

            after_cursor = rows[-1][0]
            time.sleep(self.config.pause_seconds)

        if not all_rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            all_rows,
            columns=["ts", "open", "high", "low", "close", "volume", "vol_ccy", "vol_ccy_quote", "confirm"],
        )
        df["datetime"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
        df = df.set_index("datetime")
        return self._normalize_ohlcv(df)
