"""LEAPS-trend options strategy — pure, testable selection/sizing/exit logic.

Idea: when the underlying is in an uptrend (price > long SMA), hold a single
long-dated, slightly in-the-money CALL as a *defined-risk* leveraged trend
position (max loss = premium paid). When the trend breaks or the option nears
expiry, close it. No selling, no naked exposure, no legs to manage.

All functions here are pure (no I/O), so they unit-test without a broker.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, Sequence

import pandas as pd

from ..config import OptionsConfig
from .types import OptionContract, dte


def is_uptrend(close: pd.Series, window: int) -> bool:
    if len(close) < window:
        return False
    sma = close.iloc[-window:].mean()
    last = close.iloc[-1]
    return bool(pd.notna(sma) and pd.notna(last) and last > sma)


def select_expiry(expirations: Sequence[str], asof: date, cfg: OptionsConfig) -> Optional[str]:
    """Pick the nearest expiry that is at least `min_dte` out (a LEAPS). If none
    reach min_dte, take the longest-dated available."""
    dated = sorted((dte(e, asof), e) for e in expirations)
    in_range = [(d, e) for d, e in dated if cfg.min_dte <= d <= cfg.max_dte]
    if in_range:
        return min(in_range)[1]          # nearest within [min_dte, max_dte]
    at_least_min = [(d, e) for d, e in dated if d >= cfg.min_dte]
    if at_least_min:
        return min(at_least_min)[1]       # nearest beyond min_dte
    return dated[-1][1] if dated else None  # fall back to the longest available


def select_strike(strikes: Sequence[float], spot: float, cfg: OptionsConfig) -> Optional[float]:
    """Pick the listed strike closest to the target moneyness (ITM for calls)."""
    if not strikes:
        return None
    target = spot * cfg.target_moneyness
    return min(strikes, key=lambda k: abs(k - target))


def select_target(
    spot: float,
    trend_up: bool,
    expirations: Sequence[str],
    strikes: Sequence[float],
    asof: date,
    cfg: OptionsConfig,
) -> Optional[OptionContract]:
    """The contract we want to hold, or None if we should be flat."""
    if not trend_up or spot <= 0:
        return None
    expiry = select_expiry(expirations, asof, cfg)
    strike = select_strike(strikes, spot, cfg)
    if expiry is None or strike is None:
        return None
    return OptionContract(symbol=cfg.underlying, expiry=expiry, strike=strike,
                          right=cfg.right)


def size_contracts(equity: float, premium_per_share: float, cfg: OptionsConfig) -> int:
    """Number of contracts so total premium <= max_premium_pct of equity.
    Premium per CONTRACT = premium_per_share * 100 (the multiplier)."""
    if premium_per_share is None or premium_per_share <= 0 or equity <= 0:
        return 0
    budget = cfg.max_premium_pct * equity
    cost_per_contract = premium_per_share * 100
    n = int(budget // cost_per_contract)
    return max(0, min(n, cfg.max_contracts))


def should_exit(contract: OptionContract, asof: date, trend_up: bool,
                cfg: OptionsConfig) -> bool:
    """Close the position if the trend broke or expiry is near (roll window)."""
    if not trend_up:
        return True
    return dte(contract.expiry, asof) < cfg.roll_dte
