from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence

import pandas as pd

from backtest_config import M1_COLUMNS
from market_data import MarketDataFeed


OhlcvLoader = Callable[[str, Optional[Sequence[str]]], pd.DataFrame]
MicroLoader = Callable[[pd.Timestamp, pd.Timestamp, Sequence[str]], pd.DataFrame]


@dataclass(frozen=True)
class CoinMarketCapFeedConfig:
    symbol: str = "BTC"
    quote: str = "USD"
    provider_name: str = "CoinMarketCap MCP"


class CoinMarketCapMarketDataFeed(MarketDataFeed):
    def __init__(
        self,
        config: Optional[CoinMarketCapFeedConfig] = None,
        timeframe_loader: Optional[OhlcvLoader] = None,
        micro_loader: Optional[MicroLoader] = None,
    ):
        self.config = config or CoinMarketCapFeedConfig()
        self.timeframe_loader = timeframe_loader
        self.micro_loader = micro_loader
        self._timeframe_cache: Dict[str, pd.DataFrame] = {}

    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        if timeframe not in self._timeframe_cache:
            if self.timeframe_loader is None:
                raise RuntimeError(
                    f"{self.config.provider_name} is not connected in this thread, "
                    "so CoinMarketCap timeframe data cannot be fetched yet."
                )
            df = self.timeframe_loader(timeframe, columns=None)
            self._timeframe_cache[timeframe] = self._normalize_ohlcv(df)

        df = self._timeframe_cache[timeframe]
        if columns is not None:
            return df[list(columns)].copy()
        return df.copy()

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        if self.micro_loader is None:
            return pd.DataFrame(columns=list(columns))
        df = self.micro_loader(start_time, end_time, columns)
        if df.empty:
            return pd.DataFrame(columns=list(columns))
        return self._normalize_micro(df).loc[start_time:end_time, list(columns)].copy()

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        normalized = df.copy()
        normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
        normalized = normalized.sort_index()
        normalized = normalized[~normalized.index.duplicated(keep="last")]
        return normalized[["open", "high", "low", "close", "volume"]].astype(float)

    @staticmethod
    def _normalize_micro(df: pd.DataFrame) -> pd.DataFrame:
        normalized = df.copy()
        normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
        normalized = normalized.sort_index()
        normalized = normalized[~normalized.index.duplicated(keep="last")]
        cols = [col for col in columns_or_default(normalized.columns) if col in normalized.columns]
        return normalized[cols]


def columns_or_default(columns: Sequence[str]) -> Sequence[str]:
    if set(M1_COLUMNS).issubset(set(columns)):
        return M1_COLUMNS
    return list(columns)
