"""The paper/live trading cycle — the real-world counterpart of the backtest.

It mirrors the design's main trading loop:
    safety preconditions -> reconnect -> read truth (reconcile) -> fresh data ->
    strategy intention -> risk veto/sizing -> idempotent execution -> log.

The broker and store are INJECTABLE, so the entire cycle is testable with a
fake broker (no IBKR needed). The SAME strategy + risk objects used in backtest
are used here; only the data source and broker differ. Run with dry_run=True to
compute and log orders WITHOUT sending them — always do this first.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .config import AppConfig, RiskPolicy
from .reconcile import reconcile_positions
from .risk.manager import RiskManager
from .risk.state import RiskState
from .store import OrderStore
from .strategies import build as build_strategy
from .types import Order


def _client_id(order: Order, asof: str) -> str:
    """Deterministic id: re-deriving the same order on the same day yields the
    same id, so a restart/reconnect cannot double-send it."""
    return f"{asof}:{order.symbol}:{order.action}:{order.quantity}"


def _connect(broker) -> None:
    fn = getattr(broker, "connect_with_retry", None) or broker.connect
    fn()


def run_cycle(
    cfg: AppConfig,
    policy: RiskPolicy,
    broker=None,
    store: Optional[OrderStore] = None,
    dry_run: bool = True,
    logger: logging.Logger = None,
    asof: Optional[datetime] = None,
) -> dict:
    log = logger or logging.getLogger("trader")
    now = asof or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    strategy = build_strategy(
        cfg.strategy_name, sma_window=cfg.sma_window, base_gross=cfg.base_gross
    )
    risk = RiskManager(policy)

    own_broker = broker is None
    own_store = store is None
    if own_broker:
        from .execution.ibkr_broker import IBKRBroker

        broker = IBKRBroker(cfg.ibkr)
    if own_store:
        store = OrderStore(cfg.store_db)

    log.info("Connecting to broker ...")
    _connect(broker)
    try:
        # 1. read truth from the broker (source of truth) + reconcile
        account = broker.account()
        broker_pos = {s: p.quantity for s, p in account.positions.items()}
        discrepancies = reconcile_positions(broker_pos, store.expected_positions())
        for d in discrepancies:
            log.warning(
                "RECONCILE drift %s: local expected=%d, broker actual=%d (delta %+d)"
                " — trusting broker.",
                d.symbol, d.expected, d.actual, d.delta,
            )
        log.info(
            "Account %s equity=%.2f cash=%.2f positions=%s",
            getattr(broker, "account_id", "?"), account.equity, account.cash, broker_pos,
        )

        state = RiskState.load_or_init(cfg.state_file, account.equity, today)

        # 2. fresh data from the broker
        history = broker.get_history(cfg.universe, cfg.history_days)
        if not history:
            raise RuntimeError("No history returned from broker; aborting cycle.")
        prices = broker.latest_prices(cfg.universe)

        # 3. strategy intention (pure) -> 4. risk veto / sizing
        desired = strategy.target_weights(history, asof=now)
        orders, decision = risk.build_orders(
            desired, history, account, state, latest_prices=prices, asof=now
        )
        log.info("Risk decision: %s", json.dumps(decision))
        store.record_decision(decision)

        # 5. idempotent execution
        sent: List[dict] = []
        skipped = 0
        for order in orders:
            order.client_id = _client_id(order, today)
            if store.already_sent(order.client_id):
                skipped += 1
                log.info("Skipping already-sent order %s", order.client_id)
                continue
            if dry_run:
                log.info("[DRY-RUN] would send: %s", order)
                store.record_order(order, "dry_run", dry_run=True)
            else:
                trade = broker.place_order(order)
                status = getattr(getattr(trade, "orderStatus", None), "status", "submitted")
                log.info("Sent %s %s x%d -> %s", order.action, order.symbol,
                         order.quantity, status)
                store.record_order(order, status, dry_run=False)
            sent.append({"symbol": order.symbol, "action": order.action,
                         "qty": order.quantity, "reason": order.reason})

        state.save(cfg.state_file)
        return {
            "decision": decision,
            "orders": sent,
            "skipped_idempotent": skipped,
            "reconcile_discrepancies": [
                {"symbol": d.symbol, "expected": d.expected, "actual": d.actual}
                for d in discrepancies
            ],
            "dry_run": dry_run,
        }
    finally:
        if own_broker:
            broker.disconnect()
            log.info("Disconnected from broker.")
        if own_store:
            store.close()
