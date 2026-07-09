from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class ExecutionOrder:
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: bool = False
    client_tag: str = "codex-runtime"


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    status: str
    exchange_order_id: Optional[str] = None
    message: str = ""


class ExchangeExecutionClient(Protocol):
    def submit_order(self, order: ExecutionOrder) -> ExecutionResult:
        ...

    def cancel_all(self) -> None:
        ...

    def get_position(self) -> Optional[dict]:
        ...


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


class LiveExecutionEngine:
    def __init__(self, client: ExchangeExecutionClient):
        self.client = client

    def submit_entry_from_position(self, position: dict) -> ExecutionResult:
        order_type = "market" if position.get("entry_mode") == "BREAKOUT" else "limit"
        return self.client.submit_order(
            ExecutionOrder(
                side=position["type"],
                order_type=order_type,
                quantity=float(position["size"]),
                price=float(position["entry_price"]),
                client_tag=f"entry:{position.get('entry_mode', 'UNKNOWN')}",
            )
        )

    def submit_exit_orders(self, position: dict) -> list[ExecutionResult]:
        exit_side = "SHORT" if position["type"] == "LONG" else "LONG"
        results = [
            self.client.submit_order(
                ExecutionOrder(
                    side=exit_side,
                    order_type="stop",
                    quantity=float(position["size"]),
                    stop_price=float(position["sl"]),
                    reduce_only=True,
                    client_tag="protective-stop",
                )
            )
        ]
        if float(position.get("tp2", 0.0)) > 0:
            results.append(
                self.client.submit_order(
                    ExecutionOrder(
                        side=exit_side,
                        order_type="limit",
                        quantity=float(position["size"]),
                        price=float(position["tp2"]),
                        reduce_only=True,
                        client_tag="take-profit",
                    )
                )
            )
        return results
