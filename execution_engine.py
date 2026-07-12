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

    @classmethod
    def from_environment(cls, exchange: str, symbol: str, *, sandbox: bool = True):
        prefix = exchange.upper()
        return cls(
            exchange,
            symbol,
            api_key=os.getenv(f"{prefix}_API_KEY"),
            secret=os.getenv(f"{prefix}_API_SECRET"),
            password=os.getenv(f"{prefix}_API_PASSWORD"),
            sandbox=sandbox,
        )

    def _amount(self, amount: float) -> float:
        value = float(self.exchange.amount_to_precision(self.symbol, amount))
        minimum = self.market.get("limits", {}).get("amount", {}).get("min")
        if value <= 0 or (minimum is not None and value < float(minimum)):
            raise ValueError(f"order quantity {amount} is below exchange minimum")
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
            self.exchange.set_leverage(float(order.leverage), self.symbol)
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
        )

    def cancel_all(self) -> None:
        self.exchange.cancel_all_orders(self.symbol)

    def get_open_orders(self) -> list[dict]:
        return self.exchange.fetch_open_orders(self.symbol)

    def get_position(self) -> Optional[dict]:
        positions = self.exchange.fetch_positions([self.symbol])
        for position in positions:
            contracts = float(position.get("contracts") or 0)
            if contracts <= 0:
                continue
            side = str(position.get("side") or "").upper()
            if side not in {"LONG", "SHORT"}:
                continue
            return {
                "type": "LONG" if side == "LONG" else "SHORT",
                "size": contracts,
                "entry_price": float(position.get("entryPrice") or 0),
                "leverage": float(position.get("leverage") or 0),
            }
        return None


class LiveExecutionEngine:
    def __init__(self, client):
        self.client = client

    def submit_entry_from_position(self, position: dict) -> ExecutionResult:
        existing = self.client.get_position()
        if existing is not None:
            if existing.get("type") == position.get("type"):
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
        order_type = "market" if position.get("entry_mode") == "BREAKOUT" else "limit"
        return self.client.submit_order(
            ExecutionOrder(
                side=position["type"],
                order_type=order_type,
                quantity=float(position["size"]),
                price=float(position["entry_price"]),
                leverage=float(position.get("leverage") or 0) or None,
                client_tag=f"entry:{position.get('entry_mode', 'UNKNOWN')}",
            )
        )

    def submit_exit_orders(self, position: dict) -> list[ExecutionResult]:
        exit_side = "SHORT" if position["type"] == "LONG" else "LONG"
        open_orders = getattr(self.client, "get_open_orders", lambda: [])()
        tags = {
            str(order.get("clientOrderId") or order.get("client_order_id") or order.get("info", {}).get("clientOrderId") or "")
            for order in open_orders
        }
        results = []
        if "protective-stop" not in tags:
            results.append(
                self.client.submit_order(
                    ExecutionOrder(
                        side=exit_side,
                        order_type="stop",
                        quantity=float(position["size"]),
                        stop_price=float(position["sl"]),
                        reduce_only=True,
                        leverage=float(position.get("leverage") or 0) or None,
                        client_tag="protective-stop",
                    )
                )
            )
        if float(position.get("tp2", 0.0)) > 0:
            if "take-profit" not in tags:
                results.append(
                    self.client.submit_order(
                        ExecutionOrder(
                            side=exit_side,
                            order_type="limit",
                            quantity=float(position["size"]),
                            price=float(position["tp2"]),
                            reduce_only=True,
                            leverage=float(position.get("leverage") or 0) or None,
                            client_tag="take-profit",
                        )
                    )
                )
        return results
