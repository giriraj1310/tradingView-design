import numpy as np
import pandas as pd

from trader.backtest.walkforward import walk_forward
from trader.config import BacktestConfig, RiskPolicy
from trader.strategies.trend import TrendFollowing


def _long_history(years=8):
    n = 252 * years
    idx = pd.bdate_range("2010-01-01", periods=n)
    # gentle uptrend + cycle so different SMAs actually differ
    t = np.linspace(0, 1, n)
    close = 100 * (1 + 0.8 * t) + 8 * np.sin(np.linspace(0, 12 * np.pi, n))
    df = pd.DataFrame(
        {"open": close, "high": close * 1.001, "low": close * 0.999,
         "close": close, "volume": 1e6},
        index=idx,
    )
    return {"SPY": df}


def test_walk_forward_runs_and_stitches_oos():
    hist = _long_history(years=8)
    cfg = BacktestConfig(start="2010-01-01", initial_cash=100000, benchmark="SPY")
    grid = [{"sma_window": w} for w in (50, 100, 200)]
    factory = lambda **p: TrendFollowing(sma_window=p["sma_window"])
    res = walk_forward(hist, factory, grid, RiskPolicy(), cfg,
                       train_years=3, test_years=1, step_years=1)

    assert len(res.folds) >= 3
    # each fold selected a parameter from the grid
    for f in res.folds:
        assert f.best_param["sma_window"] in (50, 100, 200)
    # stitched OOS curve exists and has metrics
    assert len(res.oos_equity) > 0
    assert "max_drawdown" in res.oos_metrics


def test_walk_forward_oos_period_after_first_train():
    hist = _long_history(years=8)
    cfg = BacktestConfig(start="2010-01-01", initial_cash=100000)
    grid = [{"sma_window": 100}]
    factory = lambda **p: TrendFollowing(sma_window=p["sma_window"])
    res = walk_forward(hist, factory, grid, RiskPolicy(), cfg,
                       train_years=3, test_years=1, step_years=1)
    # first OOS test must start at/after the first 3y train window ends (~2013)
    assert pd.to_datetime(res.folds[0].test_start).year >= 2012
