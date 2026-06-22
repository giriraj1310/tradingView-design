"""Shared synthetic-data fixtures so tests never depend on the network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_series(prices, start="2020-01-01"):
    """Build an OHLCV DataFrame from a close-price array (open=prev close)."""
    idx = pd.bdate_range(start=start, periods=len(prices))
    close = np.asarray(prices, dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": np.full(len(close), 1_000_000.0),
        },
        index=idx,
    )


@pytest.fixture
def uptrend():
    # 300 days, steady uptrend with mild noise
    n = 300
    base = 100 * (1.0 + np.linspace(0, 0.6, n))
    noise = np.sin(np.linspace(0, 30, n)) * 0.5
    return make_series(base + noise)


@pytest.fixture
def downtrend():
    n = 300
    base = 200 * (1.0 - np.linspace(0, 0.4, n))
    return make_series(base)
