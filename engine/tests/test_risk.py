import numpy as np

from trader.config import RiskPolicy
from trader.risk.manager import RiskManager, drawdown
from trader.risk.state import RiskState
from trader.types import Account, Position


def _flat_history(symbols, n=60, price=100.0):
    import pandas as pd

    idx = pd.bdate_range("2021-01-01", periods=n)
    out = {}
    for s in symbols:
        # very low vol so vol-targeting does not shrink positions in these tests
        close = price * (1 + np.cumsum(np.random.RandomState(1).normal(0, 1e-4, n)))
        out[s] = pd.DataFrame({"close": close, "open": close}, index=idx)
    return out


def test_per_name_cap_enforced():
    pol = RiskPolicy(max_weight_single_etf=0.20, target_annual_vol=10.0)  # huge target -> no vol shrink
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    acct = Account(cash=100000, equity=100000, positions={})
    state = RiskState.initialize(100000, "d")
    orders, dec = rm.build_orders({"AAA": 0.9}, hist, acct, state, {"AAA": 100.0})
    # 20% cap on 100k / $100 = 200 shares max
    buy = next(o for o in orders if o.symbol == "AAA")
    assert buy.quantity <= 200
    assert dec["target_weights"]["AAA"] <= 0.20 + 1e-9


def test_max_positions_keeps_top_n():
    pol = RiskPolicy(max_positions=2, max_weight_single_etf=1.0, target_annual_vol=10.0)
    rm = RiskManager(pol)
    syms = ["A", "B", "C", "D"]
    hist = _flat_history(syms)
    acct = Account(cash=100000, equity=100000, positions={})
    state = RiskState.initialize(100000, "d")
    desired = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}
    _, dec = rm.build_orders(desired, hist, acct, state, {s: 100.0 for s in syms})
    assert set(dec["target_weights"]) == {"A", "B"}


def test_hard_drawdown_flattens():
    pol = RiskPolicy(drawdown_hard_pct=0.15, target_annual_vol=10.0)
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    # hold 500 shares, equity dropped 20% below HWM
    acct = Account(cash=50000, equity=80000,
                   positions={"AAA": Position("AAA", 500, 100.0)})
    state = RiskState(high_water_mark=100000, day_start_equity=100000, day="d")
    orders, dec = rm.build_orders({"AAA": 1.0}, hist, acct, state, {"AAA": 100.0})
    assert dec["mode"] == "halt_flatten"
    sell = next(o for o in orders if o.symbol == "AAA")
    assert sell.action == "SELL" and sell.quantity == 500  # flatten


def test_daily_loss_blocks_new_risk():
    pol = RiskPolicy(max_daily_loss_pct=0.02, target_annual_vol=10.0)
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    # down 3% on the day, currently flat -> must not open new longs
    acct = Account(cash=97000, equity=97000, positions={})
    state = RiskState(high_water_mark=100000, day_start_equity=100000, day="d")
    orders, dec = rm.build_orders({"AAA": 0.5}, hist, acct, state, {"AAA": 100.0})
    assert dec["mode"] == "no_new_risk"
    assert orders == []


def test_vol_targeting_scales_down_high_vol():
    import pandas as pd

    pol = RiskPolicy(target_annual_vol=0.10, max_weight_single_etf=1.0)
    rm = RiskManager(pol)
    n = 60
    idx = pd.bdate_range("2021-01-01", periods=n)
    # very high vol series (~5% daily) -> realized vol >> target -> scale < 1
    rng = np.random.RandomState(0)
    close = 100 * (1 + np.cumsum(rng.normal(0, 0.05, n)))
    hist = {"AAA": pd.DataFrame({"close": close, "open": close}, index=idx)}
    acct = Account(cash=100000, equity=100000, positions={})
    state = RiskState.initialize(100000, "d")
    _, dec = rm.build_orders({"AAA": 1.0}, hist, acct, state, {"AAA": float(close[-1])})
    assert dec["vol_scale"] < 1.0
    assert dec["target_weights"]["AAA"] < 1.0


def test_no_trade_band_skips_small_drift():
    # target ~20% but already holding ~18% (2pp drift < 5pp band) -> no trade
    pol = RiskPolicy(max_weight_single_etf=1.0, target_annual_vol=10.0,
                     no_trade_band=0.05)
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    acct = Account(cash=82000, equity=100000,
                   positions={"AAA": Position("AAA", 180, 100.0)})  # 18% weight
    state = RiskState.initialize(100000, "d")
    orders, _ = rm.build_orders({"AAA": 0.20}, hist, acct, state, {"AAA": 100.0})
    assert orders == []


def test_no_trade_band_allows_large_drift():
    pol = RiskPolicy(max_weight_single_etf=1.0, target_annual_vol=10.0,
                     no_trade_band=0.05)
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    # holding 5%, target 20% -> 15pp drift > band -> should trade
    acct = Account(cash=95000, equity=100000,
                   positions={"AAA": Position("AAA", 50, 100.0)})
    state = RiskState.initialize(100000, "d")
    orders, _ = rm.build_orders({"AAA": 0.20}, hist, acct, state, {"AAA": 100.0})
    assert any(o.symbol == "AAA" and o.action == "BUY" for o in orders)


def test_no_trade_band_never_blocks_full_exit():
    # signal dropped the name (target 0); band must NOT keep the position
    pol = RiskPolicy(max_weight_single_etf=1.0, no_trade_band=0.05)
    rm = RiskManager(pol)
    hist = _flat_history(["AAA"])
    acct = Account(cash=98000, equity=100000,
                   positions={"AAA": Position("AAA", 20, 100.0)})  # 2% weight
    state = RiskState.initialize(100000, "d")
    orders, _ = rm.build_orders({}, hist, acct, state, {"AAA": 100.0})
    sell = next(o for o in orders if o.symbol == "AAA")
    assert sell.action == "SELL" and sell.quantity == 20


def test_drawdown_helper():
    assert abs(drawdown(80, 100) - (-0.2)) < 1e-9
    assert drawdown(120, 100) > 0
