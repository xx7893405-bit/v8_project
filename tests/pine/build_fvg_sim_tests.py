"""Extract production Pine helpers into native fixtures; this does not execute Pine."""
from pathlib import Path
import argparse
import hashlib
import json


def extract(text, name):
    begin, end = f"// BEGIN {name}", f"// END {name}"
    assert text.count(begin) == text.count(end) == 1
    return text[text.index(begin):text.index(end) + len(end)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["contract", "timing"], default="contract")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "tradingview/fvg_confluence_strategy_1a.pine"
    text = source.read_text()
    fixture = ('//@version=6\nindicator("FVG Sim Contract Tests", overlay=true)\n'
               + extract(text, "SIM CONTRACT FUNCTIONS") + "\n"
               + Path(__file__).with_name("fvg_sim_contract_cases.pine").read_text())
    if args.mode == "timing":
        header = text.splitlines()[1].replace("V8 FVG 共振 1.0A｜模擬交易", "FVG Sim Timing Tests")
        fixture = "//@version=6\n" + header + "\n" + extract(text, "SIM CONTRACT FUNCTIONS") + "\n" + extract(text, "SIM SCHEDULER") + "\n" + Path(__file__).with_name("fvg_sim_timing_cases.pine").read_text()
    args.output.write_text(fixture)
    print(json.dumps({"fixture": str(args.output), "sha256": hashlib.sha256(fixture.encode()).hexdigest(),
                      "assertions": fixture.count("passed += f_assert"), "execution": "not run; use TradingView"}))


if __name__ == "__main__":
    main()
