"""Build a native Pine fixture from the production indicator's pure functions.

This builder does not execute Pine or backtest prices. Paste its output into
TradingView; runtime assertions there are the execution evidence.
"""
from pathlib import Path
import argparse
import hashlib
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "tradingview/fvg_confluence_visual_1a.pine"
    cases = Path(__file__).with_name("fvg_confluence_contract_cases.pine")
    text = source.read_text(encoding="utf-8")
    begin, end = "// BEGIN CONTRACT FUNCTIONS", "// END CONTRACT FUNCTIONS"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise SystemExit("Expected exactly one production contract-function block")
    functions = text[text.index(begin):text.index(end) + len(end)]
    fixture = ('//@version=6\nindicator("FVG 1.0A Contract Tests", overlay=true)\n'
               + functions + "\n" + cases.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(fixture, encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "production_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "fixture_sha256": hashlib.sha256(fixture.encode()).hexdigest(),
                      "assertions": fixture.count("passed += f_assert"),
                      "execution": "not run; use TradingView Pine Editor"}))


if __name__ == "__main__":
    main()
