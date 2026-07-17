import tempfile
import unittest
from pathlib import Path

import pandas as pd

from market_data import CSVMarketDataFeed


class CSVMarketDataFeedContractTest(unittest.TestCase):
    def test_timeframe_is_sorted_and_projects_requested_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame(
                {
                    "datetime": ["2026-01-01 00:15:00", "2026-01-01 00:00:00"],
                    "open": [2.0, 1.0],
                    "high": [3.0, 2.0],
                    "low": [1.0, 0.5],
                    "close": [2.5, 1.5],
                }
            ).to_csv(Path(directory) / "tiny_15m.csv", index=False)

            result = CSVMarketDataFeed(
                data_dir=directory,
                timeframe_files={"15m": "tiny_15m.csv"},
            ).load_timeframe("15m", columns=["close", "open"])

            self.assertEqual(list(result.columns), ["close", "open"])
            self.assertEqual(
                list(result.index),
                [pd.Timestamp("2026-01-01 00:00:00"), pd.Timestamp("2026-01-01 00:15:00")],
            )
            self.assertEqual(result["open"].tolist(), [1.0, 2.0])

    def test_micro_window_is_time_bounded_and_projects_requested_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame(
                {
                    "datetime": [
                        "2026-01-01 00:02:00",
                        "2026-01-01 00:00:00",
                        "2026-01-01 00:01:00",
                    ],
                    "open": [3.0, 1.0, 2.0],
                    "high": [4.0, 2.0, 3.0],
                    "low": [2.0, 0.0, 1.0],
                }
            ).to_csv(Path(directory) / "tiny_1m.csv", index=False)

            result = CSVMarketDataFeed(
                data_dir=directory,
                micro_filename="tiny_1m.csv",
            ).load_micro_window(
                pd.Timestamp("2026-01-01 00:01:00"),
                pd.Timestamp("2026-01-01 00:02:00"),
                columns=["high", "low"],
            )

            self.assertEqual(list(result.columns), ["high", "low"])
            self.assertEqual(
                list(result.index),
                [pd.Timestamp("2026-01-01 00:01:00"), pd.Timestamp("2026-01-01 00:02:00")],
            )
            self.assertEqual(result["high"].tolist(), [3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
