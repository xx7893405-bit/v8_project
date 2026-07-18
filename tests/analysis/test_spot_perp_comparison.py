import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from run_contract_strategy_comparison import benchmark_config
from run_spot_perp_comparison import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PERP_DATABASE,
    DEFAULT_SPOT_CSV,
    build_comparison,
    calculate_market_metrics,
    match_trade_entries,
    strategy_specs,
    write_reports,
)


class FakeFeed:
    def __init__(self, closes):
        index = pd.date_range("2021-01-01", periods=len(closes), freq="1min")
        self.frame = pd.DataFrame({"close": closes}, index=index)

    def load_timeframe(self, timeframe):
        if timeframe != "1m":
            raise AssertionError("comparison audit should request only aligned 1m")
        return self.frame.copy()


class SpotPerpComparisonTest(unittest.TestCase):
    def test_canonical_paths_and_six_frozen_specs(self):
        self.assertEqual(DEFAULT_SPOT_CSV, Path("202101-202607_merged/btc_1m.csv"))
        self.assertEqual(DEFAULT_PERP_DATABASE, Path("data/btcusdt_perp_1m_202101_present.duckdb"))
        self.assertEqual(DEFAULT_OUTPUT_ROOT, Path("reports/spot_perp_benchmark"))
        specs = strategy_specs()
        self.assertEqual([item["name"] for item in specs], ["nfe_v2", "nfe_v2_a", "bears"])
        self.assertEqual(
            [(item["signal_timeframe"], item["max_holding_bars"]) for item in specs],
            [("15m", 96), ("5m", 288), ("1h", 24)],
        )
        self.assertEqual(specs[0]["kwargs"]["ltf"], "15m")
        self.assertEqual(specs[1]["kwargs"]["ltf"], "5m")
        self.assertEqual(specs[1]["kwargs"]["entry_delay"], "90m")
        self.assertEqual(specs[2]["kwargs"], {})
        for spec in specs:
            config = benchmark_config(spec["max_holding_bars"])
            self.assertEqual(config.risk_pct, 0.05)
            self.assertEqual(config.leverage, 20.0)
            self.assertEqual(config.maker_fee, 0.0002)
            self.assertEqual(config.taker_fee, 0.0005)
            self.assertEqual(config.funding_rate_8h, 0.0001)

    def test_known_basis_metrics(self):
        index = pd.date_range("2026-01-01", periods=4, freq="1min")
        spot = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]}, index=index)
        perp = pd.DataFrame({"close": [100.1, 101.101, 102.102, 103.103]}, index=index)
        metrics = calculate_market_metrics(spot, perp)
        self.assertEqual(metrics["aligned_1m_rows"], 4)
        self.assertAlmostEqual(metrics["median_basis_bps"], 10.0)
        self.assertAlmostEqual(metrics["p95_abs_basis_bps"], 10.0)
        self.assertAlmostEqual(metrics["close_correlation"], 1.0)
        self.assertAlmostEqual(metrics["return_correlation"], 1.0)

    def test_trade_overlap_is_one_to_one_side_aware_and_inclusive(self):
        spot = [
            {"entry_time": "2026-01-01 00:00", "type": "LONG"},
            {"entry_time": "2026-01-01 00:04", "type": "LONG"},
            {"entry_time": "2026-01-01 01:00", "type": "SHORT"},
        ]
        perp = [
            {"entry_time": "2026-01-01 00:03", "type": "LONG"},
            {"entry_time": "2026-01-01 01:05", "type": "SHORT"},
            {"entry_time": "2026-01-01 01:00", "type": "LONG"},
        ]
        result = match_trade_entries(spot, perp, "5m")
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["spot_only"], 1)
        self.assertEqual(result["perp_only"], 1)
        self.assertEqual(result["spot_match_rate_pct"], 66.6667)
        self.assertEqual(result["perp_match_rate_pct"], 66.6667)
        self.assertEqual(sorted(item["side"] for item in result["matches"]), ["LONG", "SHORT"])

    def test_mock_feeds_build_exactly_six_market_runs(self):
        calls = []

        def runner(spec, market, feed, start, end, output_dir):
            calls.append((spec["name"], market, start, end, feed))
            trade = {"entry_time": "2021-01-01 01:00", "type": "LONG"}
            return {
                "strategy": spec["name"],
                "market": market,
                "start": str(start),
                "end": str(end),
                "metrics": {"return_pct": 0.0, "max_drawdown_pct": 0.0, "trades": 1, "win_rate_pct": 0.0, "profit_factor": 0.0},
                "trades": [trade],
            }

        spot_feed = FakeFeed([100, 101, 102])
        perp_feed = FakeFeed([100.1, 101.1, 102.1])
        audit = {
            "common_fingerprint": "fixed",
            "common_first": "2020-12-31 23:59:00",
            "common_last": "2021-01-01 00:02:00",
            "common_rows": 3,
        }
        results, market_metrics, overlaps = build_comparison(
            spot_feed, perp_feed, audit, Path("unused"), runner=runner
        )
        self.assertEqual(len(results), 6)
        self.assertEqual(len(calls), 6)
        self.assertEqual([(item[0], item[1]) for item in calls], [
            ("nfe_v2", "spot"), ("nfe_v2", "perp"),
            ("nfe_v2_a", "spot"), ("nfe_v2_a", "perp"),
            ("bears", "spot"), ("bears", "perp"),
        ])
        self.assertTrue(all(item[2] == pd.Timestamp("2021-01-01") for item in calls))
        self.assertEqual(market_metrics["aligned_1m_rows"], 3)
        self.assertEqual([item["matched_count"] for item in overlaps], [1, 1, 1])

    def test_reports_serialize_snapshot_grouping_and_overlap(self):
        metrics = {
            "return_pct": 1.0,
            "max_drawdown_pct": -2.0,
            "trades": 1,
            "win_rate_pct": 100.0,
            "profit_factor": None,
            "final_balance": 10_100.0,
            "missed": 0,
        }
        results = [
            {
                "strategy": "nfe_v2",
                "market": "spot",
                "metrics": metrics,
                "by_year": [{"year": 2026, **metrics}],
                "by_side": [{"type": "LONG", **metrics}],
            }
        ]
        payload = {
            "snapshot": {"common_fingerprint": "fixed", "common_first": pd.Timestamp("2021-01-01")},
            "market_metrics": {"median_basis_bps": 1.25},
            "trade_overlap": [{"strategy": "nfe_v2", "matched_count": 1, "matches": []}],
            "results": results,
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run_fixed"
            output.mkdir(exist_ok=False)
            write_reports(results, payload, output)
            self.assertTrue((output / "summary.csv").is_file())
            self.assertTrue((output / "by_year.csv").is_file())
            self.assertTrue((output / "by_side.csv").is_file())
            self.assertTrue((output / "trade_overlap.csv").is_file())
            self.assertTrue((output / "summary.md").is_file())
            decoded = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(decoded["snapshot"]["common_fingerprint"], "fixed")
            self.assertEqual(decoded["results"][0]["by_year"][0]["year"], 2026)


if __name__ == "__main__":
    unittest.main()
