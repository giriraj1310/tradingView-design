"""Command-line entrypoints.

Run from the `engine/` directory:

    python -m trader.cli backtest          # honest backtest on Yahoo data
    python -m trader.cli signals           # today's target weights/orders (no broker)
    python -m trader.cli check-ibkr        # connect to IBKR paper, print account
    python -m trader.cli paper             # one paper cycle, DRY-RUN by default
    python -m trader.cli paper --live-send # actually send orders to the paper acct
"""
from __future__ import annotations

import argparse
import sys

from .config import AppConfig, RiskPolicy
from .logging_setup import setup as setup_logging


def _pct(x) -> str:
    return f"{x * 100:.2f}%" if isinstance(x, (int, float)) else str(x)


def cmd_backtest(cfg: AppConfig, policy: RiskPolicy, args) -> int:
    from .backtest import run_backtest
    from .data import yahoo
    from .strategies import build as build_strategy

    print(f"Loading history for {cfg.universe} from Yahoo (cache: {cfg.cache_dir}) ...")
    history = yahoo.load(
        cfg.universe, cache_dir=cfg.cache_dir, start=cfg.backtest.start,
        end=cfg.backtest.end, refresh=args.refresh,
    )
    strategy = build_strategy(cfg.strategy_name, sma_window=cfg.sma_window,
                              base_gross=cfg.base_gross)
    result = run_backtest(history, strategy, policy, cfg.backtest)

    m, b = result.metrics, result.benchmark_metrics
    print("\n=== Backtest result ===")
    print(f"period            {result.equity.index[0].date()} -> {result.equity.index[-1].date()}")
    print(f"strategy          {cfg.strategy_name} (sma={cfg.sma_window})")
    print(f"fills             {result.n_fills}")
    print(f"{'':18}{'STRATEGY':>12}{'BENCHMARK ' + cfg.backtest.benchmark:>20}")
    for key, label in [
        ("total_return", "Total return"), ("cagr", "CAGR"),
        ("ann_vol", "Ann. vol"), ("sharpe", "Sharpe"),
        ("max_drawdown", "Max drawdown"), ("calmar", "Calmar"),
    ]:
        sv = m.get(key, 0.0)
        bv = b.get(key, 0.0)
        sfmt = f"{sv:.2f}" if key in ("sharpe", "calmar") else _pct(sv)
        bfmt = f"{bv:.2f}" if key in ("sharpe", "calmar") else _pct(bv)
        print(f"{label:18}{sfmt:>12}{bfmt:>20}")

    out = "equity_curve.csv"
    result.equity.to_csv(out, header=["equity"])
    print(f"\nEquity curve written to {out}")
    print("NOTE: backtested results do not predict live performance.")
    return 0


def cmd_walkforward(cfg: AppConfig, policy: RiskPolicy, args) -> int:
    from .backtest import walk_forward
    from .data import yahoo
    from .strategies.trend import TrendFollowing

    print(f"Loading history for {cfg.universe} from Yahoo ...")
    history = yahoo.load(cfg.universe, cache_dir=cfg.cache_dir,
                         start=cfg.backtest.start, end=cfg.backtest.end,
                         refresh=args.refresh)
    grid = [{"sma_window": w} for w in args.grid]
    factory = lambda **p: TrendFollowing(sma_window=p["sma_window"],
                                         base_gross=cfg.base_gross)
    result = walk_forward(
        history, factory, grid, policy, cfg.backtest,
        train_years=args.train_years, test_years=args.test_years,
        step_years=args.step_years, select_by=args.select_by,
    )

    print(f"\n=== Walk-forward (train={args.train_years}y / test={args.test_years}y "
          f"/ step={args.step_years}y, select by {args.select_by}) ===")
    print(f"param grid: sma_window in {args.grid}")
    print(f"\n{'fold OOS period':28}{'picked sma':>11}{'OOS ret':>10}{'OOS DD':>9}")
    selected = []
    for f in result.folds:
        sma = f.best_param["sma_window"]
        selected.append(sma)
        print(f"{f.test_start} -> {f.test_end:12}{sma:>11}"
              f"{_pct(f.oos_metrics.get('total_return', 0)):>10}"
              f"{_pct(f.oos_metrics.get('max_drawdown', 0)):>9}")

    m, b = result.oos_metrics, result.benchmark_metrics
    print("\n--- Stitched OUT-OF-SAMPLE vs benchmark "
          f"{cfg.backtest.benchmark} (same OOS period) ---")
    print(f"{'':18}{'OOS':>12}{'BENCHMARK':>14}")
    for key, label in [("total_return", "Total return"), ("cagr", "CAGR"),
                       ("ann_vol", "Ann. vol"), ("sharpe", "Sharpe"),
                       ("max_drawdown", "Max drawdown"), ("calmar", "Calmar")]:
        sv, bv = m.get(key, 0.0), b.get(key, 0.0)
        sfmt = f"{sv:.2f}" if key in ("sharpe", "calmar") else _pct(sv)
        bfmt = f"{bv:.2f}" if key in ("sharpe", "calmar") else _pct(bv)
        print(f"{label:18}{sfmt:>12}{bfmt:>14}")

    uniq = sorted(set(selected))
    print(f"\nparameter stability: selected sma values = {uniq}")
    print("  (few distinct, clustered values = robust; jumping all over = likely noise)")
    print("NOTE: OOS results still do not guarantee live performance.")
    return 0


