"""The paper/live trading cycle — the real-world counterpart of the backtest.

It mirrors the design's main trading loop:
    safety preconditions -> read truth (reconcile) -> fresh data ->
    strategy intention -> risk veto/sizing -> idempotent execution -> log.

The SAME strategy + risk objects used in backtest are injected here; only the
data source and broker (IBKR) differ. Run with dry_run=True to compute and log
orders WITHOUT sending them — always do this first against paper.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List

from .config import AppConfig, RiskPolicy
from .execution.ibkr_broker import IBKRBroker
from .risk.manager import RiskManager
from .risk.state import RiskState
from .strategies import build as build_strategy
from .types import Order


def _client_id(order: Order, asof: str) -> str:
    return f"{asof}:{order.symbol}:{order.action}:{order.quantity}"


def run_cycle(
    cfg: AppConfig,
    policy: RiskPolicy,
    dry_run: bool = True,
    logger: logging.Logger = None,
) -> dict:
    log = logger or logging.getLogger("trader")
    strategy = build_strategy(
        cfg.strategy_name, sma_window=cfg.sma_window, base_gross=cfg.base_gross
    )
    risk = RiskManager(policy)
    broker = IBKRBroker(cfg.ibkr)

    log.info("Connecting to IBKR %s:%s ...", cfg.ibkr.host, cfg.ibkr.port)
    broker.connect()
    try:
        # 1. read truth from the broker (source of truth)
        account = broker.account()
        log.info(
            "Account %s  equity=%.2f cash=%.2f positions=%s",
            broker.account_id, account.equity, account.cash,
            {s: p.quantity for s, p in account.positions.items()},
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = RiskState.load_or_init(cfg.state_file, account.equity, today)

        # 2. fresh data (history + latest prices) from the broker
        history = broker.get_history(cfg.universe, cfg.history_days)
        if not history:
            raise RuntimeError("No history returned from IBKR; aborting cycle.")
        prices = broker.latest_prices(cfg.universe)

        # 3. strategy intention (pure)
        desired = strategy.target_weights(history, asof=datetime.now())

        # 4. risk veto / sizing -> approved orders
        orders, decision = risk.build_orders(
            desired, history, account, state, latest_prices=prices,
            asof=datetime.now(),
        )
        log.info("Risk decision: %s", json.dumps(decision))

        # 5. execution (idempotent client ids)
        sent: List[dict] = []
        for order in orders:
            order.client_id = _client_id(order, today)
            if dry_run:
                log.info("[DRY-RUN] would send: %s", order)
            else:
                trade = broker.place_order(order)
                status = getattr(getattr(trade, "orderStatus", None), "status", "?")
                log.info("Sent %s %s x%d -> %s", order.action, order.symbol,
                         order.quantity, status)
            sent.append(
                {"symbol": order.symbol, "action": order.action,
                 "qty": order.quantity, "reason": order.reason}
            )

        state.save(cfg.state_file)
        return {"decision": decision, "orders": sent, "dry_run": dry_run}
    finally:
        broker.disconnect()
        log.info("Disconnected from IBKR.")
