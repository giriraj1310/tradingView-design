"""Options paper/live cycle for the LEAPS-trend strategy.

Maintains a single long-call line on the underlying:
  * trend up + currently flat        -> BUY to open a LEAPS call
  * trend broke OR near expiry       -> SELL to close
  * kill-switch / hard drawdown / disabled -> close everything, open nothing

Defined-risk by construction (we only ever BUY calls). Dependency-injected
broker + store, so it is testable with a fake broker (no IBKR needed). Dry-run
by default — always paper-test before --live-send.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from ..config import AppConfig, RiskPolicy
from ..risk.manager import drawdown
from ..risk.state import RiskState
from ..store import OrderStore
from . import strategy as S
from .types import OptionOrder


def _client_id(order: OptionOrder, day: str) -> str:
    return f"{day}:{order.contract.key()}:{order.action}:{order.quantity}"


def _connect(broker) -> None:
    fn = getattr(broker, "connect_with_retry", None) or broker.connect
    fn()


def run_options_cycle(
    cfg: AppConfig,
    policy: RiskPolicy,
    broker=None,
    store: Optional[OrderStore] = None,
    dry_run: bool = True,
    logger: logging.Logger = None,
    asof: Optional[datetime] = None,
) -> dict:
    log = logger or logging.getLogger("trader")
    oc = cfg.options
    now = asof or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    asof_date = now.date()

    own_broker = broker is None
    own_store = store is None
    if own_broker:
        from ..execution.ibkr_broker import IBKRBroker

        broker = IBKRBroker(cfg.ibkr)
    if own_store:
        store = OrderStore(cfg.store_db)

    log.info("Connecting to broker (options cycle) ...")
    _connect(broker)
    try:
        account = broker.account()
        state = RiskState.load_or_init(cfg.state_file, account.equity, today)

        # risk gate: disabled / manual kill / hard drawdown -> flatten & stand down
        dd = drawdown(account.equity, state.high_water_mark)
        halt = (not oc.enabled) or policy.global_kill_switch or dd <= -policy.drawdown_hard_pct
        if halt:
            log.warning("Options halt active (enabled=%s kill=%s dd=%.3f) -> flatten only.",
                        oc.enabled, policy.global_kill_switch, dd)

        # trend on the underlying
        history = broker.get_history([oc.underlying], cfg.history_days)
        close = history.get(oc.underlying)
        if close is None or "close" not in close:
            raise RuntimeError(f"No history for {oc.underlying}.")
        close = close["close"]
        trend_up = (not halt) and S.is_uptrend(close, cfg.sma_window)
        spot = float(close.iloc[-1])

        # current long calls we manage on this underlying
        held = [p for p in broker.option_positions()
                if p.contract.symbol == oc.underlying
                and p.contract.right == oc.right and p.quantity > 0]

        orders: List[OptionOrder] = []

        # --- exits ----------------------------------------------------
        for p in held:
            if halt or S.should_exit(p.contract, asof_date, trend_up, oc):
                orders.append(OptionOrder(
                    contract=p.contract, action="SELL", quantity=p.quantity,
                    reason="halt" if halt else "exit",
                ))

        # a held line is "kept" only if we are NOT exiting it
        keeping = [p for p in held
                   if not (halt or S.should_exit(p.contract, asof_date, trend_up, oc))]

        # --- entry (only if trend up and we hold nothing we're keeping) ---
        target_info = None
        if trend_up and not keeping:
            chain = broker.option_chain(oc.underlying)  # (expirations, strikes)
            expirations, strikes = chain
            target = S.select_target(spot, True, expirations, strikes, asof_date, oc)
            if target is not None:
                quote = broker.option_quote(target)
                price = quote.mid or quote.ask or quote.last
                n = S.size_contracts(account.equity, price, oc)
                target_info = {"contract": target.key(), "price": price,
                               "contracts": n, "spot": spot}
                if n > 0 and price:
                    limit = round(price * (1 + oc.limit_buffer), 2)
                    orders.append(OptionOrder(
                        contract=target, action="BUY", quantity=n,
                        order_type="LMT", limit_price=limit, reason="open_leaps",
                    ))
                else:
                    log.warning("Skip entry: contracts=%s price=%s", n, price)

        decision = {
            "asof": today, "underlying": oc.underlying, "trend_up": trend_up,
            "halt": halt, "spot": round(spot, 2), "equity": round(account.equity, 2),
            "drawdown": round(dd, 4), "held": [p.contract.key() for p in held],
            "target": target_info, "n_orders": len(orders),
        }
        log.info("Options decision: %s", json.dumps(decision))
        store.record_decision(decision)

        # --- idempotent execution ------------------------------------
        sent, skipped = [], 0
        for order in orders:
            order.client_id = _client_id(order, today)
            if store.already_sent(order.client_id):
                skipped += 1
                log.info("Skipping already-sent option order %s", order.client_id)
                continue
            if dry_run:
                log.info("[DRY-RUN] would send: %s %s x%d @ %s",
                         order.action, order.contract.key(), order.quantity,
                         order.limit_price)
                store.record_order(order, "dry_run", dry_run=True)
            else:
                trade = broker.place_option_order(order)
                status = getattr(getattr(trade, "orderStatus", None), "status", "submitted")
                log.info("Sent %s %s x%d -> %s", order.action,
                         order.contract.key(), order.quantity, status)
                store.record_order(order, status, dry_run=False)
            sent.append({"contract": order.contract.key(), "action": order.action,
                         "qty": order.quantity, "limit": order.limit_price,
                         "reason": order.reason})

        state.save(cfg.state_file)
        return {"decision": decision, "orders": sent,
                "skipped_idempotent": skipped, "dry_run": dry_run}
    finally:
        if own_broker:
            broker.disconnect()
            log.info("Disconnected from broker.")
        if own_store:
            store.close()