def cmd_signals(cfg: AppConfig, policy: RiskPolicy, args) -> int:
    from .data import yahoo
    from .risk.manager import RiskManager
    from .risk.state import RiskState
    from .strategies import build as build_strategy
    from .types import Account

    history = yahoo.load(cfg.universe, cache_dir=cfg.cache_dir,
                         start=cfg.backtest.start, refresh=args.refresh)
    strategy = build_strategy(cfg.strategy_name, sma_window=cfg.sma_window,
                              base_gross=cfg.base_gross)
    desired = strategy.target_weights(history)
    prices = {s: float(df["close"].iloc[-1]) for s, df in history.items()}

    equity = args.equity
    acct = Account(cash=equity, equity=equity, positions={})
    state = RiskState.initialize(equity, "today")
    risk = RiskManager(policy)
    orders, decision = risk.build_orders(desired, history, acct, state,
                                         latest_prices=prices)

    print("=== Today's signals (paper sizing on a flat book) ===")
    print(f"assumed equity    {equity:,.0f}")
    print(f"desired weights   {decision['desired_weights']}")
    print(f"target weights    {decision['target_weights']}")
    print(f"vol scale         {decision['vol_scale']}")
    print(f"risk mode         {decision['mode']}")
    print("orders:")
    for o in orders:
        print(f"  {o.action:4} {o.symbol:5} x{o.quantity:<6} ~${prices[o.symbol]*o.quantity:,.0f}")
    if not orders:
        print("  (none)")
    return 0


def cmd_check_ibkr(cfg: AppConfig, policy: RiskPolicy, args) -> int:
    from .execution.ibkr_broker import IBKRBroker, IBKRError

    broker = IBKRBroker(cfg.ibkr)
    print(f"Connecting to IBKR at {cfg.ibkr.host}:{cfg.ibkr.port} "
          f"(clientId={cfg.ibkr.client_id}) ...")
    try:
        broker.connect()
    except IBKRError as e:
        print(f"\nCONNECTION FAILED:\n  {e}\n")
        print("Checklist:")
        print("  1. IB Gateway (or TWS) is running and logged into your PAPER account.")
        print("  2. API enabled: Configure > Settings > API > 'Enable ActiveX and Socket Clients'.")
        print(f"  3. Socket port matches config.yaml ibkr.port ({cfg.ibkr.port}).")
        print("  4. 127.0.0.1 is in 'Trusted IPs' (or uncheck 'Read-Only API' as needed).")
        return 2

    try:
        acct = broker.account()
        print(f"\nConnected. Account: {broker.account_id}")
        print(f"  Net liquidation : {acct.equity:,.2f}")
        print(f"  Cash            : {acct.cash:,.2f}")
        print(f"  Positions       : {len(acct.positions)}")
        for s, p in acct.positions.items():
            print(f"    {s:6} qty={p.quantity:<8} avg_cost={p.avg_cost:.2f}")
        prices = broker.latest_prices(cfg.universe)
        print(f"  Latest prices   : "
              + ", ".join(f"{s}={v:.2f}" for s, v in prices.items()))
        print("\nOK — the engine can connect to your IBKR account.")
        return 0
    finally:
        broker.disconnect()


def cmd_paper(cfg: AppConfig, policy: RiskPolicy, args) -> int:
    from .loop import run_cycle

    logger = setup_logging(cfg.log_file)
    dry_run = not args.live_send
    if dry_run:
        print("DRY-RUN: computing orders but NOT sending. Use --live-send to transmit.")
    result = run_cycle(cfg, policy, dry_run=dry_run, logger=logger)
    print(f"\nrisk mode        : {result['decision']['mode']}")
    print(f"orders           : {result['orders'] or '(none)'}")
    print(f"skipped (idempot): {result['skipped_idempotent']}")
    if result["reconcile_discrepancies"]:
        print(f"reconcile drift  : {result['reconcile_discrepancies']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="trader", description="Risk-first trading engine")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--risk", default=None, help="path to risk_policy.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bt = sub.add_parser("backtest", help="run an honest backtest on Yahoo data")
    p_bt.add_argument("--refresh", action="store_true", help="ignore cache, refetch")
    p_bt.set_defaults(func=cmd_backtest)

    p_wf = sub.add_parser("walkforward", help="walk-forward + OOS validation")
    p_wf.add_argument("--refresh", action="store_true")
    p_wf.add_argument("--grid", type=int, nargs="+",
                      default=[50, 100, 150, 200, 250],
                      help="sma_window values to select among")
    p_wf.add_argument("--train-years", type=int, default=3)
    p_wf.add_argument("--test-years", type=int, default=1)
    p_wf.add_argument("--step-years", type=int, default=1)
    p_wf.add_argument("--select-by", default="sharpe",
                      choices=["sharpe", "calmar", "cagr", "total_return"])
    p_wf.set_defaults(func=cmd_walkforward)

    p_sig = sub.add_parser("signals", help="today's target weights/orders (no broker)")
    p_sig.add_argument("--refresh", action="store_true")
    p_sig.add_argument("--equity", type=float, default=100000.0)
    p_sig.set_defaults(func=cmd_signals)

    p_chk = sub.add_parser("check-ibkr", help="connect to IBKR and print the account")
    p_chk.set_defaults(func=cmd_check_ibkr)

    p_pap = sub.add_parser("paper", help="run one trading cycle against IBKR")
    p_pap.add_argument("--live-send", action="store_true",
                       help="actually transmit orders (default is dry-run)")
    p_pap.set_defaults(func=cmd_paper)

    args = parser.parse_args(argv)
    cfg = AppConfig.load(args.config) if args.config else AppConfig.load()
    policy = RiskPolicy.load(args.risk) if args.risk else RiskPolicy.load()
    return args.func(cfg, policy, args)


if __name__ == "__main__":
    sys.exit(main())
