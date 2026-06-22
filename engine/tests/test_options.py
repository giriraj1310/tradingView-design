from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from trader.config import AppConfig, OptionsConfig, RiskPolicy
from trader.options import strategy as S
from trader.options.loop import run_options_cycle
from trader.options.types import OptionContract, OptionPosition, OptionQuote, dte
from trader.store import OrderStore


# ---- pure strategy logic ------------------------------------------------

def _chain(asof):
    # expiries at ~30, ~400, ~500, ~900 DTE
    exps = [(asof + pd.Timedelta(days=d)).strftime("%Y%m%d") for d in (30, 400, 500, 900)]
    strikes = [float(s) for s in range(400, 601, 5)]
    return exps, strikes


def test_select_expiry_picks_nearest_leaps():
    asof = date(2026, 1, 1)
    exps, _ = _chain(asof)
    cfg = OptionsConfig(min_dte=365, max_dte=730)
    chosen = S.select_expiry(exps, asof, cfg)
    assert 365 <= dte(chosen, asof) <= 730
    # of the two in-range (400, 500), it should pick the nearer (400)
    assert dte(chosen, asof) == 400


def test_select_strike_targets_itm():
    cfg = OptionsConfig(target_moneyness=0.95)
    strikes = [float(s) for s in range(400, 601, 5)]
    strike = S.select_strike(strikes, spot=500.0, cfg=cfg)
    assert strike == 475.0  # closest to 500 * 0.95


def test_no_target_when_trend_down():
    asof = date(2026, 1, 1)
    exps, strikes = _chain(asof)
    assert S.select_target(500, False, exps, strikes, asof, OptionsConfig()) is None


def test_size_contracts_respects_premium_budget():
    cfg = OptionsConfig(max_premium_pct=0.05, max_contracts=10)
    # equity 100k, 5% budget = 5000; premium 20/share -> 2000/contract -> 2 contracts
    assert S.size_contracts(100000, 20.0, cfg) == 2
    # cap applies
    assert S.size_contracts(100000, 0.10, cfg) == 10
    # unaffordable / no price -> 0
    assert S.size_contracts(100000, 0.0, cfg) == 0


def test_should_exit_on_trend_break_or_near_expiry():
    asof = date(2026, 1, 1)
    far = OptionContract("SPY", (asof + pd.Timedelta(days=400)).strftime("%Y%m%d"), 475, "C")
    near = OptionContract("SPY", (asof + pd.Timedelta(days=30)).strftime("%Y%m%d"), 475, "C")
    cfg = OptionsConfig(roll_dte=60)
    assert S.should_exit(far, asof, trend_up=False, cfg=cfg) is True   # trend broke
    assert S.should_exit(near, asof, trend_up=True, cfg=cfg) is True   # near expiry
    assert S.should_exit(far, asof, trend_up=True, cfg=cfg) is False   # keep


# ---- full options cycle with a fake broker ------------------------------

class FakeOptionsBroker:
    def __init__(self, equity, history, spot, expirations, strikes,
                 quote_mid=20.0, positions=None):
        self._equity = equity
        self._history = history
        self._spot = spot
        self._exps = expirations
        self._strikes = strikes
        self._quote_mid = quote_mid
        self._positions = positions or []
        self.placed = []
        self.account_id = "DU-FAKE"
        self._connected = False

    def connect_with_retry(self, **kw): self._connected = True; return self
    def connect(self, **kw): self._connected = True; return self
    def is_connected(self): return self._connected
    def disconnect(self): self._connected = False

    def account(self):
        from trader.types import Account
        return Account(cash=self._equity, equity=self._equity, positions={})

    def get_history(self, symbols, days):
        return {s: self._history[s] for s in symbols if s in self._history}

    def latest_prices(self, symbols):
        return {s: self._spot for s in symbols}

    def option_chain(self, underlying):
        return self._exps, self._strikes

    def option_quote(self, contract):
        return OptionQuote(contract=contract, bid=self._quote_mid - 0.5,
                           ask=self._quote_mid + 0.5)

    def option_positions(self):
        return list(self._positions)

    def place_option_order(self, order):
        self.placed.append(order)
        return type("T", (), {"orderStatus": type("S", (), {"status": "Filled"})()})()


