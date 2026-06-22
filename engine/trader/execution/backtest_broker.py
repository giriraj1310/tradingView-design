"""Simulated broker for backtesting, with explicit (pessimistic) costs.

Fills are applied by the backtest engine at the *next* bar's price (t -> t+1),
plus slippage, plus commission. This broker holds cash/positions and never
peeks at the future itself; the engine controls the fill price.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from ..types import Account, Fill, Order, Position


class BacktestBroker:
    def __init__(
        self,
        cash: float,
        commission_per_share: float = 0.005,
        min_commission: float = 1.0,
        slippage_bps: float = 5.0,
    ):
        self.cash = float(cash)
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission
        self.slippage_bps = slippage_bps
        self.positions: Dict[str, Position] = {}
        self.fills: List[Fill] = []

    def is_connected(self) -> bool:
        return True

    def account(self, mark_prices: Optional[Dict[str, float]] = None) -> Account:
        mark_prices = mark_prices or {}
        equity = self.cash
        for sym, pos in self.positions.items():
            px = mark_prices.get(sym, pos.avg_cost)
            equity += pos.quantity * px
        return Account(
            cash=self.cash,
            equity=equity,
            positions={s: Position(p.symbol, p.quantity, p.avg_cost) for s, p in self.positions.items()},
        )

    def latest_prices(self, symbols: List[str]) -> Dict[str, float]:  # pragma: no cover
        raise NotImplementedError("Backtest prices are supplied by the engine.")

    def execute(self, order: Order, base_price: float, timestamp: datetime) -> Fill:
        """Apply a fill at base_price adjusted for slippage + commission."""
        side = 1 if order.action == "BUY" else -1
        slip = base_price * (self.slippage_bps / 1e4) * side
        fill_price = base_price + slip
        signed = order.signed_qty()
        commission = max(self.min_commission, abs(signed) * self.commission_per_share)

        self.cash -= signed * fill_price + commission
        self._apply_to_position(order.symbol, signed, fill_price)

        fill = Fill(
            symbol=order.symbol,
            quantity=signed,
            price=fill_price,
            commission=commission,
            timestamp=timestamp,
            order_client_id=order.client_id,
        )
        self.fills.append(fill)
        return fill

    def _apply_to_position(self, symbol: str, signed_qty: int, price: float) -> None:
        pos = self.positions.get(symbol, Position(symbol))
        new_qty = pos.quantity + signed_qty
        if pos.quantity == 0 or (pos.quantity > 0) == (signed_qty > 0):
            # opening or adding in the same direction -> weighted avg cost
            total_cost = pos.avg_cost * abs(pos.quantity) + price * abs(signed_qty)
            pos.avg_cost = total_cost / abs(new_qty) if new_qty != 0 else 0.0
        elif new_qty == 0:
            pos.avg_cost = 0.0
        elif (new_qty > 0) != (pos.quantity > 0):
            # flipped sides -> remaining lot is at the new fill price
            pos.avg_cost = price
        pos.quantity = new_qty
        if new_qty == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = pos
