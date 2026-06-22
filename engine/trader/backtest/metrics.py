"""Performance metrics computed from a daily equity curve."""
from __future__ import annotations

import math
from typing import Dict

import pandas as pd

TRADING_DAYS = 252


def compute_metrics(equity: pd.Series) -> Dict[str, float]:
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    rets = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    years = max(len(equity) / TRADING_DAYS, 1e-9)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0)
    ann_vol = float(rets.std() * math.sqrt(TRADING_DAYS))
    sharpe = float(rets.mean() / rets.std() * math.sqrt(TRADING_DAYS)) if rets.std() > 0 else 0.0
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "days": int(len(equity)),
    }
