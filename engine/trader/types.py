"""Core domain types shared across backtest, paper, and live.

These are deliberately simple, broker-agnostic dataclasses. The execution
adapters translate them to/from broker-specific objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class Order:
    """An order *intention* approved by the risk manager. Quantity is always
    positive; direction is carried by `action`."""

    symbol: str
    action: str  # "BUY" or "SELL"
    quantity: int
    order_type: str = "MKT"  # "MKT" or "LMT"
    limit_price: Optional[float] = None
    tif: str = "DAY"
    client_id: str = ""
    reason: str = ""  # why this order exists (audit trail / risk mode)

    def signed_qty(self) -> int:
        return self.quantity if self.action == "BUY" else -self.quantity


@dataclass
class Fill:
    symbol: str
    quantity: int  # signed
    price: float
    commission: float
    timestamp: datetime
    order_client_id: str = ""


@dataclass
class Position:
    symbol: str
    quantity: int = 0  # signed
    avg_cost: float = 0.0


@dataclass
class Account:
    cash: float
    equity: float  # net liquidation value
    positions: Dict[str, Position] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def position_qty(self, symbol: str) -> int:
        pos = self.positions.get(symbol)
        return pos.quantity if pos else 0
