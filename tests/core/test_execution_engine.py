import unittest

from execution_engine import CcxtExecutionClient, ExecutionOrder, ExecutionResult, LiveExecutionEngine


class FakeExchange:
    def amount_to_precision(self, symbol, value):
        return f"{value:.3f}"

    def price_to_precision(self, symbol, value):
        return f"{value:.1f}"

    def set_leverage(self, leverage, symbol, params=None):
        self.leverage = leverage

    def create_order(self, *args):
        self.order = args
        return {"id": "mock-1", "status": "open"}


class ExecutionEngineTest(unittest.TestCase):
    def test_entry_converts_base_quantity_to_contracts(self):
        client = CcxtExecutionClient.__new__(CcxtExecutionClient)
        client.exchange_name = "binance"
        client.symbol = "BTC/USDT:USDT"
        client.exchange = FakeExchange()
        client.market = {
            "contract": True,
            "contractSize": 0.001,
            "limits": {"amount": {"min": 1}, "leverage": {"max": 20}},
        }
        client.margin_mode = "isolated"

        result = client.submit_order(
            ExecutionOrder(
                side="LONG",
                order_type="limit",
                quantity=0.12345,
                price=60000.12,
                leverage=3,
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(client.exchange.leverage, 3.0)
        self.assertEqual(client.exchange.order[:5], ("BTC/USDT:USDT", "limit", "buy", 123.45, 60000.1))

    def test_engine_submits_protective_stop_as_reduce_only(self):
        class Client:
            def __init__(self):
                self.orders = []

            def submit_order(self, order):
                self.orders.append(order)
                return ExecutionResult(True, "ok")

            def get_open_orders(self):
                return []

        client = Client()
        LiveExecutionEngine(client).submit_exit_orders(
            {"type": "LONG", "size": 0.1, "sl": 59000, "tp2": 62000, "leverage": 2}
        )
        self.assertEqual([order.order_type for order in client.orders], ["stop", "limit"])
        self.assertTrue(all(order.reduce_only for order in client.orders))
        self.assertEqual(client.orders[0].leverage, 2.0)
        self.assertTrue(all(order.client_tag.startswith("v8-") for order in client.orders))

    def test_engine_does_not_duplicate_protective_orders(self):
        class Client:
            def get_open_orders(self):
                return [
                    {"clientOrderId": "v8-stop-v8entry"},
                    {"clientOrderId": "v8-tp2-v8entry"},
                ]

            def submit_order(self, order):
                raise AssertionError("protective order should be skipped")

        self.assertEqual(
            LiveExecutionEngine(Client()).submit_exit_orders(
                {"type": "LONG", "size": 0.1, "sl": 59000, "tp2": 62000}
            ),
            [],
        )

    def test_engine_does_not_duplicate_same_side_position(self):
        class Client:
            def get_position(self):
                return {"type": "LONG", "size": 0.1}

            def submit_order(self, order):
                raise AssertionError("entry should be skipped")

        result = LiveExecutionEngine(Client()).submit_entry_from_position(
            {"type": "LONG", "size": 0.1, "entry_price": 60000}
        )
        self.assertEqual(result.status, "ALREADY_IN_SYNC")


if __name__ == "__main__":
    unittest.main()
