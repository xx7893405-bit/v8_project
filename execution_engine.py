from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    import ccxt
except ImportError:  # Dry-run mode remains usable without the optional live dependency.
    ccxt = None


@dataclass(frozen=True)
class ExecutionOrder:
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: bool = False
    client_tag: str = "codex-runtime"
    leverage: Optional[float] = None


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    status: str
    exchange_order_id: Optional[str] = None
    message: str = ""
    filled_quantity: float = 0.0
    average_price: Optional[float] = None
    fee: float = 0.0
    fee_currency: Optional[str] = None
    timestamp: Optional[str] = None
    exchange_trade_id: Optional[str] = None


class DryRunExecutionClient:
    def submit_order(self, order: ExecutionOrder) -> ExecutionResult:
        return ExecutionResult(
            accepted=True,
            status="DRY_RUN_ACCEPTED",
            exchange_order_id=None,
            message=f"Dry run only: {order.side} {order.order_type} qty={order.quantity}",
        )

    def cancel_all(self) -> None:
        return None

    def cancel_order(self, order_id: str) -> None:
        return None

    def get_position(self) -> Optional[dict]:
        return None

    def get_open_orders(self) -> list[dict]:
        return []

    def get_fills(self, order_ids: set[str]) -> list[dict]:
        return []