def _spy_uptrend(n=320):
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = 100 * (1 + np.linspace(0, 0.6, n))
    return pd.DataFrame({"close": close, "open": close}, index=idx)


def _cfg(tmp_path):
    cfg = AppConfig(universe=["SPY"], sma_window=200)
    cfg.options = OptionsConfig(enabled=True, underlying="SPY")
    cfg.state_file = str(tmp_path / "s.json")
    cfg.store_db = ":memory:"
    return cfg


def test_options_cycle_opens_leaps_in_uptrend_dry_run(tmp_path):
    asof = datetime(2026, 1, 2, tzinfo=timezone.utc)
    exps = [(asof.date() + pd.Timedelta(days=d)).strftime("%Y%m%d") for d in (400, 500)]
    strikes = [float(s) for s in range(150, 181)]
    spot = float(_spy_uptrend()["close"].iloc[-1])
    broker = FakeOptionsBroker(100000, {"SPY": _spy_uptrend()}, spot, exps, strikes)
    store = OrderStore(":memory:")
    res = run_options_cycle(_cfg(tmp_path), RiskPolicy(), broker=broker, store=store,
                            dry_run=True, asof=asof)
    assert broker.placed == []                  # dry-run sends nothing
    assert len(res["orders"]) == 1              # but a BUY was computed
    assert res["orders"][0]["action"] == "BUY"


def test_options_cycle_live_then_idempotent(tmp_path):
    asof = datetime(2026, 1, 2, tzinfo=timezone.utc)
    exps = [(asof.date() + pd.Timedelta(days=d)).strftime("%Y%m%d") for d in (400, 500)]
    strikes = [float(s) for s in range(150, 181)]
    spot = float(_spy_uptrend()["close"].iloc[-1])
    store = OrderStore(":memory:")
    cfg = _cfg(tmp_path)

    b1 = FakeOptionsBroker(100000, {"SPY": _spy_uptrend()}, spot, exps, strikes)
    run_options_cycle(cfg, RiskPolicy(), broker=b1, store=store, dry_run=False, asof=asof)
    assert len(b1.placed) == 1

    # restart same day, still flat -> must NOT re-send
    b2 = FakeOptionsBroker(100000, {"SPY": _spy_uptrend()}, spot, exps, strikes)
    res2 = run_options_cycle(cfg, RiskPolicy(), broker=b2, store=store,
                             dry_run=False, asof=asof)
    assert b2.placed == []
    assert res2["skipped_idempotent"] == 1


def test_options_cycle_closes_when_trend_breaks(tmp_path):
    # downtrend + an existing long call -> should SELL to close, open nothing
    asof = datetime(2026, 1, 2, tzinfo=timezone.utc)
    idx = pd.bdate_range("2024-01-01", periods=320)
    close = 200 * (1 - np.linspace(0, 0.3, 320))   # downtrend
    hist = {"SPY": pd.DataFrame({"close": close, "open": close}, index=idx)}
    held = [OptionPosition(
        OptionContract("SPY", (asof.date() + pd.Timedelta(days=400)).strftime("%Y%m%d"),
                       140.0, "C"), quantity=2, avg_cost=20.0)]
    broker = FakeOptionsBroker(100000, hist, float(close[-1]),
                               ["20271217"], [140.0], positions=held)
    store = OrderStore(":memory:")
    res = run_options_cycle(_cfg(tmp_path), RiskPolicy(), broker=broker, store=store,
                            dry_run=True, asof=asof)
    actions = [o["action"] for o in res["orders"]]
    assert actions == ["SELL"]
    assert res["decision"]["trend_up"] is False
