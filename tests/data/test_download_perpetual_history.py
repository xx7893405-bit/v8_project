import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from download_perpetual_history import (
    API_SYMBOL,
    KLINES_URL,
    audit_database,
    download_history,
    ensure_schema,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        start = params["startTime"]
        end = params["endTime"]
        return FakeResponse([row for row in self.rows if start <= row[0] <= end])


def row(open_time, close):
    open_ms = int(pd.Timestamp(open_time).tz_localize("UTC").timestamp() * 1000)
    return [open_ms, "1", "3", "0", str(close), "10", open_ms + 59_999]


class PerpetualHistoryDownloaderTest(unittest.TestCase):
    def test_uses_contract_endpoint_and_stores_only_closed_candles(self):
        rows = [row("2021-01-01 00:00:00", 1), row("2021-01-01 00:01:00", 2), row("2021-01-01 00:02:00", 3)]
        session = FakeSession(rows)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.duckdb"
            inserted = download_history(
                database,
                start="2021-01-01T00:00:00Z",
                session=session,
                now_ms=int(pd.Timestamp("2021-01-01 00:02:30", tz="UTC").timestamp() * 1000),
            )
            stored = duckdb.connect(str(database), read_only=True).execute(
                "SELECT open_time, close FROM ohlcv_1m ORDER BY open_time"
            ).fetchall()

        self.assertEqual(inserted, 2)
        self.assertEqual([value[1] for value in stored], [1.0, 2.0])
        self.assertEqual(session.calls[0][0], KLINES_URL)
        self.assertEqual(session.calls[0][1]["symbol"], API_SYMBOL)

    def test_audit_reports_gap_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.duckdb"
            connection = duckdb.connect(str(database))
            ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO ohlcv_1m VALUES
                ('binance', 'swap', 'BTC/USDT:USDT', '2021-01-01 00:00:00', 1, 2, 0, 1, 1, now()),
                ('binance', 'swap', 'BTC/USDT:USDT', '2021-01-01 00:02:00', 1, 2, 0, 1, 1, now())
                """
            )
            connection.close()

            audit = audit_database(
                database,
                now_ms=int(pd.Timestamp("2021-01-01 00:03:30", tz="UTC").timestamp() * 1000),
            )

        self.assertEqual(audit["duplicates"], 0)
        self.assertEqual(audit["gap_count"], 1)
        self.assertEqual(audit["missing_minutes"], 1)
        self.assertTrue(audit["last_candle_closed"])

    def test_resume_starts_after_latest_stored_open_time(self):
        rows = [row("2021-01-01 00:00:00", 1), row("2021-01-01 00:01:00", 2)]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.duckdb"
            first_session = FakeSession(rows)
            now_ms = int(pd.Timestamp("2021-01-01 00:02:30", tz="UTC").timestamp() * 1000)
            download_history(database, session=first_session, now_ms=now_ms)
            second_session = FakeSession(rows)
            inserted = download_history(database, session=second_session, now_ms=now_ms)
            connection = duckdb.connect(str(database), read_only=True)
            count = connection.execute("SELECT count(*) FROM ohlcv_1m").fetchone()[0]
            connection.close()

        self.assertEqual(inserted, 0)
        self.assertEqual(count, 2)
        self.assertEqual(second_session.calls, [])


if __name__ == "__main__":
    unittest.main()
