import sys
import unittest
from unittest.mock import patch

import paper_trader
import run_api_backtest
import run_live_trading


class EntrypointDefaultsTest(unittest.TestCase):
    def test_okx_defaults_to_perpetual_swap_contract(self):
        for module in (paper_trader, run_api_backtest, run_live_trading):
            with self.subTest(module=module.__name__), patch.object(sys, "argv", [f"{module.__name__}.py"]):
                self.assertEqual(module.parse_args().okx_symbol, "BTC-USDT-SWAP")


if __name__ == "__main__":
    unittest.main()
