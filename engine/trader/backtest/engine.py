"""Event-driven backtest engine with strict no-look-ahead discipline.

The contract that keeps the backtest honest:

  * On each day `t`, the strategy and risk manager only ever see history
    sliced up to and including `t` (`df.loc[:t]`).
  * Orders decided on `t` are filled at the **next** trading day's OPEN
    (`t+1`), via the BacktestBroker, with slippage + commission.
  * Equity is marked at each day's close.

This is the SAME strategy + risk code used in paper/live; only the broker
(BacktestBroker) and data source differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from ..config import BacktestConfig, RiskPolicy
from ..execution.backtest_broker import BacktestBroker
from ..risk.manager import RiskManager
from ..risk.state import RiskState
from .metrics import compute_metrics


@dataclass
class BacktestResult:
    equity: pd.Series
    metrics: Dict[str, float]
    benchmark_equity: Optional[pd.Series] = None
    benchmark_metrics: Dict[str, float] = field(default_factory=dict)
    n_fills: int = 0
    decisions: List[dict] = field(default_factory=list)


def _price_asof(df: pd.DataFrame, day, col: str) -> Optional[float]:
    sub = df.loc[:day, col]
    if len(sub) == 0:
        return None
    val = sub.iloc[-1]
    return float(val) if pd.notna(val) else None


def run_backtest(
    history: Dict[str, pd.DataFrame],
    strategy,
    policy: RiskPolicy,
    cfg: BacktestConfig,
    record_decisions: bool = False,
) -> BacktestResult:
    if not history:
        raise ValueError("Empty history.")

    all_dates = sorted(set().union(*[set(df.index) for df in history.values()]))
    if cfg.start:
        start = pd.to_datetime(cfg.start)
        all_dates = [d for d in all_dates if d >= start]
    if cfg.end:
        end = pd.to_datetime(cfg.end)
        all_dates = [d for d in all_dates if d <= end]
    if len(all_dates) < strategy.warmup + 2:
        raise ValueError("Not enough data for the strategy warmup window.")

    broker = BacktestBroker(
        cash=cfg.initial_cash,
        commission_per_share=cfg.commission_per_share,
        min_commission=cfg.min_commission,
        slippage_bps=cfg.slippage_bps,
    )
    risk = RiskManager(policy)
    state = RiskState.initialize(cfg.initial_cash, str(all_dates[0].date()))

    equity_points: List[tuple] = []
    decisions: List[dict] = []

    for i, day in enumerate(all_dates):
        # mark-to-market at today's close (no future info)
        marks = {s: _price_asof(df, day, "close") for s, df in history.items()}
        marks = {s: px for s, px in marks.items() if px is not None}
        acct = broker.account(marks)
        state.update(acct.equity, str(day.date()))
        equity_points.append((day, acct.equity))

        if i < strategy.warmup or i + 1 >= len(all_dates):
            continue

        # decide using ONLY history up to `day`
        hist_slice = {s: df.loc[:day] for s, df in history.items()}
        desired = strategy.target_weights(hist_slice, asof=day)
        orders, decision = risk.build_orders(
            desired, hist_slice, acct, state, latest_prices=marks, asof=day
        )
        if record_decisions:
            decisions.append(decision)

        # execute at NEXT day's open
        next_day = all_dates[i + 1]
        for order in orders:
            df = history.get(order.symbol)
            if df is None or next_day not in df.index:
                continue
            fill_open = float(df.loc[next_day, "open"])
            broker.execute(order, fill_open, next_day)

    equity = pd.Series(
        [e for _, e in equity_points], index=[d for d, _ in equity_points]
    )
    metrics = compute_metrics(equity)

    bench_equity = None
    bench_metrics: Dict[str, float] = {}
    bdf = history.get(cfg.benchmark)
    if bdf is not None:
        bclose = bdf["close"].reindex(equity.index).ffill().dropna()
        if len(bclose) > 1:
            bench_equity = (bclose / bclose.iloc[0]) * cfg.initial_cash
            bench_metrics = compute_metrics(bench_equity)

    return BacktestResult(
        equity=equity,
        metrics=metrics,
        benchmark_equity=bench_equity,
        benchmark_metrics=bench_metrics,
        n_fills=len(broker.fills),
        decisions=decisions,
    )
