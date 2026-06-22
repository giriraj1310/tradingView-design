"""Configuration loading. Plain dataclasses backed by YAML files."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(_HERE, "config", "config.yaml")
DEFAULT_RISK = os.path.join(_HERE, "config", "risk_policy.yaml")


@dataclass
class RiskPolicy:
    max_gross_exposure: float = 1.0
    max_net_exposure: float = 1.0
    max_weight_single_etf: float = 0.25
    max_weight_single_stock: float = 0.08
    max_positions: int = 12
    max_sector_weight: float = 0.35
    min_trade_notional: float = 100.0
    no_trade_band: float = 0.05
    sizing_method: str = "volatility_target"
    target_annual_vol: float = 0.10
    risk_per_trade: float = 0.0075
    kelly_fraction_cap: float = 0.25
    stop_type: str = "atr"
    atr_multiple: float = 3.0
    time_stop_bars: int = 20
    max_daily_loss_pct: float = 0.02
    drawdown_soft_pct: float = 0.10
    drawdown_hard_pct: float = 0.15
    max_spread_bps: float = 25.0
    halt_on_stale_data_seconds: int = 120
    on_uncertainty: str = "reduce_or_halt"
    global_kill_switch: bool = False

    @classmethod
    def load(cls, path: str = DEFAULT_RISK) -> "RiskPolicy":
        with open(path) as f:
            d = yaml.safe_load(f) or {}
        lev = d.get("leverage", {})
        pos = d.get("position_limits", {})
        siz = d.get("sizing", {})
        reb = d.get("rebalancing", {})
        st = d.get("stops", {})
        cb = d.get("circuit_breakers", {})
        mg = d.get("market_guards", {})
        mo = d.get("manual_overrides", {})
        return cls(
            max_gross_exposure=lev.get("max_gross_exposure", 1.0),
            max_net_exposure=lev.get("max_net_exposure", 1.0),
            max_weight_single_etf=pos.get("max_weight_single_etf", 0.25),
            max_weight_single_stock=pos.get("max_weight_single_stock", 0.08),
            max_positions=pos.get("max_positions", 12),
            max_sector_weight=pos.get("max_sector_weight", 0.35),
            min_trade_notional=pos.get("min_trade_notional", 100.0),
            no_trade_band=reb.get("no_trade_band", 0.05),
            sizing_method=siz.get("method", "volatility_target"),
            target_annual_vol=siz.get("target_annual_vol", 0.10),
            risk_per_trade=siz.get("risk_per_trade", 0.0075),
            kelly_fraction_cap=siz.get("kelly_fraction_cap", 0.25),
            stop_type=st.get("type", "atr"),
            atr_multiple=st.get("atr_multiple", 3.0),
            time_stop_bars=st.get("time_stop_bars", 20),
            max_daily_loss_pct=cb.get("max_daily_loss_pct", 0.02),
            drawdown_soft_pct=cb.get("drawdown_soft_pct", 0.10),
            drawdown_hard_pct=cb.get("drawdown_hard_pct", 0.15),
            max_spread_bps=mg.get("max_spread_bps", 25.0),
            halt_on_stale_data_seconds=mg.get("halt_on_stale_data_seconds", 120),
            on_uncertainty=mg.get("on_uncertainty", "reduce_or_halt"),
            global_kill_switch=mo.get("global_kill_switch", False),
        )


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 17
    account: Optional[str] = None
    readonly: bool = False


@dataclass
class OptionsConfig:
    enabled: bool = False
    underlying: str = "SPY"
    right: str = "C"
    min_dte: int = 365          # LEAPS: at least ~1 year to expiry
    max_dte: int = 730          # ...up to ~2 years
    roll_dte: int = 60          # close/roll when fewer than this many days left
    target_moneyness: float = 0.95  # strike ~5% ITM for a long call (higher delta)
    max_premium_pct: float = 0.05   # max total premium at risk = your defined max loss
    max_contracts: int = 10
    limit_buffer: float = 0.02  # marketable-limit buffer over the quote


@dataclass
class BacktestConfig:
    start: str = "2015-01-01"
    end: Optional[str] = None
    initial_cash: float = 100000.0
    commission_per_share: float = 0.005
    min_commission: float = 1.0
    slippage_bps: float = 5.0
    benchmark: str = "SPY"


@dataclass
class AppConfig:
    universe: List[str] = field(default_factory=list)
    bar: str = "1d"
    history_days: int = 420
    data_source: str = "yahoo"
    cache_dir: str = ".cache"
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    strategy_name: str = "trend"
    sma_window: int = 200
    base_gross: float = 1.0
    state_file: str = ".state/risk_state.json"
    store_db: str = ".state/trader.db"
    log_file: str = ".logs/trader.log"

    @classmethod
    def load(cls, path: str = DEFAULT_CONFIG) -> "AppConfig":
        with open(path) as f:
            d = yaml.safe_load(f) or {}
        data = d.get("data", {})
        bt = d.get("backtest", {})
        ib = d.get("ibkr", {})
        opt = d.get("options", {})
        strat = d.get("strategy", {})
        return cls(
            universe=d.get("universe", []),
            bar=d.get("bar", "1d"),
            history_days=d.get("history_days", 420),
            data_source=data.get("source", "yahoo"),
            cache_dir=data.get("cache_dir", ".cache"),
            backtest=BacktestConfig(
                start=bt.get("start", "2015-01-01"),
                end=bt.get("end"),
                initial_cash=bt.get("initial_cash", 100000.0),
                commission_per_share=bt.get("commission_per_share", 0.005),
                min_commission=bt.get("min_commission", 1.0),
                slippage_bps=bt.get("slippage_bps", 5.0),
                benchmark=bt.get("benchmark", "SPY"),
            ),
            ibkr=IBKRConfig(
                host=ib.get("host", "127.0.0.1"),
                port=ib.get("port", 4002),
                client_id=ib.get("client_id", 17),
                account=ib.get("account"),
                readonly=ib.get("readonly", False),
            ),
            options=OptionsConfig(
                enabled=opt.get("enabled", False),
                underlying=opt.get("underlying", "SPY"),
                right=opt.get("right", "C"),
                min_dte=opt.get("min_dte", 365),
                max_dte=opt.get("max_dte", 730),
                roll_dte=opt.get("roll_dte", 60),
                target_moneyness=opt.get("target_moneyness", 0.95),
                max_premium_pct=opt.get("max_premium_pct", 0.05),
                max_contracts=opt.get("max_contracts", 10),
                limit_buffer=opt.get("limit_buffer", 0.02),
            ),
            strategy_name=strat.get("name", "trend"),
            sma_window=strat.get("sma_window", 200),
            base_gross=strat.get("base_gross", 1.0),
            state_file=d.get("state_file", ".state/risk_state.json"),
            store_db=d.get("store_db", ".state/trader.db"),
            log_file=d.get("log_file", ".logs/trader.log"),
        )
