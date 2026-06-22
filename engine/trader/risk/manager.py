"""Risk manager — the gatekeeper with final authority over signals.

Takes desired strategy weights + current account + price history and produces
risk-approved orders (or vetoes). Enforces, in order:

  1. circuit breakers (global kill switch, hard/soft drawdown, daily loss)
  2. per-name weight caps and max position count
  3. volatility targeting (scale the whole book toward target vol; never lever)
  4. gross-exposure cap
  5. translation of target weights -> integer share deltas (orders)

A strategy can scream "buy"; this layer can still say no. Every decision is
returned in a structured `decision` dict for the audit log.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..config import RiskPolicy
from ..types import Account, Order
from .state import RiskState

TRADING_DAYS = 252


def drawdown(equity: float, high_water_mark: float) -> float:
    """Negative number, e.g. -0.12 for a 12% drawdown."""
    if high_water_mark <= 0:
        return 0.0
    return (equity / high_water_mark) - 1.0


class RiskManager:
    def __init__(self, policy: RiskPolicy):
        self.policy = policy

    def build_orders(
        self,
        desired: Dict[str, float],
        history: Dict[str, pd.DataFrame],
        account: Account,
        state: RiskState,
        latest_prices: Dict[str, float],
        asof: Optional[datetime] = None,
    ) -> Tuple[List[Order], dict]:
        p = self.policy
        desired = dict(desired)
        dd = drawdown(account.equity, state.high_water_mark)
        daily = 0.0
        if state.day_start_equity > 0:
            daily = (account.equity / state.day_start_equity) - 1.0

        # --- 1. circuit breakers ---------------------------------------
        mode = "normal"
        if p.global_kill_switch or dd <= -p.drawdown_hard_pct:
            desired = {}  # flatten everything
            mode = "halt_flatten"
        elif dd <= -p.drawdown_soft_pct:
            desired = {s: w * 0.5 for s, w in desired.items()}
            mode = "soft_derisk"
        elif daily <= -p.max_daily_loss_pct:
            mode = "no_new_risk"  # enforced after sizing

        # --- 2. per-name caps + max positions --------------------------
        capped = {s: min(w, p.max_weight_single_etf) for s, w in desired.items()}
        if len(capped) > p.max_positions:
            top = sorted(capped.items(), key=lambda kv: -kv[1])[: p.max_positions]
            capped = dict(top)

        # --- 3. volatility targeting -----------------------------------
        vol_scale = self._vol_scale(capped, history)
        capped = {s: w * vol_scale for s, w in capped.items()}

        # --- 4. gross-exposure cap -------------------------------------
        gross = sum(capped.values())
        if gross > p.max_gross_exposure and gross > 0:
            f = p.max_gross_exposure / gross
            capped = {s: w * f for s, w in capped.items()}

        # --- 5. target weights -> target shares ------------------------
        symbols = set(capped) | set(account.positions)
        target_shares: Dict[str, int] = {}
        for s in symbols:
            price = latest_prices.get(s)
            if not price or price <= 0:
                target_shares[s] = account.position_qty(s)  # can't price -> leave
                continue
            tw = capped.get(s, 0.0)
            target_shares[s] = int((tw * account.equity) // price)

        if mode == "no_new_risk":
            for s, tgt in target_shares.items():
                cur = account.position_qty(s)
                if abs(tgt) > abs(cur):  # don't increase exposure
                    target_shares[s] = cur

        # --- 6. diff vs current -> orders ------------------------------
        orders: List[Order] = []
        for s in sorted(symbols):
            cur = account.position_qty(s)
            delta = target_shares[s] - cur
            if delta == 0:
                continue
            price = latest_prices.get(s) or 0.0
            if abs(delta) * price < p.min_trade_notional:
                continue
            orders.append(
                Order(
                    symbol=s,
                    action="BUY" if delta > 0 else "SELL",
                    quantity=abs(delta),
                    order_type="MKT",
                    reason=mode,
                )
            )

        decision = {
            "asof": str(asof) if asof else None,
            "mode": mode,
            "equity": round(account.equity, 2),
            "drawdown": round(dd, 4),
            "daily_pnl": round(daily, 4),
            "vol_scale": round(vol_scale, 4),
            "desired_weights": {k: round(v, 4) for k, v in desired.items()},
            "target_weights": {k: round(v, 4) for k, v in capped.items()},
            "n_orders": len(orders),
        }
        return orders, decision

    def _vol_scale(
        self,
        weights: Dict[str, float],
        history: Dict[str, pd.DataFrame],
        lookback: int = 20,
    ) -> float:
        """Scale the book so its recent realized vol ~= target. Capped at 1.0:
        we reduce risk in turbulent markets but never add leverage."""
        if not weights:
            return 1.0
        port_ret: Optional[pd.Series] = None
        for s, w in weights.items():
            df = history.get(s)
            if df is None or len(df) < lookback + 1:
                continue
            r = df["close"].pct_change().iloc[-lookback:] * w
            port_ret = r if port_ret is None else port_ret.add(r, fill_value=0.0)
        if port_ret is None:
            return 1.0
        daily_vol = float(port_ret.std())
        if not math.isfinite(daily_vol) or daily_vol <= 0:
            return 1.0
        realized_annual = daily_vol * math.sqrt(TRADING_DAYS)
        if realized_annual <= 0:
            return 1.0
        return min(self.policy.target_annual_vol / realized_annual, 1.0)
