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
    def __init__(
        self,
        positions=None,
        open_orders=None,
        entry_result=None,
        protection_result=None,
        close_result=None,
        fills=None,
    ):
        self.positions = list(positions or [])
        self.open_orders = list(open_orders or [])
        self.entry_result = entry_result or ExecutionResult(True, "OPEN", exchange_order_id="entry-1")
        self.protection_result = protection_result
        self.close_result = close_result or ExecutionResult(True, "CLOSED", exchange_order_id="close-1", filled_quantity=1.0)
        self.fills = list(fills or [])
        self.submitted = []
        self.cancelled = []

    def get_position(self):
        return self.positions.pop(0) if self.positions else None

    def get_open_orders(self):
        return list(self.open_orders)

    def submit_order(self, order):
        self.submitted.append(order)
        if not order.reduce_only:
            return self.entry_result
        if order.order_type == "market":
            return self.close_result
        result = self.protection_result or ExecutionResult(True, "OPEN", exchange_order_id=order.client_tag)
        if result.accepted and order.order_type in {"stop", "limit"}:
            self.open_orders.append(
                {
                    "id": result.exchange_order_id,
                    "clientOrderId": order.client_tag,
                    "quantity": order.quantity,
                    "stopPrice": order.stop_price,
                    "price": order.price,
                    "reduceOnly": True,
                }
            )
        return result

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        self.open_orders = [order for order in self.open_orders if str(order.get("id")) != str(order_id)]

    def get_fills(self, order_ids):
        return [fill for fill in self.fills if fill["order_id"] in order_ids]


