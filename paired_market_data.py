from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import duckdb
import pandas as pd


OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
RESAMPLE_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
EXPECTED_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_index(values: pd.Index | pd.Series) -> pd.DatetimeIndex:
    normalized = pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_localize(None)
    # DuckDB currently returns microseconds while CSV parsing commonly returns
    # nanoseconds; normalize the dtype as well as the timestamp values.
    return normalized.astype("datetime64[ns]")


def _audit(path: Path, index: pd.DatetimeIndex) -> dict:
    unique = index.drop_duplicates().sort_values()
    missing = 0
    if len(unique) > 1:
        expected = int((unique[-1] - unique[0]) / pd.Timedelta(minutes=1)) + 1
        missing = expected - len(unique)
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "rows": len(index),
        "first": unique[0].isoformat() if len(unique) else None,
        "last": unique[-1].isoformat() if len(unique) else None,
        "duplicates": int(index.duplicated().sum()),
        "missing": missing,
    }


def _load_spot(path: Path) -> tuple[pd.DataFrame, dict]:
    source = pd.read_csv(path)
    required = {"datetime", *OHLCV_COLUMNS}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"Spot CSV is missing columns: {sorted(missing)}")
    index = _normalize_index(source["datetime"])
    audit = _audit(path, index)
    frame = source.loc[:, OHLCV_COLUMNS].copy()
    frame.index = index
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index().astype(float)
    return frame, audit


def _load_perp(path: Path) -> tuple[pd.DataFrame, dict]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('ohlcv_1m')").fetchall()
        }
        order_suffix = ", ingested_at" if "ingested_at" in columns else ""
        frame = connection.execute(
            f"""
            SELECT open_time AS datetime, open, high, low, close, volume
            FROM ohlcv_1m
            WHERE exchange = 'binance'
              AND market_type = 'swap'
              AND symbol = 'BTC/USDT:USDT'
            ORDER BY open_time{order_suffix}
            """
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise FileNotFoundError("No canonical Binance BTC/USDT:USDT swap candles found")
    index = _normalize_index(frame.pop("datetime"))
    audit = _audit(path, index)
    frame.index = index
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index().astype(float)
    return frame, audit


def _fingerprint(spot: pd.DataFrame, perp: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for label, frame in (("spot", spot), ("perp", perp)):
        digest.update(label.encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class AlignedOneMinuteFeed:
    """Immutable-by-interface aligned 1m candles with complete-bar resampling."""

    _one_minute: pd.DataFrame

    def load_timeframe(
        self, timeframe: str, columns: Optional[Sequence[str]] = None
    ) -> pd.DataFrame:
        if timeframe not in RESAMPLE_RULES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if timeframe == "1m":
            result = self._one_minute.copy()
        else:
            rule = RESAMPLE_RULES[timeframe]
            result = self._one_minute.resample(rule, label="left", closed="left").agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            counts = self._one_minute["close"].resample(
                rule, label="left", closed="left"
            ).count()
            result = result.loc[counts == EXPECTED_MINUTES[timeframe]]
        if columns is not None:
            return result.loc[:, list(columns)].copy()
        return result.copy()

    def load_micro_window(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        columns: Sequence[str],
    ) -> pd.DataFrame:
        start = pd.Timestamp(start_time)
        end = pd.Timestamp(end_time)
        if start.tzinfo is not None:
            start = start.tz_convert("UTC").tz_localize(None)
        if end.tzinfo is not None:
            end = end.tz_convert("UTC").tz_localize(None)
        return self._one_minute.loc[start:end, list(columns)].copy()


def load_aligned_market_feeds(
    spot_csv: str | Path,
    perp_database: str | Path,
) -> tuple[AlignedOneMinuteFeed, AlignedOneMinuteFeed, dict]:
    """Load price-identical-time feeds so market source is the only variable."""

    spot_path = Path(spot_csv)
    perp_path = Path(perp_database)
    spot_raw, spot_audit = _load_spot(spot_path)
    perp_raw, perp_audit = _load_perp(perp_path)

    common_index = spot_raw.index.intersection(perp_raw.index).sort_values()
    if common_index.empty:
        raise ValueError("Spot and perpetual sources have no common 1m timestamps")
    spot = spot_raw.loc[common_index].copy()
    perp = perp_raw.loc[common_index].copy()
    common_first = common_index[0].isoformat()
    common_last = common_index[-1].isoformat()
    common_fingerprint = _fingerprint(spot, perp)
    audit = {
        "spot": spot_audit,
        "perp": perp_audit,
        "common": {
            "rows": len(common_index),
            "first": common_first,
            "last": common_last,
            "fingerprint": common_fingerprint,
        },
        "common_rows": len(common_index),
        "common_first": common_first,
        "common_last": common_last,
        "common_fingerprint": common_fingerprint,
        "spot_excluded_rows": len(spot_raw) - len(common_index),
        "perp_excluded_rows": len(perp_raw) - len(common_index),
    }
    return AlignedOneMinuteFeed(spot), AlignedOneMinuteFeed(perp), audit
