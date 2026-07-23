import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from run_contract_strategy_comparison import (
    DEFAULT_DATABASE,
    assert_same_snapshot,
    benchmark_config,
    calculate_metrics,
    clip_period,
    parse_args,
    snapshot_identity,
    write_parquet,
)


class ContractStrategyComparisonTest(unittest.TestCase):
    def test_default_database_is_canonical_perpetual_snapshot(self):
        self.assertEqual(DEFAULT_DATABASE, Path("data/btcusdt_perp_1m_202101_present.duckdb"))

    def test_common_execution_config_is_frozen(self):
        config = benchmark_config(96)
        self.assertEqual(config.initial_balance, 10_000.0)
        self.assertEqual(config.risk_pct, 0.05)
        self.assertEqual(config.leverage, 20.0)
        self.assertEqual(config.maker_fee, 0.0002)
        self.assertEqual(config.taker_fee, 0.0005)
        self.assertEqual(config.max_holding_bars, 96)

    def test_metrics_and_empty_trades(self):
        trades = [
            {"exit_time": "2026-07-01", "entry_balance": 10_000.0, "pnl": 100.0},
            {"exit_time": "2026-07-02", "entry_balance": 10_100.0, "pnl": -40.0},
        ]
        result = calculate_metrics(trades, missed=3, initial_balance=10_000.0)
        self.assertEqual(result["return_pct"], 0.6)
        self.assertEqual(result["max_drawdown_pct"], -0.396)
        self.assertEqual(result["win_rate_pct"], 50.0)
        self.assertEqual(result["profit_factor"], 2.5)
        self.assertEqual(result["final_balance"], 10_060.0)
        self.assertEqual(result["missed"], 3)

        empty = calculate_metrics([], missed=2, initial_balance=10_000.0)
        self.assertEqual(empty["trades"], 0)
        self.assertEqual(empty["final_balance"], 10_000.0)
        self.assertIsNone(empty["profit_factor"])

    def test_headline_drawdown_uses_session_equity_events(self):
        trades = [{"exit_time": "2026-07-02", "entry_balance": 10_000.0, "pnl": 100.0}]
        events = [
            {"equity": 10_000.0},
            {"equity": 8_000.0},
            {"equity": 10_100.0},
        ]
        result = calculate_metrics(trades, missed=0, initial_balance=10_000.0, equity_events=events)
        self.assertEqual(result["max_drawdown_pct"], -20.0)

    def test_fidelity_is_default_and_research_is_explicit(self):
        with patch("sys.argv", ["comparison"]):
            self.assertEqual(parse_args().profile, "fidelity")
        self.assertEqual(parse_args(["--profile", "research"]).profile, "research")

    def test_duckdb_writes_parquet_without_optional_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.parquet"
            write_parquet([{"value": 1}], path)
            self.assertEqual(
                duckdb.sql("SELECT value FROM read_parquet(?)", params=[str(path)]).fetchone()[0], 1
            )

    def test_period_clipping(self):
        start, end = clip_period(
            pd.Timestamp("2021-01-01"),
            pd.Timestamp("2026-07-31"),
            pd.Timestamp("2022-01-01"),
            pd.Timestamp("2026-07-18"),
        )
        self.assertEqual(start, pd.Timestamp("2022-01-01"))
        self.assertEqual(end, pd.Timestamp("2026-07-18"))
        with self.assertRaises(ValueError):
            clip_period(
                pd.Timestamp("2026-07-01"),
                pd.Timestamp("2026-07-31"),
                pd.Timestamp("2025-01-01"),
                pd.Timestamp("2026-06-30"),
            )

    def test_snapshot_fingerprint_detects_change(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.duckdb"
            connection = duckdb.connect(str(database))
            connection.execute(
                """
                CREATE TABLE ohlcv_1m (
                    exchange VARCHAR, market_type VARCHAR, symbol VARCHAR, open_time TIMESTAMP,
                    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, ingested_at TIMESTAMP
                )
                """
            )
            row = ["binance", "swap", "BTC/USDT:USDT", "2026-07-01", 1, 1, 1, 1, 1, "2026-07-01"]
            connection.execute("INSERT INTO ohlcv_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            connection.close()
            first = snapshot_identity(database)
            self.assertEqual(first, snapshot_identity(database))

            connection = duckdb.connect(str(database))
            row[3] = "2026-07-01 00:01:00"
            connection.execute("INSERT INTO ohlcv_1m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            connection.close()
            second = snapshot_identity(database)
            self.assertNotEqual(first["fingerprint"], second["fingerprint"])
            with self.assertRaises(RuntimeError):
                assert_same_snapshot(first, second)


if __name__ == "__main__":
    unittest.main()
