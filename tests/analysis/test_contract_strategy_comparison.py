import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pandas as pd

import run_contract_strategy_comparison as comparison
from research_viewer import RunCatalog
from run_artifacts import canonical_artifact_references
from run_contract_strategy_comparison import (
    DEFAULT_DATABASE,
    FIDELITY_UNSUPPORTED,
    MDD_WARNING,
    RESEARCH_WARNING,
    assert_same_snapshot,
    benchmark_config,
    calculate_metrics,
    clip_period,
    main,
    parse_args,
    snapshot_identity,
    validate_baseline,
    write_parquet,
    write_reports,
)


class ContractStrategyComparisonTest(unittest.TestCase):
    def test_equity_publisher_normalizes_raw_time_to_canonical_utc(self):
        row = {
            "strategy": "nfe_v2",
            "period": "full",
            "time": pd.Timestamp("2026-07-18 13:51:00"),
            "balance": 10_050.0,
            "equity": 10_025.0,
            "position_exposure": 0.25,
            "mark_source": "trade_price",
        }

        normalized = comparison._normalize_equity_row(row)

        self.assertEqual(
            normalized,
            {
                "strategy": "nfe_v2",
                "period": "full",
                "event_time": "2026-07-18T13:51:00+00:00",
                "balance": 10_050.0,
                "equity": 10_025.0,
                "position_exposure": 0.25,
                "mark_source": "trade_price",
            },
        )
        self.assertEqual(row["time"], pd.Timestamp("2026-07-18 13:51:00"))

        for invalid in (
            {key: value for key, value in row.items() if key != "time"},
            {**row, "event_time": "2026-07-18T13:51:00+00:00"},
            {**row, "time": "not-a-timestamp"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                comparison._normalize_equity_row(invalid)

    def test_trade_publisher_normalizes_lifecycle_to_canonical_utc(self):
        row = {
            "strategy": "nfe_v2",
            "period": "full",
            "entry_time": pd.Timestamp("2026-07-18 21:00:00+08:00"),
            "exit_time": pd.Timestamp("2026-07-18 14:00:00"),
            "type": "LONG",
            "pnl": 125.5,
            "fee": 4.25,
            "accumulated_funding": -0.75,
        }

        normalized = comparison._normalize_trade_row(row)

        self.assertEqual(
            normalized,
            {
                "strategy": "nfe_v2",
                "period": "full",
                "entry_time": "2026-07-18T13:00:00+00:00",
                "exit_time": "2026-07-18T14:00:00+00:00",
                "type": "LONG",
                "pnl": 125.5,
                "fee": 4.25,
                "accumulated_funding": -0.75,
            },
        )
        self.assertEqual(row["pnl"], 125.5)

        for invalid in (
            {key: value for key, value in row.items() if key != "entry_time"},
            {key: value for key, value in row.items() if key != "exit_time"},
            {**row, "entry_time": "not-a-timestamp"},
            {
                **row,
                "entry_time": "2026-07-18T15:00:00+00:00",
                "exit_time": "2026-07-18T14:00:00+00:00",
            },
            {**row, "event_time": "2026-07-18T13:00:00+00:00"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                comparison._normalize_trade_row(invalid)

    def test_published_rows_round_trip_through_run_catalog(self):
        class FixtureStrategy:
            def __init__(self, **kwargs):
                self.ltf = kwargs["ltf"]

            def signal_timeframe(self):
                return self.ltf

        trade = {
            "type": "LONG",
            "entry_time": pd.Timestamp("2026-07-18 13:00:00"),
            "exit_time": pd.Timestamp("2026-07-18 14:00:00"),
            "pnl": 125.5,
            "pnl_pct": 1.255,
            "result": "TAKE_PROFIT_ALL",
            "rr_potential": 3.25,
            "rr_realized": 1.5,
            "entry_price": 100_000.125,
            "exit_price": 101_000.875,
            "sl": 99_000.25,
            "tp1": 100_500.5,
            "tp2": 101_000.875,
            "size": 0.25,
            "entry_balance": 10_000.0,
            "fee": 4.25,
            "accumulated_funding": -0.75,
            "position_sizing_mode": "risk_based",
            "target_notional_usd": 25_000.25,
            "actual_notional_usd": 25_000.25,
            "leverage": 2.5,
            "initial_margin": 10_000.1,
            "maintenance_margin": 125.75,
            "liquidation_price": None,
            "be_active": True,
            "tp1_hit": True,
            "entry_mode": "LIMIT",
            "exit_model": "MICRO_1M",
        }
        equity_events = [
            {
                "time": pd.Timestamp("2026-07-18 13:00:00"),
                "balance": 10_000.0,
                "equity": 10_000.0,
                "position_exposure": 0.0,
                "mark_source": "trade_price",
            },
            {
                "time": pd.Timestamp("2026-07-18 21:30:00+08:00"),
                "balance": 10_000.0,
                "equity": 10_050.0,
                "position_exposure": 0.25,
                "mark_source": "trade_price",
            },
            {
                "time": pd.Timestamp("2026-07-18 14:00:00"),
                "balance": 10_125.5,
                "equity": 10_125.5,
                "position_exposure": 0.0,
                "mark_source": "realized_balance",
            },
        ]
        session = SimpleNamespace(
            trades=[trade],
            missed_trades=[],
            equity_events=equity_events,
            balance=10_125.5,
        )
        spec = {
            "name": "nfe_v2",
            "class": FixtureStrategy,
            "kwargs": {"ltf": "15m"},
            "max_holding_bars": 96,
        }
        identity = {"fingerprint": "fixture-snapshot"}
        with (
            patch("run_contract_strategy_comparison.DuckDBMarketDataFeed"),
            patch(
                "run_contract_strategy_comparison.MultiTimeframeBacktester"
            ) as backtester,
            patch(
                "run_contract_strategy_comparison.snapshot_identity",
                return_value=identity,
            ),
        ):
            backtester.return_value.run_session.return_value = session
            result, trades, equity, _ = comparison.run_period(
                spec,
                "full",
                pd.Timestamp("2026-07-18 13:00:00"),
                pd.Timestamp("2026-07-18 14:00:00"),
                Path("fixture.duckdb"),
                identity,
            )

        self.assertNotIn("time", equity[0])
        self.assertTrue(equity[0]["event_time"].endswith("+00:00"))
        self.assertTrue(trades[0]["entry_time"].endswith("+00:00"))
        self.assertTrue(trades[0]["exit_time"].endswith("+00:00"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "publisher-utc-fixture"
            run_dir = root / run_id
            run_dir.mkdir()
            write_parquet(equity, run_dir / "equity.parquet")
            write_parquet(trades, run_dir / "trades.parquet")

            provenance = {
                "strategy": {"name": "contract_strategy_comparison", "config_id": "fixture"},
                "data": {
                    "snapshot_id": "fixture-snapshot",
                    "content_sha256": "a" * 64,
                    "market_type": "swap",
                    "symbol": "BTC/USDT:USDT",
                },
                "git": {"revision": "037d7b2"},
                "period": {
                    "start": "2026-07-18T13:00:00+00:00",
                    "end": "2026-07-18T14:00:00+00:00",
                },
                "assumptions": {
                    "costs": {"maker_fee": 0.0002, "taker_fee": 0.0005},
                    "leverage": {"maximum": 20.0},
                },
            }
            artifacts = canonical_artifact_references()
            manifest = {
                "schema_version": "run-artifact/v1",
                "metrics_version": "metrics/v1",
                "run_id": run_id,
                "created_at": "2026-07-28T01:02:03+00:00",
                **provenance,
                "artifacts": artifacts,
            }
            summary = {
                "schema_version": "run-artifact/v1",
                "metrics_version": "metrics/v1",
                "run_id": run_id,
                "created_at": manifest["created_at"],
                "provenance": provenance,
                "verdict": "research_only",
                "profile": "research",
                "results": [
                    {
                        "strategy": "nfe_v2",
                        "period": "full",
                        "start": provenance["period"]["start"],
                        "end": provenance["period"]["end"],
                        "metrics": result["metrics"],
                        "baseline_deltas": {},
                    }
                ],
                "warnings": ["fixture only"],
                "artifacts": artifacts,
            }
            (run_dir / "manifest.json").write_text(json.dumps(manifest))
            (run_dir / "summary.json").write_text(json.dumps(summary))

            catalog = RunCatalog(root)
            loaded_equity = catalog.load_equity(
                run_id, strategy="nfe_v2", period="full", limit=2
            )
            loaded_trades = catalog.load_trades(
                run_id, strategy="nfe_v2", period="full", limit=1
            )

        self.assertEqual(
            loaded_equity["series"], {"strategy": "nfe_v2", "period": "full"}
        )
        self.assertEqual(loaded_equity["row_count"], 3)
        self.assertLessEqual(len(loaded_equity["rows"]), 2)
        self.assertTrue(
            all(row["event_time"].endswith("+00:00") for row in loaded_equity["rows"])
        )
        period_start = pd.Timestamp("2026-07-18T13:00:00+00:00")
        period_end = pd.Timestamp("2026-07-18T14:00:00+00:00")
        self.assertTrue(
            all(
                period_start <= pd.Timestamp(row["event_time"]) <= period_end
                for row in loaded_equity["rows"]
            )
        )
        self.assertEqual(
            loaded_trades["series"], {"strategy": "nfe_v2", "period": "full"}
        )
        self.assertEqual(loaded_trades["row_count"], result["metrics"]["trades"])
        self.assertLessEqual(len(loaded_trades["rows"]), 1)
        stored_trade = loaded_trades["rows"][0]
        self.assertEqual(stored_trade["entry_time"], "2026-07-18T13:00:00+00:00")
        self.assertEqual(stored_trade["exit_time"], "2026-07-18T14:00:00+00:00")
        self.assertGreaterEqual(pd.Timestamp(stored_trade["entry_time"]), period_start)
        self.assertLessEqual(pd.Timestamp(stored_trade["exit_time"]), period_end)
        self.assertEqual(stored_trade["pnl"], 125.5)
        self.assertEqual(stored_trade["fee"], 4.25)
        self.assertEqual(stored_trade["accumulated_funding"], -0.75)

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

    def test_main_rejects_unsafe_run_id_before_io_or_backtest(self):
        for run_id in ("../escape", "nested/run", r"nested\run"):
            with (
                self.subTest(run_id=run_id),
                patch("sys.argv", ["comparison", "--run-id", run_id]),
                patch("run_contract_strategy_comparison.verify_manifest") as verify,
                patch("run_contract_strategy_comparison.snapshot_identity") as snapshot,
                patch("run_contract_strategy_comparison.run_period") as run,
            ):
                with self.assertRaisesRegex(ValueError, "run_id"):
                    main()
                verify.assert_not_called()
                snapshot.assert_not_called()
                run.assert_not_called()

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

    def test_baseline_identity_hashes_exact_bytes_and_is_portable(self):
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
            "full": (
                pd.Timestamp("2021-01-01"),
                pd.Timestamp("2026-07-18 13:51:00"),
            ),
            "mtd_2026_07": (
                pd.Timestamp("2026-07-01"),
                pd.Timestamp("2026-07-18 13:51:00"),
            ),
        }
        config = benchmark_config(96)
        baseline = {
            "run_id": "baseline-run-001",
            "generated_at": "2026-07-18T13:51:00+00:00",
            "snapshot": snapshot,
            "periods": {
                name: {"start": str(bounds[0]), "end": str(bounds[1])}
                for name, bounds in periods.items()
            },
            "results": [
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
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            baseline_directory = Path(directory) / "legacy-baseline"
            baseline_directory.mkdir()
            path = baseline_directory / "summary.json"
            baseline_bytes = json.dumps(baseline).encode()
            path.write_bytes(baseline_bytes)
            loaded, identity = validate_baseline(path, snapshot, periods)
            self.assertEqual(loaded, baseline)
            self.assertEqual(
                identity,
                {
                    "run_id": "baseline-run-001",
                    "content_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
                    "generated_at": "2026-07-18T13:51:00+00:00",
                    "snapshot_id": "frozen",
                },
            )

            legacy = json.loads(json.dumps(baseline))
            legacy.pop("run_id")
            legacy_bytes = json.dumps(legacy).encode()
            path.write_bytes(legacy_bytes)
            self.assertEqual(
                validate_baseline(path, snapshot, periods)[1],
                {
                    "run_id": "legacy-baseline",
                    "content_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
                    "generated_at": "2026-07-18T13:51:00+00:00",
                    "snapshot_id": "frozen",
                },
            )

    def test_duckdb_writes_parquet_without_optional_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.parquet"
            write_parquet([{"value": 1}], path)
            self.assertEqual(
                duckdb.sql("SELECT value FROM read_parquet(?)", params=[str(path)]).fetchone()[0], 1
            )

    def test_write_reports_emits_frozen_portable_artifact_bundle(self):
        artifacts = {
            "manifest": {"available": True, "path": "manifest.json"},
            "summary": {"available": True, "path": "summary.json"},
            "summary_markdown": {"available": True, "path": "summary.md"},
            "review": {"available": True, "path": "review.md"},
            "trades": {"available": True, "path": "trades.parquet"},
            "equity": {"available": True, "path": "equity.parquet"},
            "diagnostics": {"available": True, "path": "diagnostics.parquet"},
            "log": {"available": True, "path": "run.log"},
            "orders": {"available": False, "path": None, "reason": "not produced"},
        }
        provenance = {
            "strategy": {
                "name": "contract_strategy_comparison",
                "config_id": "sha256:fixture",
            },
            "data": {
                "snapshot_id": "snapshot-fixture",
                "content_sha256": "a" * 64,
                "market_type": "swap",
                "symbol": "BTC/USDT:USDT",
            },
            "git": {"revision": "a6dfe16"},
            "period": {
                "start": "2021-01-01T00:00:00+00:00",
                "end": "2026-07-18T13:51:00+00:00",
            },
            "assumptions": {
                "costs": {"maker_fee": 0.0002, "taker_fee": 0.0005},
                "leverage": {"risk_pct": 0.05, "max_leverage": 20.0},
            },
        }
        metrics = {
            "return_pct": 12.5,
            "max_drawdown_pct": -8.25,
            "trades": 42,
            "win_rate_pct": 45.24,
            "profit_factor": 1.4,
            "final_balance": 11_250.0,
            "missed": 3,
        }
        baseline_metrics = {**metrics, "return_pct": 10.0}
        manifest = {
            "schema_version": "run-artifact/v1",
            "metrics_version": "metrics/v1",
            "run_id": "run-001",
            "created_at": "2026-07-28T01:02:03+00:00",
            **provenance,
            "artifacts": artifacts,
            "profile": "research",
        }

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "run-001"
            output_dir.mkdir()
            write_reports(
                [
                    {
                        "strategy": "nfe_v2",
                        "period": "full",
                        "start": "2021-01-01T00:00:00+00:00",
                        "end": "2026-07-18T13:51:00+00:00",
                        "metrics": metrics,
                    }
                ],
                [{"trade_id": 1}],
                [{"equity": 10_000.0}],
                [{"status": "ok"}],
                manifest,
                {
                    "results": [
                        {
                            "strategy": "nfe_v2",
                            "period": "full",
                            "metrics": baseline_metrics,
                        }
                    ]
                },
                {
                    "run_id": "baseline-run-001",
                    "content_sha256": "b" * 64,
                    "generated_at": "2026-07-18T13:51:00+00:00",
                    "snapshot_id": "snapshot-fixture",
                },
                output_dir,
            )

            written_manifest = json.loads((output_dir / "manifest.json").read_text())
            summary = json.loads((output_dir / "summary.json").read_text())
            self.assertEqual(written_manifest["artifacts"], artifacts)
            self.assertEqual(
                summary["provenance"],
                {
                    key: provenance[key]
                    for key in ("strategy", "data", "git", "period", "assumptions")
                },
            )
            self.assertEqual(summary["artifacts"], artifacts)
            self.assertEqual(summary["created_at"], manifest["created_at"])
            self.assertEqual(summary["results"][0]["metrics"], metrics)
            self.assertEqual(
                {
                    key: summary["results"][0][key]
                    for key in ("period", "start", "end")
                },
                {
                    "period": "full",
                    "start": "2021-01-01T00:00:00+00:00",
                    "end": "2026-07-18T13:51:00+00:00",
                },
            )
            self.assertEqual(
                summary["results"][0]["baseline_deltas"],
                {
                    "return_pct": 2.5,
                    "max_drawdown_pct": 0.0,
                    "trades": 0,
                    "win_rate_pct": 0.0,
                    "profit_factor": 0.0,
                    "final_balance": 0.0,
                },
            )
            self.assertNotIn("trade_id", json.dumps(summary))
            self.assertFalse(summary["artifacts"]["orders"]["available"])
            self.assertEqual(
                (output_dir / "summary.md").read_text(),
                "# Run summary\n\n"
                "Run ID: `run-001`\n\n"
                "| Strategy | Period | Return % | MDD % | Trades | Win rate % | "
                "Profit factor | Final balance |\n"
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n"
                "| nfe_v2 | full | 12.5 | -8.25 | 42 | 45.24 | 1.4 | 11250.0 |\n"
                "\n## Warnings\n\n"
                f"- {RESEARCH_WARNING}\n"
                f"- {MDD_WARNING}\n",
            )
            self.assertEqual(
                (output_dir / "review.md").read_text(),
                "# Review\n\n"
                "Run ID: `run-001`\n\n"
                "Verdict: **research_only**.\n"
                "\n## Warnings\n\n"
                f"- {RESEARCH_WARNING}\n"
                f"- {MDD_WARNING}\n",
            )

    def test_main_creates_an_immutable_versioned_run_directory(self):
        metrics = {
            "return_pct": 1.25,
            "max_drawdown_pct": -2.5,
            "trades": 4,
            "win_rate_pct": 50.0,
            "profit_factor": 1.5,
            "final_balance": 10_125.0,
            "missed": 0,
        }
        identity = {
            "first_open_time": "2021-01-01 00:00:00",
            "last_open_time": "2026-07-18 13:51:00",
            "fingerprint": "snapshot-fixture",
        }
        baseline = {
            "results": [
                {"strategy": "nfe_v2", "period": period, "metrics": metrics}
                for period in ("full", "mtd_2026_07")
            ]
        }
        spec = {
            "name": "nfe_v2",
            "class": object,
            "kwargs": {"ltf": "15m"},
            "max_holding_bars": 96,
        }

        def fixture_run_period(spec, period, start, end, database, snapshot):
            return (
                {
                    "strategy": spec["name"],
                    "period": period,
                    "start": str(start),
                    "end": str(end),
                    "metrics": metrics,
                },
                [{"period": period, "pnl": 1.0}],
                [{"period": period, "equity": 10_000.0}],
                [{"period": period, "status": "ok"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.json"
            baseline_path.write_text("{}")
            argv = [
                "comparison",
                "--database",
                str(root / "market.duckdb"),
                "--manifest",
                str(root / "data-manifest.json"),
                "--baseline",
                str(baseline_path),
                "--output-root",
                str(root),
                "--run-id",
                "run-immutable",
                "--profile",
                "research",
            ]
            with (
                patch("sys.argv", argv),
                patch(
                    "run_contract_strategy_comparison.verify_manifest",
                    return_value={"sha256": "a" * 64},
                ),
                patch(
                    "run_contract_strategy_comparison.snapshot_identity",
                    return_value=identity,
                ),
                patch(
                    "run_contract_strategy_comparison.validate_baseline",
                    return_value=(
                        baseline,
                        {
                            "run_id": "baseline-run-001",
                            "content_sha256": "b" * 64,
                            "generated_at": "2026-07-18T13:51:00+00:00",
                            "snapshot_id": "snapshot-fixture",
                        },
                    ),
                ),
                patch(
                    "run_contract_strategy_comparison.strategy_specs",
                    return_value=[spec],
                ),
                patch(
                    "run_contract_strategy_comparison.run_period",
                    side_effect=fixture_run_period,
                ) as run,
                patch(
                    "run_contract_strategy_comparison.git_identity",
                    return_value={"commit": "a6dfe16", "dirty": False},
                ),
                patch("builtins.print"),
            ):
                main()
                with self.assertRaises(FileExistsError):
                    main()

            manifest = json.loads(
                (root / "run-immutable" / "manifest.json").read_text()
            )
            summary = json.loads(
                (root / "run-immutable" / "summary.json").read_text()
            )
            self.assertEqual(manifest["schema_version"], "run-artifact/v1")
            self.assertEqual(manifest["metrics_version"], "metrics/v1")
            self.assertEqual(
                manifest["strategy"]["name"], "contract_strategy_comparison"
            )
            self.assertEqual(
                manifest["data"],
                {
                    "snapshot_id": "snapshot-fixture",
                    "content_sha256": "a" * 64,
                    "market_type": "swap",
                    "symbol": "BTC/USDT:USDT",
                },
            )
            self.assertEqual(manifest["git"]["revision"], "a6dfe16")
            self.assertEqual(
                manifest["period"],
                {
                    "start": "2021-01-01T00:00:00+00:00",
                    "end": "2026-07-18T13:51:00+00:00",
                },
            )
            self.assertEqual(
                summary["provenance"],
                {
                    key: manifest[key]
                    for key in ("strategy", "data", "git", "period", "assumptions")
                },
            )
            self.assertIsNone(manifest["random_seed"])
            self.assertEqual(
                summary["results"][0]["metrics"],
                metrics,
            )
            self.assertEqual(run.call_count, 2)

    def test_main_cleans_failed_staging_and_allows_same_run_id_retry(self):
        metrics = {
            "return_pct": 1.25,
            "max_drawdown_pct": -2.5,
            "trades": 4,
            "win_rate_pct": 50.0,
            "profit_factor": 1.5,
            "final_balance": 10_125.0,
            "missed": 0,
        }
        identity = {
            "first_open_time": "2021-01-01 00:00:00",
            "last_open_time": "2026-07-18 13:51:00",
            "fingerprint": "snapshot-fixture",
        }
        baseline = {
            "results": [
                {"strategy": "nfe_v2", "period": period, "metrics": metrics}
                for period in ("full", "mtd_2026_07")
            ]
        }
        spec = {
            "name": "nfe_v2",
            "class": object,
            "kwargs": {"ltf": "15m"},
            "max_holding_bars": 96,
        }

        def fixture_run_period(spec, period, start, end, database, snapshot):
            return (
                {
                    "strategy": spec["name"],
                    "period": period,
                    "start": str(start),
                    "end": str(end),
                    "metrics": metrics,
                },
                [{"period": period, "pnl": 1.0}],
                [{"period": period, "equity": 10_000.0}],
                [{"period": period, "status": "ok"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = root / "runs"
            baseline_path = root / "baseline.json"
            baseline_path.write_text("{}")
            argv = [
                "comparison",
                "--database",
                str(root / "market.duckdb"),
                "--manifest",
                str(root / "data-manifest.json"),
                "--baseline",
                str(baseline_path),
                "--output-root",
                str(output_root),
                "--run-id",
                "run-retry",
                "--profile",
                "research",
            ]
            with (
                patch("sys.argv", argv),
                patch(
                    "run_contract_strategy_comparison.verify_manifest",
                    return_value={"sha256": "a" * 64},
                ),
                patch(
                    "run_contract_strategy_comparison.snapshot_identity",
                    return_value=identity,
                ),
                patch(
                    "run_contract_strategy_comparison.validate_baseline",
                    return_value=(
                        baseline,
                        {
                            "run_id": "baseline-run-001",
                            "content_sha256": "b" * 64,
                            "snapshot_id": "snapshot-fixture",
                        },
                    ),
                ),
                patch(
                    "run_contract_strategy_comparison.strategy_specs",
                    return_value=[spec],
                ),
                patch(
                    "run_contract_strategy_comparison.run_period",
                    side_effect=fixture_run_period,
                ),
                patch(
                    "run_contract_strategy_comparison.git_identity",
                    return_value={"commit": "a6dfe16", "dirty": False},
                ),
                patch("builtins.print"),
            ):
                with (
                    patch(
                        "run_contract_strategy_comparison.write_parquet",
                        side_effect=RuntimeError("fixture write failure"),
                    ),
                    self.assertRaisesRegex(RuntimeError, "fixture write failure"),
                ):
                    main()

                self.assertFalse((output_root / "run-retry").exists())
                self.assertEqual(list(output_root.iterdir()), [])

                started = Event()
                release = Event()
                run_calls = []
                writer_errors = []

                def blocking_run_period(*args):
                    run_calls.append(args[1])
                    if len(run_calls) == 1:
                        started.set()
                        if not release.wait(5):
                            raise TimeoutError("fixture writer was not released")
                    return fixture_run_period(*args)

                def run_writer():
                    try:
                        main()
                    except BaseException as error:
                        writer_errors.append(error)

                with patch(
                    "run_contract_strategy_comparison.run_period",
                    side_effect=blocking_run_period,
                ):
                    writer = Thread(target=run_writer)
                    writer.start()
                    self.assertTrue(started.wait(5))
                    try:
                        with self.assertRaises(FileExistsError):
                            main()
                        self.assertEqual(run_calls, ["full"])
                    finally:
                        release.set()
                        writer.join(5)

                self.assertFalse(writer.is_alive())
                self.assertEqual(writer_errors, [])

            self.assertTrue((output_root / "run-retry" / "summary.json").is_file())

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
