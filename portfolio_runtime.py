from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class SymbolPortfolio:
    strategy: str
    initial_margin_budget: float
    min_strategy_amount: float
    strategy_amount: Optional[float] = None
    halted: bool = False
    halt_notified: bool = False

    def __post_init__(self) -> None:
        if not self.strategy:
            raise ValueError("strategy is required")
        if self.initial_margin_budget <= 0:
            raise ValueError("initial_margin_budget must be positive")
        if self.min_strategy_amount < 0:
            raise ValueError("min_strategy_amount cannot be negative")
        if self.strategy_amount is None:
            self.strategy_amount = self.initial_margin_budget
        if self.strategy_amount < 0:
            raise ValueError("strategy_amount cannot be negative")
        if self.strategy_amount < self.min_strategy_amount:
            self.halted = True


class PortfolioAccount:
    """Track independent, compounding margin budgets per symbol."""

    def __init__(self, account_balance: float, symbols: dict[str, SymbolPortfolio]):
        if account_balance <= 0:
            raise ValueError("account_balance must be positive")
        if not symbols:
            raise ValueError("at least one symbol allocation is required")
        allocated = sum(item.initial_margin_budget for item in symbols.values())
        if allocated > account_balance:
            raise ValueError("symbol margin budgets exceed account balance")
        self.account_balance = float(account_balance)
        self.reserve = float(account_balance - allocated)
        self.symbols = symbols

    @classmethod
    def from_config(cls, account_balance: float, config: dict[str, dict[str, float]]):
        for symbol, values in config.items():
            if not values.get("strategy"):
                raise ValueError(f"{symbol} must define exactly one strategy")
        return cls(
            account_balance,
            {
                symbol: SymbolPortfolio(
                    strategy=str(values["strategy"]),
                    initial_margin_budget=float(values["margin_budget"]),
                    min_strategy_amount=float(values["min_strategy_amount"]),
                )
                for symbol, values in config.items()
            },
        )

    @property
    def unallocated_balance(self) -> float:
        return self.reserve

    def add_symbol(
        self,
        symbol: str,
        *,
        strategy: str,
        margin_budget: float,
        min_strategy_amount: float,
    ) -> None:
        if symbol in self.symbols:
            raise ValueError(f"symbol {symbol} already has a strategy")
        if margin_budget > self.unallocated_balance:
            raise ValueError("margin budget exceeds unallocated balance")
        self.symbols[symbol] = SymbolPortfolio(
            strategy=strategy,
            initial_margin_budget=margin_budget,
            min_strategy_amount=min_strategy_amount,
        )
        self.reserve -= margin_budget

    def remove_symbol(self, symbol: str, *, has_open_position: bool = False) -> float:
        if has_open_position:
            raise ValueError("cannot remove a symbol with an open position")
        portfolio = self.symbols.pop(symbol)
        amount = float(portfolio.strategy_amount or 0.0)
        self.reserve += amount
        return amount

    @classmethod
    def from_snapshot(cls, snapshot: dict):
        symbols = {
            symbol: SymbolPortfolio(strategy=values.get("strategy", "nfe-v2"), **{k: v for k, v in values.items() if k != "strategy"})
            for symbol, values in snapshot["symbols"].items()
        }
        account = cls(float(snapshot["account_balance"]), symbols)
        account.reserve = float(snapshot.get("reserve", account.reserve))
        return account

    def strategy_amount(self, symbol: str) -> float:
        return float(self.symbols[symbol].strategy_amount or 0.0)

    def can_open_new_position(self, symbol: str) -> bool:
        portfolio = self.symbols[symbol]
        return not portfolio.halted and self.strategy_amount(symbol) >= portfolio.min_strategy_amount

    def apply_realized_pnl(self, symbol: str, net_pnl: float) -> Optional[dict]:
        portfolio = self.symbols[symbol]
        portfolio.strategy_amount = max(0.0, self.strategy_amount(symbol) + float(net_pnl))
        if portfolio.strategy_amount >= portfolio.min_strategy_amount:
            return None
        portfolio.halted = True
        if portfolio.halt_notified:
            return None
        portfolio.halt_notified = True
        return {
            "event_type": "STRATEGY_HALTED_MIN_AMOUNT",
            "symbol": symbol,
            "strategy_amount": portfolio.strategy_amount,
            "min_strategy_amount": portfolio.min_strategy_amount,
            "reason": "realized_strategy_amount_below_minimum",
        }

    def snapshot(self) -> dict:
        return {
            "account_balance": self.account_balance,
            "reserve": self.reserve,
            "symbols": {symbol: asdict(item) for symbol, item in self.symbols.items()},
        }


def parse_symbol_allocations(value: str) -> dict[str, dict[str, float]]:
    """Parse ``BTC=300:100,ETH=400:100`` into portfolio config."""
    result: dict[str, dict[str, float]] = {}
    for item in value.split(","):
        symbol, amounts = item.split("=", 1)
        margin, minimum = amounts.split(":", 1)
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        result[symbol] = {
            "strategy": "nfe-v2",
            "margin_budget": float(margin),
            "min_strategy_amount": float(minimum),
        }
    return result
