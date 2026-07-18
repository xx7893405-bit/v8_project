import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from run_entry_quality_comparison import (
    DEFAULT_DATABASE,
    DEFAULT_OUTPUT_ROOT,
    FILTER_COUNTERS,
    calculate_entry_quality_metrics,
    filter_counts,
    grouped_entry_quality_metrics,
    strategy_specs,
    write_reports,
)
from run_contract_strategy_comparison import benchmark_config


class EntryQualityComparisonTest(unittest.TestCase):
    def test_seven_frozen_single_variable_specs(self):
        specs = strategy_specs()
        self.assertEqual(
            [spec["name"] for spec in specs],
            [
                "v2a_baseline",
                "v2a_min_stop_0_10",
                "v2a_delay_target_revalidate",
                "bears_baseline",
                "bears_fib_05",
                "bears_triple",
                "bears_fib_05_triple_diag",
            ],
        )
        self.assertEqual(DEFAULT_DATABASE, Path("data/btcusdt_perp_1m_202101_present.duckdb"))
        self.assertEqual(DEFAULT_OUTPUT_ROOT, Path("reports/entry_quality_benchmark"))

        v2a = {spec["name"]: spec for spec in specs[:3]}
        baseline = v2a["v2a_baseline"]
        self.assertEqual(baseline["kwargs"]["ltf"], "5m")
        self.assertEqual(baseline["kwargs"]["entry_delay"], "90m")
        self.assertEqual(baseline["max_holding_bars"], 288)
        min_stop_diff = set(v2a["v2a_min_stop_0_10"]["kwargs"].items()) - set(baseline["kwargs"].items())
        revalidate_diff = set(v2a["v2a_delay_target_revalidate"]["kwargs"].items()) - set(baseline["kwargs"].items())
        self.assertEqual(min_stop_diff, {("min_stop_pct", 0.001)})
        self.assertEqual(revalidate_diff, {("invalidate_target_during_delay", True)})

        bears = {spec["name"]: spec for spec in specs[3:]}
        self.assertEqual(bears["bears_baseline"]["kwargs"], {})
        self.assertEqual(bears["bears_fib_05"]["kwargs"], {"allowed_fib_ratios": (0.5,)})
        self.assertEqual(bears["bears_triple"]["kwargs"], {"require_triple": True})
        self.assertEqual(
            bears["bears_fib_05_triple_diag"]["kwargs"],
            {"allowed_fib_ratios": (0.5,), "require_triple": True},
        )
        self.assertTrue(all(spec["max_holding_bars"] == 24 for spec in specs[3:]))

    def test_common_risk_and_execution_config(self):
        for bars in (288, 24):
            cfg = benchmark_config(bars)
            self.assertEqual(cfg.initial_balance, 10_000.0)
            self.assertEqual(cfg.risk_pct, 0.05)
            self.assertEqual(cfg.leverage, 20.0)
            self.assertEqual(cfg.maker_fee, 0.0002)
            self.assertEqual(cfg.taker_fee, 0.0005)
            self.assertEqual(cfg.max_holding_bars, bars)

    def test_entry_quality_metrics(self):
        trades = [
            {
                "entry_time": "2026-07-01 00:00:00",
                "exit_time": "2026-07-01 00:05:00",
                "pnl": 100.0,
                "rr_realized": 2.0,
            },
            {
                "entry_time": "2026-07-01 01:00:00",
                "exit_time": "2026-07-01 01:20:00",
                "pnl": 50.0,
                "rr_realized": 1.0,
            },
            {
                "entry_time": "2026-07-01 02:00:00",
                "exit_time": "2026-07-01 02:04:00",
                "pnl": -60.0,
                "rr_realized": -1.0,
            },
        ]
        metrics = calculate_entry_quality_metrics(trades, missed=4, initial_balance=10_000.0, signal_timeframe="5m")
        self.assertEqual(metrics["return_pct"], 0.9)
        self.assertEqual(metrics["profit_factor"], 2.5)
        self.assertEqual(metrics["avg_rr_realized"], 0.6667)
        self.assertEqual(metrics["breakeven_win_rate_pct"], 40.0)
        self.assertEqual(metrics["quick_exit_count"], 2)
        self.assertEqual(metrics["quick_exit_rate_pct"], 66.6667)
        self.assertEqual(metrics["top_win_share_pct"], 66.6667)
        self.assertEqual(metrics["missed"], 4)

    def test_metric_edges_for_empty_no_wins_and_no_losses(self):
        empty = calculate_entry_quality_metrics([], 2, 10_000.0, "1h")
        self.assertIsNone(empty["avg_rr_realized"])
        self.assertIsNone(empty["breakeven_win_rate_pct"])
        self.assertIsNone(empty["top_win_share_pct"])

        no_wins = calculate_entry_quality_metrics(
            [{"entry_time": "2026-01-01", "exit_time": "2026-01-01 01:00", "pnl": -10, "rr_realized": -1}],
            0,
            10_000.0,
            "1h",
        )
        self.assertEqual(no_wins["profit_factor"], 0.0)
        self.assertIsNone(no_wins["breakeven_win_rate_pct"])
        self.assertIsNone(no_wins["top_win_share_pct"])

        no_losses = calculate_entry_quality_metrics(
            [{"entry_time": "2026-01-01", "exit_time": "2026-01-01 02:00", "pnl": 10, "rr_realized": 1}],
            0,
            10_000.0,
            "1h",
        )
        self.assertIsNone(no_losses["profit_factor"])
        self.assertIsNone(no_losses["breakeven_win_rate_pct"])
        self.assertEqual(no_losses["top_win_share_pct"], 100.0)

    def test_all_filter_counters_are_serialized_with_zero_defaults(self):
        class Strategy:
            stop_too_tight_count = 3
            fib_filtered_setups = 7

        counts = filter_counts(Strategy())
        self.assertEqual(set(counts), set(FILTER_COUNTERS))
        self.assertEqual(counts["stop_too_tight_count"], 3)
        self.assertEqual(counts["fib_filtered_setups"], 7)
        self.assertEqual(counts["delay_target_invalidated_count"], 0)
        self.assertEqual(counts["triple_filtered_setups"], 0)
        json.dumps(counts, allow_nan=False)

    def test_grouped_metrics_have_year_and_side_labels(self):
        trades = [
            {
                "type": "LONG",
                "entry_time": "2025-12-31 23:00:00",
                "exit_time": "2026-01-01 00:00:00",
                "entry_balance": 10_000.0,
                "pnl": 100.0,
                "rr_realized": 2.0,
            },
            {
                "type": "SHORT",
                "entry_time": "2026-02-01 00:00:00",
                "exit_time": "2026-02-01 02:00:00",
                "entry_balance": 10_100.0,
                "pnl": -50.0,
                "rr_realized": -1.0,
            },
            {
                "type": "LONG",
                "entry_time": "2027-01-01 00:00:00",
                "exit_time": "2027-01-01 00:30:00",
                "entry_balance": 10_050.0,
                "pnl": 25.0,
                "rr_realized": 0.5,
            },
        ]
        by_year = grouped_entry_quality_metrics(trades, "year", "1h")
        self.assertEqual([row["year"] for row in by_year], [2026, 2027])
        self.assertEqual(by_year[0]["trades"], 2)
        self.assertEqual(by_year[0]["profit_factor"], 2.0)
        self.assertEqual(by_year[0]["quick_exit_count"], 1)

        by_side = grouped_entry_quality_metrics(trades, "type", "1h")
        self.assertEqual([row["type"] for row in by_side], ["LONG", "SHORT"])
        self.assertEqual(by_side[0]["trades"], 2)
        self.assertEqual(by_side[0]["top_win_share_pct"], 80.0)
        self.assertEqual(by_side[1]["trades"], 1)
        self.assertEqual(grouped_entry_quality_metrics([], "year", "1h"), [])

    def test_report_formats_and_existing_output_is_not_overwritten(self):
        metrics = calculate_entry_quality_metrics(
            [{"entry_time": pd.Timestamp("2026-07-01"), "exit_time": pd.Timestamp("2026-07-01 00:05"), "pnl": 5, "rr_realized": 0.5}],
            0,
            10_000.0,
            "5m",
        )
        metrics.update({name: 0 for name in FILTER_COUNTERS})
        result = {"strategy": "v2a_baseline", "period": "full", "metrics": metrics}
        payload = {"snapshot": {"fingerprint": "fixed"}, "results": [result]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run_fixed"
            output.mkdir(parents=True, exist_ok=False)
            write_reports([result], payload, output)
            self.assertTrue((output / "summary.csv").is_file())
            self.assertTrue((output / "summary.json").is_file())
            self.assertTrue((output / "summary.md").is_file())
            decoded = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(decoded["snapshot"]["fingerprint"], "fixed")
            with self.assertRaises(FileExistsError):
                output.mkdir(parents=True, exist_ok=False)


if __name__ == "__main__":
    unittest.main()
