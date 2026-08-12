import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/skills/strategy-module-composer/scripts/catalog.py"


class StrategyModuleComposerSkillTest(unittest.TestCase):
    def test_catalog_cli_filters_the_live_registry(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                str(ROOT),
                "--stage",
                "direction",
                "--status",
                "parity-verified",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        catalog = json.loads(result.stdout)
        self.assertEqual(catalog["schema"], "strategy-module-catalog/v1")
        self.assertEqual(catalog["counts"]["parity-verified"], 8)
        self.assertEqual(
            [module["module_id"] for module in catalog["modules"]],
            ["v2.htf_structure_direction"],
        )


if __name__ == "__main__":
    unittest.main()