class CcxtExecutionClient:
    """Small CCXT adapter for Binance and OKX USDT perpetuals."""

    def __init__(
        self,
        exchange: str,
        symbol: str,
        *,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        password: Optional[str] = None,
        sandbox: bool = True,
        market_type: str = "swap",
        margin_mode: str = "isolated",
    ):
        if exchange not in {"binance", "okx"}:
            raise ValueError("exchange must be binance or okx")
        if ccxt is None:
            raise RuntimeError("ccxt is required for live execution; install requirements.txt")
        if not api_key or not secret:
            raise ValueError("API credentials are required for live execution")
        exchange_class = getattr(ccxt, exchange)
        self.exchange_name = exchange
        self.symbol = symbol
        self.exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": secret,
                "password": password,
                "enableRateLimit": True,
                "options": {"defaultType": market_type},
            }
        )
        if sandbox:
            self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()
        if symbol not in self.exchange.markets:
            raise ValueError(f"{symbol!r} is unavailable on {exchange}")
        self.market = self.exchange.market(symbol)
        if not self.market.get("contract"):
            raise ValueError("live execution only supports contract markets")
        if margin_mode not in {"isolated", "cross"}:
            raise ValueError("margin_mode must be isolated or cross")
        self.margin_mode = margin_mode
        self.exchange.set_margin_mode(margin_mode, symbol)

    @classmethod
    def from_environment(cls, exchange: str, symbol: str, *, sandbox: bool = True, margin_mode: str = "isolated"):
        prefix = exchange.upper()
        return cls(
            exchange,
            symbol,
            api_key=os.getenv(f"{prefix}_API_KEY"),
            secret=os.getenv(f"{prefix}_API_SECRET"),
            password=os.getenv(f"{prefix}_API_PASSWORD"),
            sandbox=sandbox,
            margin_mode=margin_mode,
        )

    def _amount(self, amount: float) -> float:
        contract_size = float(self.market.get("contractSize") or 1.0)
        if contract_size <= 0:
            raise ValueError("exchange returned an invalid contractSize")
        contracts = float(amount) / contract_size
        value = float(self.exchange.amount_to_precision(self.symbol, contracts))
        minimum = self.market.get("limits", {}).get("amount", {}).get("min")
        if value <= 0 or (minimum is not None and value < float(minimum)):
            raise ValueError(f"order quantity {amount} ({contracts} contracts) is below exchange minimum")
        return value

    def _price(self, price: Optional[float]) -> Optional[float]:
        return None if price is None else float(self.exchange.price_to_precision(self.symbol, price))

    def _params(self, order: ExecutionOrder) -> dict:
        params = {"reduceOnly": order.reduce_only, "clientOrderId": order.client_tag[:32]}
        if self.exchange_name == "binance" and order.order_type == "stop":
            params.update({"stopPrice": self._price(order.stop_price), "workingType": "MARK_PRICE"})
        elif self.exchange_name == "okx" and order.order_type == "stop":
            params.update({"triggerPrice": self._price(order.stop_price), "triggerDirection": "ascending" if order.side == "LONG" else "descending"})
        return params

    def submit_order(self, order: ExecutionOrder) -> ExecutionResult:
        side = order.side.lower()
        if side not in {"long", "short"}:
            raise ValueError("order side must be LONG or SHORT")
        ccxt_side = "buy" if side == "long" else "sell"
        amount = self._amount(order.quantity)
        price = self._price(order.price)
        if order.leverage is not None:
            max_leverage = self.market.get("limits", {}).get("leverage", {}).get("max")
            if max_leverage is not None and float(order.leverage) > float(max_leverage):
                raise ValueError(f"requested leverage exceeds exchange maximum {max_leverage}")
            self.exchange.set_leverage(float(order.leverage), self.symbol, {"marginMode": self.margin_mode})
        params = self._params(order)
        if order.order_type == "stop":
            if self.exchange_name == "binance":
                order_type, price = "STOP_MARKET", None
            else:
                order_type, price = "trigger", None
        elif order.order_type in {"market", "limit"}:
            order_type = order.order_type
        else:
            raise ValueError(f"unsupported order type: {order.order_type}")
        result = self.exchange.create_order(self.symbol, order_type, ccxt_side, amount, price, params)
        fee = result.get("fee") or {}
        return ExecutionResult(
            accepted=True,
            status=str(result.get("status") or "accepted").upper(),
            exchange_order_id=str(result.get("id")) if result.get("id") else None,
            message=f"{self.exchange_name} {order_type} {ccxt_side} {amount}",
            filled_quantity=float(result.get("filled") or 0.0) * float(self.market.get("contractSize") or 1.0),
            average_price=float(result.get("average") or 0.0) or None,
            fee=float(fee.get("cost") or 0.0),
            fee_currency=fee.get("currency"),
            timestamp=self._timestamp(result.get("timestamp") or result.get("datetime")),
        )

    @staticmethod
    def _timestamp(value) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc).isoformat()

    def cancel_all(self) -> None:
        self.exchange.cancel_all_orders(self.symbol)

    def cancel_order(self, order_id: str) -> None:
        self.exchange.cancel_order(order_id, self.symbol)

    def get_open_orders(self) -> list[dict]:
        contract_size = float(self.market.get("contractSize") or 1.0)
        orders = self.exchange.fetch_open_orders(self.symbol)
        return [{**order, "quantity": float(order.get("amount") or 0.0) * contract_size} for order in orders]

    def get_position(self) -> Optional[dict]:
        positions = self.exchange.fetch_positions([self.symbol])
        for position in positions:
            contracts = float(position.get("contracts") or 0)
            if contracts <= 0:
                continue
            side = str(position.get("side") or "").upper()
            if side not in {"LONG", "SHORT"}:
                continue
            contract_size = float(self.market.get("contractSize") or 1.0)
            contracts = float(position.get("contracts") or 0)
            return {
                "type": "LONG" if side == "LONG" else "SHORT",
                "size": contracts * contract_size,
                "contracts": contracts,
                "contract_size": contract_size,
                "entry_price": float(position.get("entryPrice") or 0),
                "leverage": float(position.get("leverage") or 0),
                "margin_mode": position.get("marginMode") or self.margin_mode,
                "initial_margin": float(position.get("initialMargin") or 0),
                "maintenance_margin": float(position.get("maintenanceMargin") or 0),
                "liquidation_price": float(position.get("liquidationPrice") or 0) or None,
            }
        return None

    def get_fills(self, order_ids: set[str]) -> list[dict]:
        if not order_ids:
            return []
        contract_size = float(self.market.get("contractSize") or 1.0)
        fills = []
        for trade in self.exchange.fetch_my_trades(self.symbol):
            order_id = str(trade.get("order") or "")
            if order_id not in order_ids:
                continue
            fee = trade.get("fee") or {}
            trade_id = str(trade.get("id") or "")
            fills.append(
                {
                    "fill_id": trade_id or f"order:{order_id}",
                    "order_id": order_id,
                    "client_tag": str(trade.get("clientOrderId") or trade.get("info", {}).get("clientOrderId") or ""),
                    "quantity": float(trade.get("amount") or 0.0) * contract_size,
                    "average_price": float(trade.get("price") or 0.0) or None,
                    "fee": float(fee.get("cost") or 0.0),
                    "fee_currency": fee.get("currency"),
                    "timestamp": self._timestamp(trade.get("timestamp")),
                }
            )
        return fills


