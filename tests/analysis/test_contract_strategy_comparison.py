import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd

from run_contract_strategy_comparison import (
    DEFAULT_DATABASE,
    FIDELITY_UNSUPPORTED,
    assert_same_snapshot,
    benchmark_config,
    calculate_metrics,
    clip_period,
    parse_args,
    snapshot_identity,
    validate_baseline,
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

    def test_fidelity_fails_when_coverage_exists_but_engine_consumption_is_unsupported(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("run_contract_strategy_comparison.verify_manifest", return_value={}),
            patch(
                "run_contract_strategy_comparison.snapshot_identity",
                return_value={
                    "first_open_time": "2021-01-01",
                    "last_open_time": "2026-07-18 13:51:00",
                },
            ),
            patch("run_contract_strategy_comparison.require_fidelity_data", return_value={"complete": True}),
            patch(
                "sys.argv",
                [
                    "comparison",
                    "--database",
                    str(Path(directory) / "market.duckdb"),
                    "--output-root",
                    directory,
                    "--run-id",
                    "must-not-exist",
                ],
            ),
        ):
            from run_contract_strategy_comparison import main

            with self.assertRaisesRegex(RuntimeError, FIDELITY_UNSUPPORTED):
                main()
            self.assertFalse((Path(directory) / "must-not-exist").exists())

    def test_baseline_identity_and_assumptions_are_required(self):
        snapshot = {
            "exchange": "binance",
            "market_type": "swap",
            "symbol": "BTC/USDT:USDT",
            "rows": 2,
            "first_open_time": "2021-01-01 00:00:00",
            "last_open_time": "2026-07-18 13:51:00",
            "file_size": 10,
            "file_mtime_ns": 20,
            "fingerprint": "frozen",
        }
        periods = {
            "full": (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-07-18 13:51:00")),
            "mtd_2026_07": (pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-18 13:51:00")),
        }
        config = benchmark_config(96)
        rows = [
            {
                "strategy": strategy,
                "period": period,
                "start": str(bounds[0]),
                "end": str(bounds[1]),
                "backtest_config": {
                    key: getattr(config, key)
                    for key in (
                        "risk_pct",
                        "leverage",
                        "maker_fee",
                        "taker_fee",
                        "slippage_usd",
                        "limit_order_slippage_usd",
                        "stop_loss_slippage_usd",
                        "funding_rate_8h",
                    )
                },
            }
            for strategy in ("nfe_v2", "nfe_v2_a", "bears")
            for period, bounds in periods.items()
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            baseline = {"generated_at": "now", "snapshot": snapshot, "periods": {
                name: {"start": str(bounds[0]), "end": str(bounds[1])}
                for name, bounds in periods.items()
            }, "results": rows}
            path.write_text(json.dumps(baseline))
            self.assertEqual(validate_baseline(path, snapshot, periods)[0], baseline)

            for mutation, message in (
                (lambda value: value["snapshot"].pop("fingerprint"), "identity is incomplete"),
                (lambda value: value["periods"]["full"].update(end="bad"), "periods"),
                (lambda value: value["results"][0]["backtest_config"].update(maker_fee=0), "maker_fee"),
            ):
                changed = json.loads(json.dumps(baseline))
                mutation(changed)
                path.write_text(json.dumps(changed))
                with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                    validate_baseline(path, snapshot, periods)

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
