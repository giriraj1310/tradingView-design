"""Trend-following strategy: hold names trading above their long SMA.

Economic rationale: time-series momentum / under-reaction — instruments that
have risen tend to keep rising over weeks-to-months. Crisis-aware: positions
are dropped when price falls below the trend line. Equal-weight across the
names currently in an uptrend; sizing/scaling is left to the risk manager.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import pandas as pd


class TrendFollowing:
    def __init__(self, sma_window: int = 200, base_gross: float = 1.0):
        self.sma_window = int(sma_window)
        self.base_gross = float(base_gross)
        self.name = "trend"
        self.warmup = self.sma_window + 1

    def target_weights(
        self,
        history: Dict[str, pd.DataFrame],
        asof: Optional[datetime] = None,
    ) -> Dict[str, float]:
        in_trend = []
        for sym, df in history.items():
            close = df["close"]
            if len(close) < self.sma_window:
                continue
            sma = close.iloc[-self.sma_window:].mean()
            last = close.iloc[-1]
            if pd.notna(sma) and pd.notna(last) and last > sma:
                in_trend.append(sym)

        if not in_trend:
            return {}
        w = self.base_gross / len(in_trend)
        return {sym: w for sym in in_trend}