class LiveExecutionEngine:
    MANAGED_PREFIX = "v8-"

    def __init__(self, client):
        self.client = client
        self.confirmed_position: Optional[dict] = None
        self.last_protection_status = {
            "protected": False,
            "covered_qty": 0.0,
            "stop_id": None,
        }

    @classmethod
    def _tags(cls, position: dict) -> dict[str, str]:
        entry = str(position.get("live_entry_tag") or "v8-entry")
        suffix = "".join(ch for ch in entry if ch.isalnum())[-12:] or "position"
        return {
            "entry": entry[:32],
            "stop": f"v8-stop-{suffix}"[:32],
            "tp1": f"v8-tp1-{suffix}"[:32],
            "tp2": f"v8-tp2-{suffix}"[:32],
            "flat": f"v8-flat-{suffix}"[:32],
        }

    @classmethod
    def _is_managed_tag(cls, tag: str) -> bool:
        return tag.startswith(cls.MANAGED_PREFIX)

    def _confirmed_entry_quantity(self, result: ExecutionResult) -> float:
        quantity = float(result.filled_quantity)
        if not result.exchange_order_id or not hasattr(self.client, "get_fills"):
            return quantity
        try:
            fills = self.client.get_fills({str(result.exchange_order_id)})
        except Exception:
            return quantity
        return max(quantity, sum(float(fill.get("quantity") or 0.0) for fill in fills))

    def submit_entry_from_position(self, position: dict) -> ExecutionResult:
        existing = self.client.get_position()
        if existing is not None:
            if existing.get("type") == position.get("type"):
                expected_size = float(position.get("remaining_size", position["size"]))
                actual_size = float(existing.get("size") or 0.0)
                tolerance = max(1e-12, expected_size * 1e-6)
                if abs(expected_size - actual_size) > tolerance:
                    return ExecutionResult(
                        accepted=False,
                        status="POSITION_SIZE_MISMATCH",
                        message=f"Exchange size {actual_size} differs from strategy size {expected_size}; entry skipped.",
                    )
                return ExecutionResult(
                    accepted=False,
                    status="POSITION_OWNERSHIP_UNVERIFIED",
                    message="A matching exchange position exists without managed-order evidence; entry skipped.",
                )
            return ExecutionResult(
                accepted=False,
                status="POSITION_CONFLICT",
                message="An opposite exchange position exists; manual reconciliation required.",
            )
        entry_tag = str(position.get("live_entry_tag") or f"v8-entry-{position.get('entry_mode', 'UNKNOWN')}")[:32]
        pending = next(
            (order for order in self.client.get_open_orders() if self._client_tag(order) == entry_tag),
            None,
        )
        if pending is not None:
            return ExecutionResult(
                accepted=True,
                status="ENTRY_PENDING",
                exchange_order_id=str(pending.get("id") or pending.get("order_id") or "") or None,
                message="The entry order already exists; duplicate submission skipped.",
            )
        order_type = "market" if position.get("entry_mode") == "BREAKOUT" else "limit"
        return self.client.submit_order(
            ExecutionOrder(
                side=position["type"],
                order_type=order_type,
                quantity=float(position["size"]),
                price=float(position["entry_price"]),
                leverage=float(position.get("leverage") or 0) or None,
                client_tag=entry_tag,
            )
        )

    @staticmethod
    def _client_tag(order: dict) -> str:
        return str(
            order.get("clientOrderId")
            or order.get("client_order_id")
            or order.get("info", {}).get("clientOrderId")
            or ""
        )

    @staticmethod
    def _order_size(order: dict) -> float:
        return float(order.get("quantity") or order.get("amount") or order.get("info", {}).get("origQty") or 0.0)

    @staticmethod
    def _order_level(order: dict, *, stop: bool) -> float:
        info = order.get("info", {})
        value = (
            order.get("stopPrice") or order.get("triggerPrice") or info.get("stopPrice") or info.get("triggerPrice")
            if stop
            else order.get("price") or info.get("price")
        )
        return float(value or 0.0)

    @staticmethod
    def _reduce_only(order: dict) -> bool:
        value = order.get("reduceOnly")
        if value is None:
            value = order.get("reduce_only")
        if value is None:
            value = order.get("info", {}).get("reduceOnly")
        return value is True or str(value).lower() == "true"

    @staticmethod
    def _matches(order: dict, quantity: float, level: float, *, stop: bool) -> bool:
        if LiveExecutionEngine._order_size(order) == 0.0 and LiveExecutionEngine._order_level(order, stop=stop) == 0.0:
            # Some adapters omit normalized fields; the stable client tag is then
            # the only safe idempotency key and is preferable to duplicating exits.
            return True
        tolerance = max(1e-9, abs(quantity) * 1e-6)
        price_tolerance = max(1e-8, abs(level) * 1e-8)
        return (
            abs(LiveExecutionEngine._order_size(order) - quantity) <= tolerance
            and abs(LiveExecutionEngine._order_level(order, stop=stop) - level) <= price_tolerance
        )

    def _replace_if_needed(self, existing: Optional[dict], order: ExecutionOrder, *, stop: bool) -> list[ExecutionResult]:
        level = float(order.stop_price if stop else order.price)
        if existing is not None and self._matches(existing, order.quantity, level, stop=stop):
            return []
        if existing is not None:
            order_id = existing.get("id") or existing.get("order_id")
            if not order_id or not hasattr(self.client, "cancel_order"):
                return [ExecutionResult(False, "PROTECTION_CONFLICT", message=f"Cannot amend {order.client_tag} without an order id.")]
            self.client.cancel_order(str(order_id))
        return [self.client.submit_order(order)]

    def _cancel_if_present(self, existing: Optional[dict]) -> list[ExecutionResult]:
        if existing is None:
            return []
        order_id = existing.get("id") or existing.get("order_id")
        if not order_id or not hasattr(self.client, "cancel_order"):
            return [ExecutionResult(False, "PROTECTION_CONFLICT", message="Cannot cancel stale protection without an order id.")]
        self.client.cancel_order(str(order_id))
        return []

    def _fail_closed_unprotected(
        self, position: dict, actual_position: dict, failures: list[ExecutionResult]
    ) -> list[ExecutionResult]:
        try:
            close = self.client.submit_order(
                ExecutionOrder(
                    side="SHORT" if actual_position["type"] == "LONG" else "LONG",
                    order_type="market",
                    quantity=float(actual_position["size"]),
                    reduce_only=True,
                    client_tag=self._tags(position)["flat"],
                )
            )
        except Exception as exc:
            close = ExecutionResult(False, "EMERGENCY_CLOSE_FAILED", message=str(exc))
        results = [*failures, close]
        try:
            remaining = self.client.get_position()
        except Exception as exc:
            self.confirmed_position = actual_position
            return [
                *results,
                ExecutionResult(False, "FLAT_RECHECK_UNCERTAIN", message=str(exc)),
            ]
        self.confirmed_position = remaining
        if remaining is None:
            tolerance = max(1e-12, float(actual_position["size"]) * 1e-6)
            if close.accepted and close.filled_quantity + tolerance >= float(actual_position["size"]):
                return results
            remaining = actual_position
        elif (
            remaining.get("type") != actual_position.get("type")
            or float(remaining.get("size") or 0.0)
            > float(actual_position["size"]) + max(1e-12, float(actual_position["size"]) * 1e-6)
        ):
            return [
                *results,
                ExecutionResult(
                    False,
                    "FLAT_OWNERSHIP_UNPROVEN",
                    message="Emergency-close recheck returned a conflicting position; no further order was sent.",
                ),
            ]
        retry = ExecutionOrder(
            side="SHORT" if remaining["type"] == "LONG" else "LONG",
            order_type="stop",
            quantity=float(remaining["size"]),
            stop_price=float(position["sl"]),
            reduce_only=True,
            client_tag=self._tags(position)["stop"],
        )
        try:
            retry_results = self._replace_if_needed(None, retry, stop=True)
        except Exception as exc:
            retry_results = [ExecutionResult(False, "PROTECTION_FAILED", message=str(exc))]
        return [
            *results,
            ExecutionResult(
                False,
                "FLAT_NOT_CONVERGED" if self.confirmed_position is not None else "FLAT_RECHECK_UNCERTAIN",
                message="Emergency close was not confirmed flat; remaining quantity was re-protected.",
            ),
            *retry_results,
        ]

    def protection_status(self, position: dict, actual_position: Optional[dict] = None) -> dict:
        actual = actual_position if actual_position is not None else self.client.get_position()
        if actual is None or actual.get("type") != position.get("type"):
            return {"protected": False, "covered_qty": 0.0, "stop_id": None}
        quantity = float(actual.get("size") or 0.0)
        stop = next(
            (
                order
                for order in self.client.get_open_orders()
                if self._client_tag(order) == self._tags(position)["stop"]
            ),
            None,
        )
        covered = self._order_size(stop) if stop is not None else 0.0
        tolerance = max(1e-12, quantity * 1e-6)
        protected = bool(
            stop is not None
            and self._reduce_only(stop)
            and abs(covered - quantity) <= tolerance
            and abs(self._order_level(stop, stop=True) - float(position["sl"]))
            <= max(1e-8, abs(float(position["sl"])) * 1e-8)
        )
        return {
            "protected": protected,
            "covered_qty": covered,
            "stop_id": (stop.get("id") or stop.get("order_id")) if stop else None,
        }

    def submit_exit_orders(self, position: dict, actual_position: Optional[dict] = None) -> list[ExecutionResult]:
        if actual_position is None and hasattr(self.client, "get_position"):
            actual_position = self.client.get_position()
            if actual_position is None:
                return []
        actual_position = actual_position or position
        if actual_position.get("type") != position.get("type"):
            return [ExecutionResult(False, "POSITION_CONFLICT", message="Protective orders require a matching exchange position.")]

        exit_side = "SHORT" if position["type"] == "LONG" else "LONG"
        open_orders = getattr(self.client, "get_open_orders", lambda: [])()
        by_tag = {self._client_tag(order): order for order in open_orders}
        tags = self._tags(position)
        quantity = float(actual_position.get("size") or 0.0)
        if quantity <= 0:
            return []
        results = []
        stop_order = ExecutionOrder(
            side=exit_side,
            order_type="stop",
            quantity=quantity,
            stop_price=float(position["sl"]),
            reduce_only=True,
            leverage=float(position.get("leverage") or 0) or None,
            client_tag=tags["stop"],
        )
        try:
            stop_results = self._replace_if_needed(by_tag.get(tags["stop"]), stop_order, stop=True)
        except Exception as exc:
            stop_results = [ExecutionResult(False, "PROTECTION_FAILED", message=str(exc))]
        results.extend(stop_results)
        if any(not result.accepted for result in stop_results):
            return self._fail_closed_unprotected(position, actual_position, results)

        expected_tags = {tags["stop"], tags["tp1"], tags["tp2"]}
        for tag, stale in by_tag.items():
            if self._is_managed_tag(tag) and tag not in expected_tags and not tag.startswith("v8-entry-"):
                results.extend(self._cancel_if_present(stale))

        tp1_quantity = 0.0
        if not position.get("tp1_realized", False) and float(position.get("tp1_close_pct") or 0.0) > 0:
            tp1_quantity = min(quantity, float(position["size"]) * float(position["tp1_close_pct"]))
            tp1_order = ExecutionOrder(
                side=exit_side,
                order_type="limit",
                quantity=tp1_quantity,
                price=float(position["tp1"]),
                reduce_only=True,
                leverage=float(position.get("leverage") or 0) or None,
                client_tag=tags["tp1"],
            )
            results.extend(self._replace_if_needed(by_tag.get(tags["tp1"]), tp1_order, stop=False))
        else:
            results.extend(self._cancel_if_present(by_tag.get(tags["tp1"])))

        live_tp2 = position.get("live_tp2", position.get("tp2"))
        if live_tp2 is not None and float(live_tp2) > 0:
            tp2_quantity = quantity - tp1_quantity
            if tp2_quantity <= 0:
                return results
            tp2_order = ExecutionOrder(
                side=exit_side,
                order_type="limit",
                quantity=tp2_quantity,
                price=float(live_tp2),
                reduce_only=True,
                leverage=float(position.get("leverage") or 0) or None,
                client_tag=tags["tp2"],
            )
            results.extend(self._replace_if_needed(by_tag.get(tags["tp2"]), tp2_order, stop=False))
        else:
            results.extend(self._cancel_if_present(by_tag.get(tags["tp2"])))
        return results

    def reconcile_position(
        self, position: dict, *, allow_entry: bool, entry_tag: Optional[str] = None
    ) -> tuple[ExecutionResult, list[ExecutionResult]]:
        actual = self.client.get_position()
        self.confirmed_position = actual
        size_matches = False
        managed_position = False
        if actual is None and allow_entry:
            position["live_entry_tag"] = str(
                entry_tag
                or position.get("live_entry_tag")
                or f"v8-entry-{position.get('entry_mode', 'UNKNOWN')}"
            )[:32]
            entry_result = self.submit_entry_from_position(position)
            actual = self.client.get_position()
            confirmed_entry_quantity = self._confirmed_entry_quantity(entry_result)
            if actual is None and confirmed_entry_quantity > 0:
                actual = {"type": position["type"], "size": confirmed_entry_quantity}
            elif actual is None and entry_result.accepted:
                order_id = entry_result.exchange_order_id
                if not order_id or not hasattr(self.client, "cancel_order"):
                    return ExecutionResult(
                        False,
                        "ENTRY_CANCEL_UNCERTAIN",
                        exchange_order_id=order_id,
                        message="Unfilled managed entry could not be cancelled safely.",
                    ), []
                try:
                    self.client.cancel_order(order_id)
                    actual = self.client.get_position()
                except Exception as exc:
                    return ExecutionResult(
                        False,
                        "ENTRY_CANCEL_UNCERTAIN",
                        exchange_order_id=order_id,
                        message=str(exc),
                    ), []
                if actual is None:
                    return ExecutionResult(
                        False,
                        "ENTRY_CANCELLED_UNFILLED",
                        exchange_order_id=order_id,
                        message="Unfilled managed entry was cancelled; snapshot was not advanced.",
                    ), []
            if actual is not None and entry_result.accepted:
                actual_size = float(actual.get("size") or 0.0)
                tolerance = max(1e-12, actual_size * 1e-6)
                managed_position = bool(
                    actual.get("type") == position.get("type")
                    and confirmed_entry_quantity > 0
                    and abs(actual_size - confirmed_entry_quantity) <= tolerance
                )
                if not managed_position:
                    entry_result = ExecutionResult(
                        False,
                        "POSITION_OWNERSHIP_UNVERIFIED",
                        exchange_order_id=entry_result.exchange_order_id,
                        message="Observed position was not proven by fills from the submitted managed entry.",
                        filled_quantity=entry_result.filled_quantity,
                        average_price=entry_result.average_price,
                        fee=entry_result.fee,
                        fee_currency=entry_result.fee_currency,
                        timestamp=entry_result.timestamp,
                        exchange_trade_id=entry_result.exchange_trade_id,
                    )
            self.confirmed_position = actual
        elif actual is None:
            entry_result = ExecutionResult(False, "ENTRY_NOT_AUTHORIZED", message="Restart reconciliation will not recreate an absent entry.")
        elif actual.get("type") != position.get("type"):
            entry_result = ExecutionResult(False, "POSITION_CONFLICT", message="Opposite exchange position requires manual reconciliation.")
        else:
            expected = float(position.get("remaining_size", position["size"]))
            actual_size = float(actual.get("size") or 0.0)
            size_matches = abs(expected - actual_size) <= max(1e-12, expected * 1e-6)
            managed_position = bool(
                not allow_entry
                and size_matches
                and self._is_managed_tag(str(position.get("live_entry_tag") or ""))
                and self.protection_status(position, actual)["protected"]
            )
            if managed_position:
                entry_result = ExecutionResult(True, "ALREADY_IN_SYNC", message=f"strategy={expected} exchange={actual_size}")
            else:
                status = "POSITION_SIZE_MISMATCH" if not size_matches else "POSITION_OWNERSHIP_UNVERIFIED"
                entry_result = ExecutionResult(False, status, message=f"strategy={expected} exchange={actual_size}")
        should_protect = bool(
            actual is not None
            and actual.get("type") == position.get("type")
            and managed_position
        )
        exits = self.submit_exit_orders(position, actual) if should_protect else []
        if should_protect and all(result.accepted for result in exits):
            self.last_protection_status = self.protection_status(position, actual)
            if not self.last_protection_status["protected"]:
                exits.extend(
                    self._fail_closed_unprotected(
                        position,
                        actual,
                        [
                            ExecutionResult(
                                False,
                                "PROTECTION_UNVERIFIED",
                                message="Confirmed quantity did not have a verifiable equal reduce-only stop.",
                            )
                        ],
                    )
                )
        return entry_result, exits

    def reconcile_flat(self, previous_position: Optional[dict]) -> tuple[ExecutionResult, list[ExecutionResult]]:
        actual = self.client.get_position()
        managed_orders = [
            order for order in self.client.get_open_orders() if self._is_managed_tag(self._client_tag(order))
        ]
        if actual is None:
            results = []
            for order in managed_orders:
                results.extend(self._cancel_if_present(order))
            if any(not result.accepted for result in results):
                return ExecutionResult(False, "FLAT_RECONCILIATION_FAILED"), results
            return ExecutionResult(True, "ALREADY_FLAT"), results

        expected = previous_position or {}
        expected_size = float(expected.get("remaining_size", expected.get("size") or 0.0))
        actual_size = float(actual.get("size") or 0.0)
        tag = str(expected.get("live_entry_tag") or "")
        tolerance = max(1e-12, expected_size * 1e-6)
        if (
            not self._is_managed_tag(tag)
            or actual.get("type") != expected.get("type")
            or abs(actual_size - expected_size) > tolerance
            or not self.protection_status(expected, actual)["protected"]
        ):
            return ExecutionResult(
                False,
                "FLAT_OWNERSHIP_UNPROVEN",
                message="Position side, size, and managed entry tag must match before automatic flattening.",
            ), []

        close = self.client.submit_order(
            ExecutionOrder(
                side="SHORT" if actual["type"] == "LONG" else "LONG",
                order_type="market",
                quantity=actual_size,
                reduce_only=True,
                client_tag=self._tags(expected)["flat"],
            )
        )
        if not close.accepted:
            return ExecutionResult(False, "FLAT_CLOSE_FAILED", message=close.message), [close]
        remaining = self.client.get_position()
        if remaining is not None:
            exits = self.submit_exit_orders(expected, remaining)
            return ExecutionResult(
                False,
                "FLAT_NOT_CONVERGED",
                exchange_order_id=close.exchange_order_id,
                message="Reduce-only close left a position; remaining quantity was re-protected.",
                filled_quantity=close.filled_quantity,
                average_price=close.average_price,
                fee=close.fee,
                fee_currency=close.fee_currency,
                timestamp=close.timestamp,
            ), [close, *exits]
        results = [close]
        for order in managed_orders:
            results.extend(self._cancel_if_present(order))
        if any(not result.accepted for result in results):
            return ExecutionResult(False, "FLAT_RECONCILIATION_FAILED"), results
        return ExecutionResult(
            True,
            "FLAT_CONVERGED",
            exchange_order_id=close.exchange_order_id,
            filled_quantity=close.filled_quantity,
            average_price=close.average_price,
            fee=close.fee,
            fee_currency=close.fee_currency,
            timestamp=close.timestamp,
        ), results

    def collect_fills(self, results: list[ExecutionResult], known_order_ids=()) -> tuple[list[dict], list[str]]:
        order_ids = {str(value) for value in known_order_ids if value}
        order_ids.update(str(result.exchange_order_id) for result in results if result.exchange_order_id)
        try:
            open_orders = self.client.get_open_orders()
        except Exception:
            open_orders = []
        order_ids.update(
            str(order.get("id") or order.get("order_id"))
            for order in open_orders
            if self._is_managed_tag(self._client_tag(order)) and (order.get("id") or order.get("order_id"))
        )
        try:
            fills = list(getattr(self.client, "get_fills", lambda _: [])(order_ids))
        except Exception:
            fills = []
        trade_orders = {str(fill.get("order_id") or "") for fill in fills}
        for result in results:
            order_id = str(result.exchange_order_id or "")
            if result.filled_quantity <= 0 or not order_id or order_id in trade_orders:
                continue
            fills.append(
                {
                    "fill_id": result.exchange_trade_id or f"order:{order_id}",
                    "order_id": order_id,
                    "client_tag": "",
                    "quantity": result.filled_quantity,
                    "average_price": result.average_price,
                    "fee": result.fee,
                    "fee_currency": result.fee_currency,
                    "timestamp": result.timestamp or datetime.now(timezone.utc).isoformat(),
                }
            )
        return fills, sorted(order_ids)

    @staticmethod
    def merge_fills(existing: list[dict], current: list[dict]) -> list[dict]:
        by_id = {str(fill["fill_id"]): fill for fill in existing}
        trade_orders = {
            str(fill.get("order_id") or "")
            for fill in [*existing, *current]
            if not str(fill["fill_id"]).startswith("order:")
        }
        for fill in current:
            fill_id = str(fill["fill_id"])
            order_id = str(fill.get("order_id") or "")
            if fill_id.startswith("order:") and order_id in trade_orders:
                continue
            if not fill_id.startswith("order:"):
                by_id.pop(f"order:{order_id}", None)
            by_id[fill_id] = fill
        return list(by_id.values())
