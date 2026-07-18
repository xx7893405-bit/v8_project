from __future__ import annotations

import gc
from pathlib import Path
from typing import Dict, Optional, Protocol, Sequence

import pandas as pd

from backtest_config import M1_COLUMNS, TIMEFRAME_FILES


def audit_datetime_index(index: pd.Index, frequency: str) -> dict:
    """Return duplicate and missing open times under the UTC/open-time contract."""
    normalized = pd.DatetimeIndex(pd.to_datetime(index, utc=True)).tz_localize(None)
    unique = normalized.drop_duplicates().sort_values()
    missing = (
        pd.date_range(unique[0], unique[-1], freq=frequency).difference(unique)
        if len(unique) > 1
        else pd.DatetimeIndex([])
    )
    return {
        "rows": len(normalized),
        "duplicates": int(normalized.duplicated().sum()),
        "missing": missing,
    }


class MarketDataFeed(Protocol):
    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        ...

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        ...


class CSVMarketDataFeed:
    def __init__(
        self,
        data_dir: str | Path = ".",
        timeframe_files: Optional[Dict[str, str]] = None,
        micro_filename: str = "btc_1m.csv",
    ):
        self.data_dir = Path(data_dir)
        self.timeframe_files = timeframe_files or TIMEFRAME_FILES
        self.micro_filename = micro_filename
        self._micro_cache: Dict[object, pd.DataFrame] = {}
        self._micro_cache_loaded = False

    def _data_path(self, filename: str) -> Path:
        return self.data_dir / filename

    @staticmethod
    def _normalize_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
        df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
        return df[~df.index.duplicated(keep="last")].sort_index()

    def load_timeframe(self, timeframe: str, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
        filename = self.timeframe_files[timeframe]
        df = pd.read_csv(self._data_path(filename), index_col="datetime", parse_dates=True)
        df = self._normalize_datetime_index(df)
        if columns is not None:
            return df[list(columns)]
        return df

    def _ensure_micro_cache(self) -> None:
        if self._micro_cache_loaded:
            return

        chunk_iter = pd.read_csv(
            self._data_path(self.micro_filename),
            index_col="datetime",
            parse_dates=True,
            usecols=["datetime", *M1_COLUMNS],
            chunksize=200000,
        )
        micro_chunks = []
        for chunk in chunk_iter:
            chunk = self._normalize_datetime_index(chunk)
            micro_chunks.append(chunk.astype({col: "float32" for col in M1_COLUMNS}))

        df_1m_all = pd.concat(micro_chunks).sort_index()
        df_1m_all["date_key"] = df_1m_all.index.date
        for date_key, group in df_1m_all.groupby("date_key"):
            self._micro_cache[date_key] = group[M1_COLUMNS]

        print(f"💡 1m 數據快取完畢，共載入 {len(self._micro_cache)} 天的微觀歷史資料。")
        self._micro_cache_loaded = True
        del df_1m_all, micro_chunks
        gc.collect()

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        self._ensure_micro_cache()
        date_range = pd.date_range(start=start_time.normalize(), end=end_time.normalize(), freq="D")
        slices = []
        for day in date_range:
            cached = self._micro_cache.get(day.date())
            if cached is not None:
                slices.append(cached[list(columns)])
        if not slices:
            return pd.DataFrame(columns=list(columns))
        return pd.concat(slices).loc[start_time:end_time]
