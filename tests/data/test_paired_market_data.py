import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from paired_market_data import OHLCV_COLUMNS, load_aligned_market_feeds


class PairedMarketDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.spot = root / "spot.csv"
        self.perp = root / "perp.duckdb"

        minutes = pd.date_range("2026-01-01 00:00", periods=17, freq="1min")
        # Spot lacks 00:06; its duplicate 00:02 deterministically keeps the last row.
        spot_times = list(minutes.delete(6)) + [minutes[2]]
        spot = self._rows(spot_times, offset=0)
        spot.loc[len(spot) - 1, OHLCV_COLUMNS] = [99.0, 100.0, 98.0, 99.5, 999.0]
        spot.to_csv(self.spot, index=False)

        connection = duckdb.connect(str(self.perp))
        connection.execute(
            """
            CREATE TABLE ohlcv_1m (
                exchange VARCHAR, market_type VARCHAR, symbol VARCHAR,
                open_time TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE,
                close DOUBLE, volume DOUBLE, ingested_at TIMESTAMP
            )
            """
        )
        perp = self._rows(list(minutes) + [minutes[2]], offset=100)
        for position, row in perp.iterrows():
            values = row[OHLCV_COLUMNS].tolist()
            if position == len(perp) - 1:
                values = [199, 200, 198, 199.5, 1999]
            connection.execute(
                "INSERT INTO ohlcv_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "binance", "swap", "BTC/USDT:USDT", row["datetime"],
                    *values, pd.Timestamp("2026-01-01") + pd.Timedelta(seconds=position),
                ],
            )
        # Non-canonical rows must never enter the paired feed.
        connection.execute(
            "INSERT INTO ohlcv_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["binance", "spot", "BTC/USDT", minutes[0], 1, 1, 1, 1, 1, minutes[0]],
        )
        connection.close()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _rows(times, offset):
        values = [float(value) for value in range(len(times))]
        return pd.DataFrame(
            {
                "datetime": times,
                "open": [offset + value for value in values],
                "high": [offset + value + 2 for value in values],
                "low": [offset + value - 1 for value in values],
                "close": [offset + value + 1 for value in values],
                "volume": [value + 1 for value in values],
            }
        )

    def test_exact_intersection_duplicate_normalization_and_audit(self):
        spot, perp, audit = load_aligned_market_feeds(self.spot, self.perp)
        spot_1m = spot.load_timeframe("1m")
        perp_1m = perp.load_timeframe("1m")

        self.assertTrue(spot_1m.index.equals(perp_1m.index))
        self.assertEqual(len(spot_1m), 16)
        self.assertNotIn(pd.Timestamp("2026-01-01 00:06"), spot_1m.index)
        self.assertEqual(spot_1m.loc["2026-01-01 00:02", "open"], 99)
        self.assertEqual(perp_1m.loc["2026-01-01 00:02", "open"], 199)
        self.assertEqual(audit["spot"]["duplicates"], 1)
        self.assertEqual(audit["spot"]["missing"], 1)
        self.assertEqual(audit["perp"]["duplicates"], 1)
        self.assertEqual(audit["perp"]["missing"], 0)
        self.assertEqual(audit["common_rows"], 16)
        self.assertEqual(audit["common_first"], "2026-01-01T00:00:00")
        self.assertEqual(audit["common_last"], "2026-01-01T00:16:00")
        self.assertEqual(audit["common_fingerprint"], audit["common"]["fingerprint"])
        self.assertEqual(audit["spot_excluded_rows"], 0)
        self.assertEqual(audit["perp_excluded_rows"], 1)
        self.assertEqual(audit, load_aligned_market_feeds(self.spot, self.perp)[2])

    def test_incomplete_and_last_partial_bars_are_dropped_for_both_feeds(self):
        spot, perp, _ = load_aligned_market_feeds(self.spot, self.perp)

        for timeframe in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            spot_frame = spot.load_timeframe(timeframe)
            perp_frame = perp.load_timeframe(timeframe)
            self.assertTrue(spot_frame.index.equals(perp_frame.index), timeframe)

        expected_5m = pd.DatetimeIndex(
            [pd.Timestamp("2026-01-01 00:00"), pd.Timestamp("2026-01-01 00:10")]
        )
        self.assertTrue(spot.load_timeframe("5m").index.equals(expected_5m))
        self.assertTrue(spot.load_timeframe("15m").empty)

    def test_micro_slice_is_inclusive_and_results_are_copies(self):
        spot, _, _ = load_aligned_market_feeds(self.spot, self.perp)
        original_csv = self.spot.read_bytes()
        window = spot.load_micro_window(
            pd.Timestamp("2026-01-01 00:01", tz="UTC"),
            pd.Timestamp("2026-01-01 00:03", tz="UTC"),
            ["close"],
        )
        self.assertEqual(len(window), 3)
        window.iloc[0, 0] = -1
        one_minute = spot.load_timeframe("1m")
        one_minute.iloc[0, 0] = -2
        self.assertNotEqual(spot.load_timeframe("1m").iloc[0, 0], -2)
        self.assertNotEqual(
            spot.load_micro_window(
                pd.Timestamp("2026-01-01 00:01"),
                pd.Timestamp("2026-01-01 00:01"),
                ["close"],
            ).iloc[0, 0],
            -1,
        )
        self.assertEqual(self.spot.read_bytes(), original_csv)


if __name__ == "__main__":
    unittest.main()
