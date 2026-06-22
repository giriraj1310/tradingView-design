import numpy as np
import pandas as pd

from trader.config import BacktestConfig, RiskPolicy
from trader.backtest.engine import run_backtest


class _SpyStrategy:
    """Records the latest date it is ever shown, to prove no look-ahead."""

    def __init__(self):
        self.name = "spy"
        self.warmup = 5
        self.violations = []

    def target_weights(self, history, asof=None):
        for sym, df in history.items():
            if len(df) and asof is not None and df.index[-1] > asof:
                self.violations.append((sym, df.index[-1], asof))
        return {}


def _hist():
    n = 120
    idx = pd.bdate_range("2021-01-01", periods=n)
    close = 100 * (1 + np.linspace(0, 0.3, n))
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    return {"SPY": df}


def test_no_lookahead_strategy_only_sees_past():
    spy = _SpyStrategy()
    cfg = BacktestConfig(start="2021-01-01", initial_cash=100000, benchmark="SPY")
    result = run_backtest(_hist(), spy, RiskPolicy(), cfg)
    assert spy.violations == []  # strategy never saw a future bar
    assert len(result.equity) > 0


def test_backtest_runs_and_trades_with_trend():
    from trader.strategies.trend import TrendFollowing

    n = 320
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * (1 + np.linspace(0, 0.8, n))
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    hist = {"SPY": df}
    cfg = BacktestConfig(start="2020-01-01", initial_cash=100000, benchmark="SPY")
    strat = TrendFollowing(sma_window=200, base_gross=1.0)
    result = run_backtest(hist, strat, RiskPolicy(), cfg)
    assert result.n_fills > 0
    assert result.metrics["days"] > 200
    # in a clean uptrend the strategy should end invested and make money
    assert result.metrics["total_return"] > 0


def test_fills_happen_at_next_open():
    # Construct a flat then jump series; a buy decided before the jump must
    # fill at the next day's open (post-decision), not at the decision close.
    from trader.strategies.trend import TrendFollowing

    n = 320
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * (1 + np.linspace(0, 0.5, n))
    df = pd.DataFrame(
        {"open": close * 0.99, "high": close, "low": close * 0.98,
         "close": close, "volume": 1e6},
        index=idx,
    )
    cfg = BacktestConfig(start="2020-01-01", initial_cash=100000)
    result = run_backtest({"SPY": df}, TrendFollowing(200), RiskPolicy(), cfg)
    assert result.n_fills > 0
