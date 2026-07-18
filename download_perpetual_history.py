from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests


KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
TIME_URL = "https://fapi.binance.com/fapi/v1/time"
EXCHANGE = "binance"
MARKET_TYPE = "swap"
SYMBOL = "BTC/USDT:USDT"
API_SYMBOL = "BTCUSDT"
MINUTE_MS = 60_000
DEFAULT_START = "2021-01-01T00:00:00Z"
DEFAULT_DATABASE = "data/btcusdt_perp_1m_202101_present.duckdb"
DB_COLUMNS = [
    "exchange", "market_type", "symbol", "open_time", "open", "high", "low", "close", "volume", "ingested_at"
]


def ensure_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
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


def request_json(session: requests.Session, url: str, params=None, retries: int = 8):
    last_error = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
            time.sleep(float(retry_after) if retry_after else min(2**attempt, 30))
    raise last_error


def server_time_ms(session: requests.Session) -> int:
    return int(request_json(session, TIME_URL)["serverTime"])


def download_history(
    database_path: str | Path,
    start: str = DEFAULT_START,
    end: str | None = None,
    session: requests.Session | None = None,
    now_ms: int | None = None,
) -> int:
    session = session or requests.Session()
    now_ms = now_ms if now_ms is not None else server_time_ms(session)
    last_closed_open_ms = (now_ms // MINUTE_MS) * MINUTE_MS - MINUTE_MS
    if end is not None:
        last_closed_open_ms = min(
            last_closed_open_ms,
            int(pd.Timestamp(end).tz_convert("UTC").timestamp() * 1000),
        )

    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    ensure_schema(connection)
    latest = connection.execute(
        """
        SELECT max(open_time) FROM ohlcv_1m
        WHERE exchange = ? AND market_type = ? AND symbol = ?
        """,
        [EXCHANGE, MARKET_TYPE, SYMBOL],
    ).fetchone()[0]
    requested_start_ms = int(pd.Timestamp(start).tz_convert("UTC").timestamp() * 1000)
    cursor_ms = (
        int(pd.Timestamp(latest, tz="UTC").timestamp() * 1000) + MINUTE_MS
        if latest is not None
        else requested_start_ms
    )

    inserted = 0
    while cursor_ms <= last_closed_open_ms:
        rows = request_json(
            session,
            KLINES_URL,
            {
                "symbol": API_SYMBOL,
                "interval": "1m",
                "startTime": cursor_ms,
                "endTime": last_closed_open_ms + MINUTE_MS - 1,
                "limit": 1500,
            },
        )
        if not rows:
            break
        closed_rows = [row for row in rows if int(row[0]) <= last_closed_open_ms]
        ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
        records = [
            [
                EXCHANGE,
                MARKET_TYPE,
                SYMBOL,
                datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                *map(float, row[1:6]),
                ingested_at,
            ]
            for row in closed_rows
        ]
        if records:
            batch = pd.DataFrame(records, columns=DB_COLUMNS)
            connection.register("download_batch", batch)
            connection.execute("INSERT OR REPLACE INTO ohlcv_1m SELECT * FROM download_batch")
            connection.unregister("download_batch")
            inserted += len(records)
        next_cursor_ms = int(rows[-1][0]) + MINUTE_MS
        if next_cursor_ms <= cursor_ms:
            connection.close()
            raise RuntimeError("Binance pagination did not advance")
        cursor_ms = next_cursor_ms
        time.sleep(0.3)
        if inserted and inserted % 150_000 == 0:
            print(
                f"downloaded {inserted:,} rows; latest={pd.to_datetime(cursor_ms - MINUTE_MS, unit='ms')}",
                flush=True,
            )
    connection.close()
    return inserted


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_database(database_path: str | Path, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    last_closed_open = datetime.fromtimestamp(
        ((now_ms // MINUTE_MS) * MINUTE_MS - MINUTE_MS) / 1000,
        tz=timezone.utc,
    ).replace(tzinfo=None)
    connection = duckdb.connect(str(database_path), read_only=True)
    summary = connection.execute(
        """
        SELECT count(*) row_count, count(*) - count(DISTINCT open_time) duplicates,
               min(open_time) first_open, max(open_time) last_open
        FROM ohlcv_1m
        WHERE exchange = ? AND market_type = ? AND symbol = ?
        """,
        [EXCHANGE, MARKET_TYPE, SYMBOL],
    ).fetchone()
    gaps = connection.execute(
        """
        WITH ordered AS (
            SELECT open_time, lag(open_time) OVER (ORDER BY open_time) previous_open
            FROM ohlcv_1m
            WHERE exchange = ? AND market_type = ? AND symbol = ?
        )
        SELECT previous_open, open_time,
               date_diff('minute', previous_open, open_time) - 1 missing_minutes
        FROM ordered
        WHERE open_time - previous_open > INTERVAL 1 MINUTE
        ORDER BY open_time
        """,
        [EXCHANGE, MARKET_TYPE, SYMBOL],
    ).fetchall()
    connection.close()
    result = {
        "exchange": EXCHANGE,
        "market_type": MARKET_TYPE,
        "symbol": SYMBOL,
        "row_count": summary[0],
        "duplicates": summary[1],
        "first_open": str(summary[2]),
        "last_open": str(summary[3]),
        "gap_count": len(gaps),
        "missing_minutes": sum(row[2] for row in gaps),
        "gaps": [
            {"previous_open": str(row[0]), "next_open": str(row[1]), "missing_minutes": row[2]}
            for row in gaps
        ],
        "last_candle_closed": summary[3] is not None and summary[3] <= last_closed_open,
        "sha256": file_sha256(database_path),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Download closed Binance USD-M BTCUSDT 1m candles.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", help="Optional final candle open time in UTC")
    parser.add_argument("--audit", help="Audit JSON path; defaults beside the database")
    args = parser.parse_args()
    inserted = download_history(args.database, args.start, args.end)
    audit = audit_database(args.database)
    audit_path = Path(args.audit) if args.audit else Path(args.database).with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"inserted={inserted:,}")
    print(json.dumps(audit, indent=2))
    print(f"audit={audit_path.resolve()}")


if __name__ == "__main__":
    main()
