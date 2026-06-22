"""End-to-end test of the live/paper cycle using a FAKE broker (no IBKR).

This proves the full path — connect, reconcile, data, strategy, risk, execution,
idempotency — works without a broker connection.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from trader.config import AppConfig, RiskPolicy
from trader.loop import run_cycle
from trader.store import OrderStore
from trader.types import Account, Fill, Position


class FakeBroker:
    """Implements the broker interface in memory. Records placed orders."""

    def __init__(self, equity=100000.0, positions=None, prices=None, history=None):
        self._equity = equity
        self._positions = positions or {}
        self._prices = prices or {}
        self._history = history or {}
        self.placed = []
        self.account_id = "DU-FAKE"
        self._connected = False

    def connect_with_retry(self, **kw):
        self._connected = True
        return self

    def connect(self, **kw):
        self._connected = True
        return self

    def is_connected(self):
        return self._connected

    def disconnect(self):
        self._connected = False

    def account(self):
        return Account(cash=self._equity, equity=self._equity,
                       positions=dict(self._positions),
                       timestamp=datetime.now(timezone.utc))

    def get_history(self, symbols, days):
        return {s: self._history[s] for s in symbols if s in self._history}

    def latest_prices(self, symbols):
        return {s: self._prices[s] for s in symbols if s in self._prices}

    def place_order(self, order):
        self.placed.append(order)
        # simulate an immediate fill so expected_positions tracks it
        return type("T", (), {"orderStatus": type("S", (), {"status": "Filled"})()})()


def _uptrend_history(symbol="SPY", n=320):
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * (1 + np.linspace(0, 0.6, n))
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    return df


def _cfg(tmp_path):
    cfg = AppConfig(universe=["SPY"], sma_window=200, base_gross=1.0)
    cfg.state_file = str(tmp_path / "state.json")
    cfg.store_db = ":memory:"
    return cfg


def test_dry_run_places_nothing_but_computes_orders(tmp_path):
    hist = {"SPY": _uptrend_history()}
    broker = FakeBroker(prices={"SPY": float(hist["SPY"]["close"].iloc[-1])}, history=hist)
    store = OrderStore(":memory:")
    cfg = _cfg(tmp_path)
    res = run_cycle(cfg, RiskPolicy(), broker=broker, store=store,
                    dry_run=True, asof=datetime(2026, 6, 22, tzinfo=timezone.utc))
    assert res["dry_run"] is True
    assert broker.placed == []          # nothing transmitted
    assert len(res["orders"]) >= 1      # but a real order was computed


def test_live_send_places_orders_and_is_idempotent(tmp_path):
    hist = {"SPY": _uptrend_history()}
    price = float(hist["SPY"]["close"].iloc[-1])
    store = OrderStore(":memory:")
    cfg = _cfg(tmp_path)
    asof = datetime(2026, 6, 22, tzinfo=timezone.utc)

    broker1 = FakeBroker(prices={"SPY": price}, history=hist)
    res1 = run_cycle(cfg, RiskPolicy(), broker=broker1, store=store,
                     dry_run=False, asof=asof)
    assert len(broker1.placed) >= 1
    assert res1["skipped_idempotent"] == 0

    # Simulate a restart BEFORE the fills reflect in the broker view (still
    # flat). The same orders get regenerated with the same client_ids and MUST
    # be skipped rather than re-sent.
    broker2 = FakeBroker(prices={"SPY": price}, history=hist)
    res2 = run_cycle(cfg, RiskPolicy(), broker=broker2, store=store,
                     dry_run=False, asof=asof)
    assert broker2.placed == []                 # idempotent: nothing re-sent
    assert res2["skipped_idempotent"] >= 1


def test_reconcile_drift_is_reported(tmp_path):
    hist = {"SPY": _uptrend_history()}
    price = float(hist["SPY"]["close"].iloc[-1])
    store = OrderStore(":memory:")
    # store recorded a prior fill of 10 SPY...
    store.record_fill(Fill("SPY", 10, price, 1.0, datetime.now(timezone.utc), "c0"))
    # ...but the broker actually reports 25 SPY (drift of +15)
    broker = FakeBroker(prices={"SPY": price}, history=hist,
                        positions={"SPY": Position("SPY", 25, price)})
    cfg = _cfg(tmp_path)
    res = run_cycle(cfg, RiskPolicy(), broker=broker, store=store,
                    dry_run=True, asof=datetime(2026, 6, 22, tzinfo=timezone.utc))
    drift = {d["symbol"]: d for d in res["reconcile_discrepancies"]}
    assert "SPY" in drift
    assert drift["SPY"]["expected"] == 10 and drift["SPY"]["actual"] == 25
