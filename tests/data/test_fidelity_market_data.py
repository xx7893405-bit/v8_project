import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from ccxt_market_data import (
    CcxtOHLCVSync,
    FidelityDataUnavailableError,
    ensure_fidelity_schema,
    require_fidelity_data,
)


class FidelityMarketDataTest(unittest.TestCase):
    def test_normal_ohlcv_schema_does_not_create_fidelity_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            sync = CcxtOHLCVSync.__new__(CcxtOHLCVSync)
            sync.connection = duckdb.connect(str(Path(directory) / "market.duckdb"))

            sync._ensure_schema()
            tables = {row[0] for row in sync.connection.execute("SHOW TABLES").fetchall()}
            sync.connection.close()

            self.assertEqual(tables, {"ohlcv_1m"})

    def test_absent_series_fail_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            connection = duckdb.connect(str(database))
            ensure_fidelity_schema(connection)
            for timestamp in pd.date_range("2026-01-01 00:00", periods=2, freq="1min"):
                connection.execute(
                    "INSERT INTO mark_price_1m VALUES ('binance','swap','BTC/USDT:USDT',?,1,2,.5,1,now())",
                    [timestamp],
                )
            connection.close()

            with self.assertRaisesRegex(FidelityDataUnavailableError, "funding-rate series is absent"):
                require_fidelity_data(database, "2026-01-01 00:00", "2026-01-01 00:01")

    def test_complete_mark_and_funding_ranges_return_compact_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            connection = duckdb.connect(str(database))
            ensure_fidelity_schema(connection)
            for timestamp in pd.date_range("2026-01-01 00:00", periods=2, freq="1min"):
                connection.execute(
                    "INSERT INTO mark_price_1m VALUES ('binance','swap','BTC/USDT:USDT',?,1,2,.5,1,now())",
                    [timestamp],
                )
            connection.execute(
                "INSERT INTO funding_rate VALUES ('binance','swap','BTC/USDT:USDT','2026-01-01 00:00',.0001,now())"
            )
            connection.close()

            coverage = require_fidelity_data(database, "2026-01-01 00:00", "2026-01-01 00:01")

            self.assertEqual(coverage["mark_price_rows"], 2)
            self.assertEqual(coverage["funding_rows"], 1)


if __name__ == "__main__":
    unittest.main()
