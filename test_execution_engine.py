import unittest

from execution_engine import CcxtExecutionClient, ExecutionOrder, LiveExecutionEngine


class FakeExchange:
    def amount_to_precision(self, symbol, value):
        return f"{value:.3f}"

    def price_to_precision(self, symbol, value):
        return f"{value:.1f}"

    def set_leverage(self, leverage, symbol):
        self.leverage = leverage

    def create_order(self, *args):
        self.order = args
        return {"id": "mock-1", "status": "open"}


class ExecutionEngineTest(unittest.TestCase):
    def test_entry_passes_precision_and_leverage(self):
        client = CcxtExecutionClient.__new__(CcxtExecutionClient)
        client.exchange_name = "binance"
        client.symbol = "BTC/USDT:USDT"
        client.exchange = FakeExchange()
        client.market = {"limits": {"amount": {"min": 0.001}}}

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
        self.assertEqual(client.exchange.order[:5], ("BTC/USDT:USDT", "limit", "buy", 0.123, 60000.1))

    def test_engine_submits_protective_stop_as_reduce_only(self):
        class Client:
            def __init__(self):
                self.orders = []

            def submit_order(self, order):
                self.orders.append(order)
                return type("Result", (), {"status": "ok"})()

            def get_open_orders(self):
                return []

        client = Client()
        LiveExecutionEngine(client).submit_exit_orders(
            {"type": "LONG", "size": 0.1, "sl": 59000, "tp2": 62000, "leverage": 2}
        )
        self.assertEqual([order.order_type for order in client.orders], ["stop", "limit"])
        self.assertTrue(all(order.reduce_only for order in client.orders))
        self.assertEqual(client.orders[0].leverage, 2.0)

    def test_engine_does_not_duplicate_protective_orders(self):
        class Client:
            def get_open_orders(self):
                return [{"clientOrderId": "protective-stop"}, {"clientOrderId": "take-profit"}]

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