class LiveExecutionContractTest(unittest.TestCase):
    def test_rejected_entry_does_not_submit_protection(self):
        client = FakeClient(entry_result=ExecutionResult(False, "REJECTED"))
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=True)
        self.assertEqual(entry.status, "REJECTED")
        self.assertEqual(exits, [])
        self.assertEqual(len(client.submitted), 1)

    def test_partial_fill_protects_only_exchange_size(self):
        actual = {"type": "LONG", "size": 0.4}
        client = FakeClient(
            positions=[None, None, actual],
            entry_result=ExecutionResult(True, "PARTIALLY_FILLED", exchange_order_id="entry-1", filled_quantity=0.4),
        )
        entry, exits = LiveExecutionEngine(client).reconcile_position(position(), allow_entry=True)
        self.assertEqual(entry.status, "PARTIALLY_FILLED")
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
        self.assertEqual([order.client_tag.split("-")[1] for order in client.submitted], ["stop", "tp1"])

    def test_changed_stop_is_cancelled_and_replaced(self):
        old_stop = {"id": "old-stop", "clientOrderId": "v8-stop-v8entry", "amount": 1.0, "stopPrice": 85.0}
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

    def test_new_entry_does_not_claim_matching_manual_position(self):
        client = FakeClient(
            positions=[{"type": "LONG", "size": 1.0}],
            open_orders=[{"id": "manual-stop", "clientOrderId": "manual-stop"}],
        )
        entry, exits = LiveExecutionEngine(client).reconcile_position(
            position(), allow_entry=True, entry_tag="v8-entry-LONG-new"
        )
        self.assertEqual(entry.status, "POSITION_OWNERSHIP_UNVERIFIED")
        self.assertFalse(entry.accepted)
        self.assertEqual(exits, [])
        self.assertEqual(client.submitted, [])
        self.assertEqual(client.cancelled, [])

    def test_submitted_but_unfilled_entry_does_not_claim_racing_position(self):
        client = FakeClient(positions=[None, None, {"type": "LONG", "size": 1.0}])
        entry, exits = LiveExecutionEngine(client).reconcile_position(
            position(), allow_entry=True, entry_tag="v8-entry-LONG-new"
        )
        self.assertEqual(entry.status, "POSITION_OWNERSHIP_UNVERIFIED")
        self.assertEqual(exits, [])
        self.assertEqual([order.order_type for order in client.submitted], ["limit"])

    def test_managed_restart_with_matching_stop_can_continue(self):
        managed = position(live_entry_tag="v8-entry-LONG-1")
        stop_tag = LiveExecutionEngine._tags(managed)["stop"]
        client = FakeClient(
            positions=[{"type": "LONG", "size": 1.0}],
            open_orders=[
                {
                    "id": "stop-1",
                    "clientOrderId": stop_tag,
                    "quantity": 1.0,
                    "stopPrice": 90.0,
                    "reduceOnly": True,
                }
            ],
        )
        entry, exits = LiveExecutionEngine(client).reconcile_position(managed, allow_entry=False)
        self.assertEqual(entry.status, "ALREADY_IN_SYNC")
        self.assertTrue(entry.accepted)
        self.assertTrue(all(result.accepted for result in exits))
        self.assertNotIn("stop", [order.order_type for order in client.submitted])
        self.assertNotIn("market", [order.order_type for order in client.submitted])

    def test_protection_failure_triggers_reduce_only_market_close(self):
        client = FakeClient(
            positions=[None, None, {"type": "LONG", "size": 0.4}, None],
            entry_result=ExecutionResult(True, "PARTIALLY_FILLED", exchange_order_id="entry-1", filled_quantity=0.4),
            protection_result=ExecutionResult(False, "REJECTED"),
            close_result=ExecutionResult(True, "CLOSED", exchange_order_id="close-1", filled_quantity=0.4),
        )
        _, exits = LiveExecutionEngine(client).reconcile_position(
            position(), allow_entry=True, entry_tag="v8-entry-LONG-1"
        )
        self.assertEqual([result.status for result in exits], ["REJECTED", "CLOSED"])
        self.assertEqual([order.order_type for order in client.submitted], ["limit", "stop", "market"])
        self.assertTrue(client.submitted[-1].reduce_only)

    def test_unverified_accepted_stop_uses_shared_fail_closed_path(self):
        class LaggingOrderClient(FakeClient):
            def get_open_orders(self):
                return []

        client = LaggingOrderClient(
            positions=[None, None, {"type": "LONG", "size": 0.4}, None],
            entry_result=ExecutionResult(True, "PARTIALLY_FILLED", exchange_order_id="entry-1", filled_quantity=0.4),
            close_result=ExecutionResult(True, "CLOSED", exchange_order_id="close-1", filled_quantity=0.4),
        )
        _, exits = LiveExecutionEngine(client).reconcile_position(
            position(), allow_entry=True, entry_tag="v8-entry-LONG-1"
        )
        self.assertIn("PROTECTION_UNVERIFIED", [result.status for result in exits])
        self.assertEqual([order.order_type for order in client.submitted], ["limit", "stop", "limit", "market"])

    def test_partial_emergency_close_retries_protection_for_remainder(self):
        client = FakeClient(
            positions=[None, None, {"type": "LONG", "size": 0.4}, {"type": "LONG", "size": 0.1}],
            entry_result=ExecutionResult(True, "PARTIALLY_FILLED", exchange_order_id="entry-1", filled_quantity=0.4),
            protection_result=ExecutionResult(False, "REJECTED"),
            close_result=ExecutionResult(True, "OPEN", exchange_order_id="close-1", filled_quantity=0.3),
        )
        _, exits = LiveExecutionEngine(client).reconcile_position(
            position(), allow_entry=True, entry_tag="v8-entry-LONG-1"
        )
        self.assertIn("FLAT_NOT_CONVERGED", [result.status for result in exits])
        self.assertEqual([order.order_type for order in client.submitted], ["limit", "stop", "market", "stop"])
        self.assertEqual(client.submitted[-1].quantity, 0.1)

    def test_api_lag_partial_fill_is_protected_from_confirmed_quantity(self):
        client = FakeClient(
            positions=[None, None, None],
            entry_result=ExecutionResult(
                True,
                "PARTIALLY_FILLED",
                exchange_order_id="entry-1",
                filled_quantity=0.4,
                average_price=100.0,
            ),
        )
        managed = position(live_entry_tag="v8-entry-LONG-1")
        engine = LiveExecutionEngine(client)
        entry, exits = engine.reconcile_position(managed, allow_entry=True)
        self.assertEqual(entry.status, "PARTIALLY_FILLED")
        self.assertEqual([order.quantity for order in client.submitted[1:]], [0.4, 0.4])
        self.assertTrue(all(result.accepted for result in exits))
        self.assertTrue(engine.protection_status(managed, engine.confirmed_position)["protected"])

    def test_unfilled_pending_entry_is_cancelled_and_rechecked(self):
        client = FakeClient(positions=[None, None, None, None])
        entry, exits = LiveExecutionEngine(client).reconcile_position(
            position(live_entry_tag="v8-entry-LONG-1"), allow_entry=True
        )
        self.assertEqual(entry.status, "ENTRY_CANCELLED_UNFILLED")
        self.assertFalse(entry.accepted)
        self.assertEqual(exits, [])
        self.assertEqual(client.cancelled, ["entry-1"])
        self.assertEqual([order.order_type for order in client.submitted], ["limit"])

    def test_protection_status_requires_equal_reduce_only_stop(self):
        managed = position(live_entry_tag="v8-entry-LONG-1")
        tag = LiveExecutionEngine._tags(managed)["stop"]
        client = FakeClient(
            positions=[{"type": "LONG", "size": 0.4}],
            open_orders=[
                {"id": "stop-1", "clientOrderId": tag, "quantity": 0.3, "stopPrice": 90, "reduceOnly": True}
            ],
        )
        status = LiveExecutionEngine(client).protection_status(managed)
        self.assertFalse(status["protected"])
        self.assertEqual(status["covered_qty"], 0.3)

    def test_restart_fill_ledger_updates_cumulative_order_without_duplicate(self):
        engine = LiveExecutionEngine(FakeClient())
        old = [{"fill_id": "order:entry-1", "order_id": "entry-1", "quantity": 0.2}]
        updated = [{"fill_id": "order:entry-1", "order_id": "entry-1", "quantity": 0.4}]
        self.assertEqual(engine.merge_fills(old, updated), updated)

        trade = {"fill_id": "trade-1", "order_id": "entry-1", "quantity": 0.4}
        self.assertEqual(engine.merge_fills(updated, [trade]), [trade])

    def test_exchange_trade_fill_is_collected_idempotently_with_cost_fields(self):
        fill = {
            "fill_id": "trade-1",
            "order_id": "entry-1",
            "client_tag": "v8-entry-LONG-1",
            "quantity": 0.4,
            "average_price": 100.0,
            "fee": 0.02,
            "fee_currency": "USDT",
            "timestamp": "2026-01-02T12:15:01+00:00",
        }
        engine = LiveExecutionEngine(FakeClient(fills=[fill]))
        current, order_ids = engine.collect_fills([], ["entry-1"])
        self.assertEqual(current, [fill])
        self.assertEqual(order_ids, ["entry-1"])
        self.assertEqual(engine.merge_fills(current, current), [fill])

    def test_stale_managed_order_is_cancelled_but_manual_order_is_untouched(self):
        managed = position(live_entry_tag="v8-entry-LONG-1", live_tp2=None, tp1_realized=True)
        client = FakeClient(
            open_orders=[
                {"id": "stale", "clientOrderId": "v8-stop-old", "quantity": 1.0, "stopPrice": 80},
                {"id": "manual", "clientOrderId": "manual-stop", "quantity": 1.0, "stopPrice": 80},
            ]
        )
        LiveExecutionEngine(client).submit_exit_orders(managed, {"type": "LONG", "size": 1.0})
        self.assertEqual(client.cancelled, ["stale"])

    def test_flat_convergence_closes_only_proven_managed_position(self):
        previous = position(live_entry_tag="v8-entry-LONG-1")
        stop_tag = LiveExecutionEngine._tags(previous)["stop"]
        client = FakeClient(
            positions=[{"type": "LONG", "size": 1.0}, None],
            open_orders=[
                {
                    "id": "stop-1",
                    "clientOrderId": stop_tag,
                    "quantity": 1.0,
                    "stopPrice": 90.0,
                    "reduceOnly": True,
                }
            ],
        )
        result, _ = LiveExecutionEngine(client).reconcile_flat(previous)
        self.assertEqual(result.status, "FLAT_CONVERGED")
        self.assertTrue(client.submitted[0].reduce_only)
        self.assertEqual(client.submitted[0].order_type, "market")

    def test_flat_does_not_claim_tagged_position_without_matching_stop(self):
        previous = position(live_entry_tag="v8-entry-LONG-1")
        client = FakeClient(positions=[{"type": "LONG", "size": 1.0}])
        result, actions = LiveExecutionEngine(client).reconcile_flat(previous)
        self.assertEqual(result.status, "FLAT_OWNERSHIP_UNPROVEN")
        self.assertEqual(actions, [])
        self.assertEqual(client.submitted, [])

    def test_flat_does_not_touch_unproven_position_or_manual_order(self):
        client = FakeClient(
            positions=[{"type": "LONG", "size": 1.0}],
            open_orders=[{"id": "manual", "clientOrderId": "manual-stop"}],
        )
        result, actions = LiveExecutionEngine(client).reconcile_flat(position())
        self.assertEqual(result.status, "FLAT_OWNERSHIP_UNPROVEN")
        self.assertEqual(actions, [])
        self.assertEqual(client.submitted, [])
        self.assertEqual(client.cancelled, [])


if __name__ == "__main__":
    unittest.main()
