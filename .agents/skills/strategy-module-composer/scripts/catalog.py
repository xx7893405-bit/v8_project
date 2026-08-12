#!/usr/bin/env python3
"""Read the V8 Strategy Module Catalog from its live registry."""

import argparse
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--stage")
    parser.add_argument("--status")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / "nfe_v2_decision_template.py").is_file():
        parser.error("--repo must be the V8 repository root")
    sys.path.insert(0, str(repo))

    from nfe_v2_decision_template import nfe_v2_plugin_registry

    catalog = nfe_v2_plugin_registry().catalog()
    catalog["modules"] = [
        module
        for module in catalog["modules"]
        if (args.stage is None or module["stage"] == args.stage)
        and (args.status is None or module["status"] == args.status)
    ]
    print(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
