import unittest

from portfolio_runtime import PortfolioAccount, parse_symbol_allocations


class PortfolioRuntimeTest(unittest.TestCase):
    def test_allocations_and_reserve(self):
        account = PortfolioAccount.from_config(
            1000,
            {
                "BTC": {"margin_budget": 300, "min_strategy_amount": 100},
                "ETH": {"margin_budget": 400, "min_strategy_amount": 100},
                "SOL": {"margin_budget": 300, "min_strategy_amount": 100},
            },
        )
        self.assertEqual(account.reserve, 0)
        self.assertEqual(account.strategy_amount("ETH"), 400)

    def test_realized_pnl_compounds_only_for_its_symbol(self):
        account = PortfolioAccount.from_config(
            1000,
            {"BTC": {"margin_budget": 300, "min_strategy_amount": 100}, "ETH": {"margin_budget": 700, "min_strategy_amount": 100}},
        )
        self.assertIsNone(account.apply_realized_pnl("BTC", 50))
        self.assertEqual(account.strategy_amount("BTC"), 350)
        self.assertEqual(account.strategy_amount("ETH"), 700)

    def test_minimum_amount_halts_once_and_emits_event(self):
        account = PortfolioAccount.from_config(
            1000, {"BTC": {"margin_budget": 300, "min_strategy_amount": 100}}
        )
        event = account.apply_realized_pnl("BTC", -210)
        self.assertEqual(event["event_type"], "STRATEGY_HALTED_MIN_AMOUNT")
        self.assertFalse(account.can_open_new_position("BTC"))
        self.assertIsNone(account.apply_realized_pnl("BTC", -1))

    def test_parser(self):
        config = parse_symbol_allocations("BTC=300:100,ETH=400:120,SOL=300:80")
        self.assertEqual(config["ETH"]["min_strategy_amount"], 120)


if __name__ == "__main__":
    unittest.main()
