from datetime import datetime, timezone

from trader.reconcile import reconcile_positions
from trader.store import OrderStore
from trader.types import Fill, Order


def test_reconcile_detects_drift():
    d = reconcile_positions({"SPY": 100, "QQQ": 50}, {"SPY": 100, "QQQ": 40})
    assert len(d) == 1
    assert d[0].symbol == "QQQ"
    assert d[0].expected == 40 and d[0].actual == 50 and d[0].delta == 10


def test_reconcile_clean_when_matching():
    assert reconcile_positions({"SPY": 100}, {"SPY": 100}) == []


def test_reconcile_handles_missing_symbols():
    d = reconcile_positions({"SPY": 100}, {})  # broker has it, store didn't expect it
    assert len(d) == 1 and d[0].expected == 0 and d[0].actual == 100


def test_store_idempotency_live_only():
    store = OrderStore(":memory:")
    o = Order(symbol="SPY", action="BUY", quantity=10, client_id="2026-06-22:SPY:BUY:10")
    assert store.already_sent(o.client_id) is False
    store.record_order(o, "dry_run", dry_run=True)
    assert store.already_sent(o.client_id) is False  # dry-run does not count
    store.record_order(o, "submitted", dry_run=False)
    assert store.already_sent(o.client_id) is True   # live send now blocks duplicates


def test_store_expected_positions_from_fills():
    store = OrderStore(":memory:")
    ts = datetime.now(timezone.utc)
    store.record_fill(Fill("SPY", 10, 100.0, 1.0, ts, "c1"))
    store.record_fill(Fill("SPY", 5, 101.0, 1.0, ts, "c2"))
    store.record_fill(Fill("QQQ", -3, 200.0, 1.0, ts, "c3"))
    pos = store.expected_positions()
    assert pos == {"SPY": 15, "QQQ": -3}
