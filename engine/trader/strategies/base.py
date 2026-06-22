"""Strategy interface.

A strategy is a PURE function of price history -> target portfolio weights.
No I/O, no broker calls, no order placement. This is what makes strategies
unit-testable and reusable identically across backtest, paper, and live.

A strategy returns an *intention* (e.g. {"SPY": 0.5}); translating that into
actual orders is the risk manager's and execution engine's job.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

try:  # Protocol available 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore


class Strategy(Protocol):
    name: str
    warmup: int  # minimum bars required before emitting signals

    def target_weights(
        self,
        history: Dict[str, pd.DataFrame],
        asof: Optional[datetime] = None,
    ) -> Dict[str, float]:
        ...
