import unittest

from execution_engine import ExecutionResult, LiveExecutionEngine


def position(**changes):
    value = {
        "type": "LONG",
        "size": 1.0,
        "remaining_size": 1.0,
        "entry_price": 100.0,
        "entry_mode": "NFE_DL_LONG",
        "sl": 90.0,
        "tp1": 110.0,
        "tp2": 120.0,
        "tp1_close_pct": 0.5,
        "tp1_realized": False,
    }
    value.update(changes)
    return value


class FakeClient:
    def __init__(self, positions=None, open_orders=None, entry_result=None):
        self.positions = list(positions or [])
        self.open_orders = list(open_orders or [])
        self.entry_result = entry_result or ExecutionResult(True, "OPEN", exchange_order_id="entry-1")
        self.submitted = []
        self.cancelled = []

    def get_position(self):
        return self.positions.pop(0) if self.positions else None

    def get_open_orders(self):
        return list(self.open_orders)

    def submit_order(self, order):
        self.submitted.append(order)
        return self.entry_result if not order.reduce_only else ExecutionResult(True, "OPEN", exchange_order_id=order.client_tag)

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)


class LiveExecutionContractTest(unittest.TestCase):
    def test_rejected_entry_does_not_submit_protection(self):
        client = FakeClient(entry_result=ExecutionResult(False, "REJECTED"))
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=True)
        self.assertEqual(entry.status, "REJECTED")
        self.assertEqual(exits, [])
        self.assertEqual(len(client.submitted), 1)

    def test_partial_fill_protects_only_exchange_size(self):
        actual = {"type": "LONG", "size": 0.4}
        client = FakeClient(positions=[None, None, actual])
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=True)
        self.assertEqual(entry.status, "OPEN")
        self.assertEqual([order.quantity for order in client.submitted[1:]], [0.4, 0.4])
        self.assertEqual(len(exits), 2)

    def test_restart_does_not_recreate_absent_entry(self):
        client = FakeClient()
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=False)
        self.assertEqual(entry.status, "ENTRY_NOT_AUTHORIZED")
        self.assertEqual(exits, [])
        self.assertEqual(client.submitted, [])

    def test_sentinel_tp2_is_not_submitted_live(self):
        client = FakeClient(positions=[{"type": "LONG", "size": 1.0}])
        LiveExecutionEngine(client).submit_exit_orders(position(live_tp2=None), {"type": "LONG", "size": 1.0})
        self.assertEqual([order.client_tag for order in client.submitted], ["protective-stop", "take-profit-1"])

    def test_changed_stop_is_cancelled_and_replaced(self):
        old_stop = {"id": "old-stop", "clientOrderId": "protective-stop", "amount": 1.0, "stopPrice": 85.0}
        client = FakeClient(open_orders=[old_stop])
        LiveExecutionEngine(client).submit_exit_orders(
            position(live_tp2=None, tp1_realized=True, sl=95.0),
            {"type": "LONG", "size": 1.0},
        )
        self.assertEqual(client.cancelled, ["old-stop"])
        self.assertEqual(client.submitted[0].stop_price, 95.0)

    def test_same_side_size_mismatch_is_not_treated_as_synced(self):
        client = FakeClient(positions=[{"type": "LONG", "size": 0.25}])
        result = LiveExecutionEngine(client).submit_entry_from_position(position())
        self.assertEqual(result.status, "POSITION_SIZE_MISMATCH")
        self.assertFalse(result.accepted)

    def test_unmanaged_same_side_size_mismatch_does_not_get_strategy_protection(self):
        client = FakeClient(positions=[{"type": "LONG", "size": 0.25}])
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=False)
        self.assertEqual(entry.status, "POSITION_SIZE_MISMATCH")
        self.assertEqual(exits, [])
        self.assertEqual(client.submitted, [])


if __name__ == "__main__":
    unittest.main()
