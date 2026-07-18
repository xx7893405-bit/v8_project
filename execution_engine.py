from __future__ import annotations

import os
from dataclasses import dataclass
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
        return ExecutionResult(
            accepted=True,
            status=str(result.get("status") or "accepted").upper(),
            exchange_order_id=str(result.get("id")) if result.get("id") else None,
            message=f"{self.exchange_name} {order_type} {ccxt_side} {amount}",
            filled_quantity=float(result.get("filled") or 0.0) * float(self.market.get("contractSize") or 1.0),
            average_price=float(result.get("average") or 0.0) or None,
        )

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


class LiveExecutionEngine:
    def __init__(self, client):
        self.client = client

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
                    accepted=True,
                    status="ALREADY_IN_SYNC",
                    message="An exchange position with the same side already exists; entry skipped.",
                )
            return ExecutionResult(
                accepted=False,
                status="POSITION_CONFLICT",
                message="An opposite exchange position exists; manual reconciliation required.",
            )
        entry_tag = str(position.get("live_entry_tag") or f"entry:{position.get('entry_mode', 'UNKNOWN')}")[:32]
        if any(self._client_tag(order) == entry_tag for order in self.client.get_open_orders()):
            return ExecutionResult(
                accepted=True,
                status="ENTRY_PENDING",
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
            client_tag="protective-stop",
        )
        results.extend(self._replace_if_needed(by_tag.get("protective-stop"), stop_order, stop=True))

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
                client_tag="take-profit-1",
            )
            results.extend(self._replace_if_needed(by_tag.get("take-profit-1"), tp1_order, stop=False))
        else:
            results.extend(self._cancel_if_present(by_tag.get("take-profit-1")))

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
                client_tag="take-profit",
            )
            results.extend(self._replace_if_needed(by_tag.get("take-profit"), tp2_order, stop=False))
        else:
            results.extend(self._cancel_if_present(by_tag.get("take-profit")))
        return results

    def reconcile_position(self, position: dict, *, allow_entry: bool) -> tuple[ExecutionResult, list[ExecutionResult]]:
        actual = self.client.get_position()
        size_matches = False
        if actual is None and allow_entry:
            entry_result = self.submit_entry_from_position(position)
            actual = self.client.get_position()
        elif actual is None:
            entry_result = ExecutionResult(False, "ENTRY_NOT_AUTHORIZED", message="Restart reconciliation will not recreate an absent entry.")
        elif actual.get("type") != position.get("type"):
            entry_result = ExecutionResult(False, "POSITION_CONFLICT", message="Opposite exchange position requires manual reconciliation.")
        else:
            expected = float(position.get("remaining_size", position["size"]))
            actual_size = float(actual.get("size") or 0.0)
            size_matches = abs(expected - actual_size) <= max(1e-12, expected * 1e-6)
            status = "ALREADY_IN_SYNC" if size_matches else "POSITION_SIZE_MISMATCH"
            entry_result = ExecutionResult(status == "ALREADY_IN_SYNC", status, message=f"strategy={expected} exchange={actual_size}")
        managed_position = bool(position.get("live_entry_tag")) or allow_entry
        exits = (
            self.submit_exit_orders(position, actual)
            if actual is not None
            and actual.get("type") == position.get("type")
            and (size_matches or managed_position)
            else []
        )
        return entry_result, exits
