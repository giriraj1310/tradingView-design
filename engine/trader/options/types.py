"""Option domain types. Broker-agnostic; the IBKR adapter maps to/from these."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


def parse_expiry(s: str) -> date:
    """Parse an IBKR-style expiry 'YYYYMMDD'."""
    return datetime.strptime(str(s), "%Y%m%d").date()


def dte(expiry: str, asof: date) -> int:
    """Calendar days to expiry."""
    return (parse_expiry(expiry) - asof).days


@dataclass(frozen=True)
class OptionContract:
    symbol: str          # underlying, e.g. "SPY"
    expiry: str          # "YYYYMMDD"
    strike: float
    right: str           # "C" or "P"
    multiplier: int = 100
    exchange: str = "SMART"
    currency: str = "USD"

    def key(self) -> str:
        # e.g. SPY-20271217-C-500.0  (stable id for logging/idempotency)
        return f"{self.symbol}-{self.expiry}-{self.right}-{self.strike:g}"


@dataclass
class OptionQuote:
    contract: OptionContract
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    delta: Optional[float] = None
    iv: Optional[float] = None

    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask and self.bid > 0 and self.ask > 0:
            return round((self.bid + self.ask) / 2.0, 2)
        return self.last if (self.last and self.last > 0) else None


@dataclass
class OptionPosition:
    contract: OptionContract
    quantity: int        # signed (long calls are positive)
    avg_cost: float = 0.0  # per-share premium (IBKR avgCost is per contract; adapter normalizes)


@dataclass
class OptionOrder:
    contract: OptionContract
    action: str          # "BUY" or "SELL"
    quantity: int        # positive
    order_type: str = "LMT"
    limit_price: Optional[float] = None
    tif: str = "DAY"
    client_id: str = ""
    reason: str = ""

    @property
    def symbol(self) -> str:
        # so the audit store (duck-typed on .symbol) can log option orders too
        return self.contract.key()
