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
EXPECTED_SCHEMA = {
    "exchange": ("VARCHAR", True),
    "market_type": ("VARCHAR", True),
    "symbol": ("VARCHAR", True),
    "open_time": ("TIMESTAMP", True),
    "open": ("DOUBLE", True),
    "high": ("DOUBLE", True),
    "low": ("DOUBLE", True),
    "close": ("DOUBLE", True),
    "volume": ("DOUBLE", True),
    "ingested_at": ("TIMESTAMP", True),
}


class DataIntegrityError(RuntimeError):
    """The local snapshot cannot safely be used for a backtest."""


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
    database_path = Path(database_path)
    if not database_path.is_file():
        raise DataIntegrityError(f"database does not exist: {database_path}")
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    last_closed_open = datetime.fromtimestamp(
        ((now_ms // MINUTE_MS) * MINUTE_MS - MINUTE_MS) / 1000,
        tz=timezone.utc,
    ).replace(tzinfo=None)
    sha_before = file_sha256(database_path)
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        schema_rows = connection.execute("PRAGMA table_info('ohlcv_1m')").fetchall()
        schema = {row[1]: (row[2], bool(row[3])) for row in schema_rows}
        schema_valid = schema == EXPECTED_SCHEMA
        summary = connection.execute(
        """
        SELECT count(*) row_count, count(*) - count(DISTINCT open_time) duplicates,
               min(open_time) first_open, max(open_time) last_open,
               count(*) FILTER (WHERE exchange <> ? OR market_type <> ? OR symbol <> ?) noncanonical_rows,
               count(*) FILTER (WHERE epoch_ms(open_time) % ? <> 0) off_grid_rows,
               count(*) FILTER (WHERE NOT isfinite(open) OR NOT isfinite(high)
                    OR NOT isfinite(low) OR NOT isfinite(close) OR NOT isfinite(volume)
                    OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR volume < 0
                    OR high < greatest(open, close, low) OR low > least(open, close, high)) invalid_ohlcv_rows,
               count(*) FILTER (WHERE open_time > ?) unclosed_rows,
               count(*) FILTER (WHERE ingested_at < open_time + INTERVAL 1 MINUTE) prematurely_ingested_rows
        FROM ohlcv_1m
        """,
        [EXCHANGE, MARKET_TYPE, SYMBOL, MINUTE_MS, last_closed_open],
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
    except duckdb.Error as exc:
        raise DataIntegrityError("database schema or contents are unreadable") from exc
    finally:
        if "connection" in locals():
            connection.close()
    sha_after = file_sha256(database_path)
    if sha_before != sha_after:
        raise DataIntegrityError("database changed during read-only audit")
    result = {
        "exchange": EXCHANGE,
        "market_type": MARKET_TYPE,
        "symbol": SYMBOL,
        "row_count": summary[0],
        "duplicates": summary[1],
        "first_open": str(summary[2]),
        "last_open": str(summary[3]),
        "schema_valid": schema_valid,
        "noncanonical_rows": summary[4],
        "off_grid_rows": summary[5],
        "invalid_ohlcv_rows": summary[6],
        "unclosed_rows": summary[7],
        "prematurely_ingested_rows": summary[8],
        "gap_count": len(gaps),
        "missing_minutes": sum(row[2] for row in gaps),
        "gaps": [
            {"previous_open": str(row[0]), "next_open": str(row[1]), "missing_minutes": row[2]}
            for row in gaps
        ],
        "last_candle_closed": summary[3] is not None and summary[7] == 0,
        "sha256": sha_after,
    }
    return result


def require_database_integrity(audit: dict) -> dict:
    failures = [
        key
        for key in (
            "duplicates",
            "gap_count",
            "missing_minutes",
            "noncanonical_rows",
            "off_grid_rows",
            "invalid_ohlcv_rows",
            "unclosed_rows",
            "prematurely_ingested_rows",
        )
        if audit.get(key)
    ]
    if not audit.get("schema_valid"):
        failures.append("schema")
    if not audit.get("row_count"):
        failures.append("empty")
    if not audit.get("last_candle_closed"):
        failures.append("last_candle_closed")
    if failures:
        raise DataIntegrityError("database integrity check failed: " + ", ".join(failures))
    return audit


def verify_manifest(database_path: str | Path, manifest_path: str | Path) -> dict:
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataIntegrityError(f"manifest is unreadable: {manifest_path}") from exc
    audit = require_database_integrity(audit_database(database_path))
    expected = {
        "exchange": EXCHANGE,
        "market_type": MARKET_TYPE,
        "symbol": SYMBOL,
        "interval": "1m",
        "closed_candles_only": True,
        "row_count": audit["row_count"],
        "first_open_utc": audit["first_open"],
        "last_open_utc": audit["last_open"],
        "sha256": audit["sha256"],
    }
    mismatches = [key for key, value in expected.items() if manifest.get(key) != value]
    if mismatches:
        raise DataIntegrityError("manifest mismatch: " + ", ".join(mismatches))
    return {
        "sha256": audit["sha256"],
        "rows": audit["row_count"],
        "first": audit["first_open"],
        "last": audit["last_open"],
        "market": {"exchange": EXCHANGE, "market_type": MARKET_TYPE, "symbol": SYMBOL, "interval": "1m"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download closed Binance USD-M BTCUSDT 1m candles.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", help="Optional final candle open time in UTC")
    parser.add_argument("--audit", action="store_true", help="Audit only; never download or write")
    parser.add_argument("--manifest", help="Manifest to verify during a read-only audit")
    args = parser.parse_args()
    if args.audit:
        result = (
            verify_manifest(args.database, args.manifest)
            if args.manifest
            else require_database_integrity(audit_database(args.database))
        )
        print(json.dumps(result, indent=2))
        return
    inserted = download_history(args.database, args.start, args.end)
    audit = audit_database(args.database)
    database_path = Path(args.database)
    audit_path = (
        database_path.with_name(f"{database_path.stem}_diagnostic.json")
    )
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"inserted={inserted:,}")
    print(json.dumps(audit, indent=2))
    print(f"audit={audit_path.resolve()}")


if __name__ == "__main__":
    main()
