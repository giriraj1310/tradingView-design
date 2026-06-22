"""Interactive Brokers adapter (paper or live) built on ib_insync.

Requires a running TWS or IB Gateway with the API enabled. For PAPER trading,
log into a paper account in IB Gateway and use port 4002 (or TWS paper 7497).

This adapter is deliberately conservative:
  * the broker is the source of truth — account/positions are always re-read;
  * historical bars are used for prices (works without a realtime data
    subscription, which is ideal for a daily strategy);
  * connection problems raise clear, actionable errors.

ib_insync runs on Python 3.9 (used here). On Python 3.10+ prefer `ib_async`
(a drop-in fork) — change the imports below from `ib_insync` to `ib_async`.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from ..config import IBKRConfig
from ..types import Account, Order, Position


class IBKRError(RuntimeError):
    pass


class IBKRBroker:
    def __init__(self, cfg: IBKRConfig):
        self.cfg = cfg
        self._ib = None
        self._account: Optional[str] = cfg.account

    # --- lifecycle -----------------------------------------------------
    def connect(self, timeout: float = 15.0) -> "IBKRBroker":
        try:
            from ._ibapi import IB
        except ImportError as e:  # pragma: no cover
            raise IBKRError(str(e)) from e

        ib = IB()
        try:
            ib.connect(
                self.cfg.host,
                self.cfg.port,
                clientId=self.cfg.client_id,
                readonly=self.cfg.readonly,
                timeout=timeout,
            )
        except Exception as e:
            raise IBKRError(
                f"Could not connect to IBKR at {self.cfg.host}:{self.cfg.port} "
                f"(clientId={self.cfg.client_id}). Is IB Gateway/TWS running with "
                f"the API enabled and this port/clientId allowed? Original: {e}"
            ) from e

        self._ib = ib
        accounts = ib.managedAccounts()
        if not self._account:
            self._account = accounts[0] if accounts else ""
        return self

    def connect_with_retry(
        self, attempts: int = 5, backoff: float = 2.0, timeout: float = 15.0
    ) -> "IBKRBroker":
        """Connect, retrying with exponential backoff. On a disconnect mid-run,
        callers should re-read positions/open orders (reconcile) before acting."""
        delay = backoff
        last: Optional[Exception] = None
        for i in range(1, attempts + 1):
            try:
                return self.connect(timeout=timeout)
            except IBKRError as e:
                last = e
                if i >= attempts:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
        raise IBKRError(f"Failed to connect after {attempts} attempts: {last}")

    def ensure_connected(self) -> "IBKRBroker":
        if not self.is_connected():
            return self.connect_with_retry()
        return self

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def disconnect(self) -> None:
        if self._ib is not None:
            self._ib.disconnect()

    @property
    def account_id(self) -> str:
        return self._account or ""

    # --- reads ---------------------------------------------------------
    def account(self) -> Account:
        ib = self._require()
        summary = {av.tag: av.value for av in ib.accountSummary(self._account or "")}
        net_liq = _f(summary.get("NetLiquidation"))
        cash = _f(summary.get("TotalCashValue"))
        positions: Dict[str, Position] = {}
        for p in ib.positions(self._account or ""):
            sym = p.contract.symbol
            positions[sym] = Position(sym, int(p.position), float(p.avgCost))
        return Account(cash=cash, equity=net_liq, positions=positions,
                       timestamp=datetime.utcnow())

    def latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        ib = self._require()
        out: Dict[str, float] = {}
        for s in symbols:
            try:
                bars = ib.reqHistoricalData(
                    self._stock(s), endDateTime="", durationStr="3 D",
                    barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
                )
                if bars:
                    out[s] = float(bars[-1].close)
            except Exception:
                continue
        return out

    def get_history(self, symbols: List[str], days: int) -> Dict[str, pd.DataFrame]:
        ib = self._require()
        dur = f"{max(int(days), 30)} D"
        out: Dict[str, pd.DataFrame] = {}
        for s in symbols:
            bars = ib.reqHistoricalData(
                self._stock(s), endDateTime="", durationStr=dur,
                barSizeSetting="1 day", whatToShow="ADJUSTED_LAST", useRTH=True,
            )
            if not bars:
                continue
            df = pd.DataFrame(
                {
                    "open": [b.open for b in bars],
                    "high": [b.high for b in bars],
                    "low": [b.low for b in bars],
                    "close": [b.close for b in bars],
                    "volume": [b.volume for b in bars],
                },
                index=pd.to_datetime([b.date for b in bars]),
            ).sort_index()
            out[s] = df
        return out

    def open_orders(self):
        return self._require().reqAllOpenOrders()

    # --- writes --------------------------------------------------------
    def place_order(self, order: Order):
        from ._ibapi import LimitOrder, MarketOrder

        ib = self._require()
        contract = self._stock(order.symbol)
        if order.order_type == "LMT" and order.limit_price:
            ib_order = LimitOrder(order.action, order.quantity, order.limit_price)
        else:
            ib_order = MarketOrder(order.action, order.quantity)
        ib_order.tif = order.tif
        if self._account:
            ib_order.account = self._account
        if order.client_id:
            # human-readable tag for the audit trail
            ib_order.orderRef = order.client_id
        trade = ib.placeOrder(contract, ib_order)
        ib.sleep(1)  # let the status come back
        return trade

    # --- internals -----------------------------------------------------
    def _stock(self, symbol: str):
        from ._ibapi import Stock

        c = Stock(symbol, "SMART", "USD")
        self._require().qualifyContracts(c)
        return c

    def _require(self):
        if not self.is_connected():
            raise IBKRError("Not connected. Call connect() first.")
        return self._ib


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
