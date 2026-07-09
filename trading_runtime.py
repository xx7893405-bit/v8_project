from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class PaperTradingConfig:
    data_source: str = "csv"
    poll_interval_seconds: int = 60
    cycles: int = 1
    state_path: str = "paper_trading_state.json"
    journal_path: str = "paper_trading_journal.json"


@dataclass(frozen=True)
class LiveTradingConfig:
    exchange: str = "binance"
    symbol: str = "BTCUSDT"
    dry_run: bool = True
    allow_new_entries: bool = True
    close_on_shutdown: bool = False


@dataclass
class RuntimeSnapshot:
    mode: str
    as_of: Optional[str]
    balance: float
    active_position: Optional[dict]
    pending_retest_order: Optional[dict]
    pending_breakout_order: Optional[dict]
    latest_trade: Optional[dict]
    latest_missed: Optional[dict]
    trade_count: int
    missed_count: int

    def to_dict(self) -> dict:
        return asdict(self)
