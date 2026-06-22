"""Broker interface. BacktestBroker and IBKRBroker both implement this so the
strategy + risk code is identical across backtest, paper, and live."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Protocol

from ..types import Account, Fill, Order


class Broker(Protocol):
    def is_connected(self) -> bool:
        ...

    def account(self) -> Account:
        ...

    def latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        ...

    def place_order(self, order: Order) -> Optional[Fill]:
        ...
