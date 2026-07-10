from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd

from market_data import MarketDataFeed


@dataclass(frozen=True)
class FeedAuditRecord:
    timeframe: str
    primary_rows: int
    secondary_rows: int
    overlapping_rows: int
    close_mae: Optional[float]


class HybridMarketDataFeed(MarketDataFeed):
    def __init__(
        self,
        primary_feed: MarketDataFeed,
        secondary_feed: Optional[MarketDataFeed] = None,
        prefer_primary: bool = True,
        audit: bool = False,
    ):
        self.primary_feed = primary_feed
        self.secondary_feed = secondary_feed
        self.prefer_primary = prefer_primary
        self.audit = audit
        self.audit_log: list[FeedAuditRecord] = []

    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        if self.secondary_feed is None:
            return self.primary_feed.load_timeframe(timeframe, columns)

        first = self.primary_feed if self.prefer_primary else self.secondary_feed
        second = self.secondary_feed if self.prefer_primary else self.primary_feed

        first_df = self._try_load_timeframe(first, timeframe)
        second_df = self._try_load_timeframe(second, timeframe)

        if first_df is None and second_df is None:
            raise FileNotFoundError(f"No data available for timeframe: {timeframe}")
        if first_df is None:
            chosen = second_df
        elif second_df is None:
            chosen = first_df
        else:
            chosen = self._merge_prefer_first(first_df, second_df)
            if self.audit:
                self.audit_log.append(self._build_audit_record(timeframe, first_df, second_df))

        if columns is not None:
            return chosen[list(columns)].copy()
        return chosen.copy()

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        if self.secondary_feed is None:
            return self.primary_feed.load_micro_window(start_time, end_time, columns)

        first = self.primary_feed if self.prefer_primary else self.secondary_feed
        second = self.secondary_feed if self.prefer_primary else self.primary_feed

        first_df = self._try_load_micro(first, start_time, end_time, columns)
        second_df = self._try_load_micro(second, start_time, end_time, columns)

        if first_df is None and second_df is None:
            return pd.DataFrame(columns=list(columns))
        if first_df is None:
            return second_df
        if second_df is None:
            return first_df
        return self._merge_prefer_first(first_df, second_df).loc[start_time:end_time, list(columns)].copy()

    @staticmethod
    def _try_load_timeframe(feed: MarketDataFeed, timeframe: str) -> Optional[pd.DataFrame]:
        try:
            return feed.load_timeframe(timeframe)
        except (FileNotFoundError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _try_load_micro(
        feed: MarketDataFeed,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> Optional[pd.DataFrame]:
        try:
            return feed.load_micro_window(start_time, end_time, columns)
        except (FileNotFoundError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _merge_prefer_first(first_df: pd.DataFrame, second_df: pd.DataFrame) -> pd.DataFrame:
        merged = first_df.combine_first(second_df)
        merged.index = pd.to_datetime(merged.index).tz_localize(None)
        return merged.sort_index()

    @staticmethod
    def _build_audit_record(timeframe: str, first_df: pd.DataFrame, second_df: pd.DataFrame) -> FeedAuditRecord:
        overlap = first_df.index.intersection(second_df.index)
        close_mae = None
        if len(overlap) > 0 and "close" in first_df.columns and "close" in second_df.columns:
            diffs = (first_df.loc[overlap, "close"] - second_df.loc[overlap, "close"]).abs()
            close_mae = float(diffs.mean()) if not diffs.empty else None
        return FeedAuditRecord(
            timeframe=timeframe,
            primary_rows=len(first_df),
            secondary_rows=len(second_df),
            overlapping_rows=len(overlap),
            close_mae=close_mae,
        )
