# trader — risk-first automated trading engine

A small, modular, **auditable** engine that implements the design in
[`../content/design.md`](../content/design.md). The same strategy + risk code
runs in **backtest, paper, and live** — only the data source and broker adapter
swap behind an interface.

> **Not financial advice.** No promise of profit. Backtested results do not
> predict live performance. Capital preservation is a first-class requirement;
> always paper-trade before risking real capital.

## Layout

```
trader/
  config.py            # YAML-backed config + risk policy
  types.py             # Order / Fill / Position / Account
  data/yahoo.py        # free historical bars for research (cached)
  strategies/trend.py  # pure signal: hold names above their 200d SMA
  risk/manager.py      # THE GATEKEEPER: caps, vol-targeting, kill-switches
  risk/state.py        # persistent HWM + start-of-day equity (breakers)
  execution/
    backtest_broker.py # simulated fills with commission + slippage
    ibkr_broker.py     # ib_insync adapter (paper/live)
  backtest/engine.py   # event-driven, strict t -> t+1, no look-ahead
  loop.py              # the paper/live trading cycle
  cli.py               # entrypoints
config/config.yaml      # universe, broker, backtest settings
config/risk_policy.yaml # the hard risk limits
tests/                  # incl. a direct no-look-ahead proof
```

## Setup

```bash
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

(Python 3.9 works with `ib_insync`. On Python 3.10+ prefer `ib_async` — a
drop-in fork; `pip install ib_async` and change the imports in
`execution/ibkr_broker.py`.)

## 1) Backtest (no broker needed)

```bash
python -m trader.cli backtest        # downloads Yahoo data, prints metrics vs SPY
python -m trader.cli signals         # today's target weights/orders on a flat book
pytest                               # run the test suite (incl. no-look-ahead proof)
```

`backtest` uses **point-in-time slicing** (decide on close `t`, fill at open
`t+1`), pessimistic commission + slippage, volatility-scaled sizing, and the
full risk module. It writes `equity_curve.csv`.

## 2) Connect to IBKR paper trading

1. Open an IBKR account and enable **paper trading** (Account → Settings).
2. Install and run **IB Gateway** (recommended) or **TWS**, and **log into the
   paper account**.
3. Enable the API: *Configure → Settings → API → Settings* →
   - check **Enable ActiveX and Socket Clients**
   - **Socket port** = `4002` for IB Gateway paper (TWS paper = `7497`)
   - add `127.0.0.1` to **Trusted IPs**
4. Confirm the engine can connect:

```bash
python -m trader.cli check-ibkr      # prints account, cash, positions, prices
```

5. Run a trading cycle — **dry-run first** (computes and logs orders, sends
   nothing):

```bash
python -m trader.cli paper           # DRY-RUN (safe)
python -m trader.cli paper --live-send   # actually transmit to the PAPER account
```

Ports live in `config/config.yaml` under `ibkr.port`. Risk limits live in
`config/risk_policy.yaml` and are enforced regardless of strategy. Set
`manual_overrides.global_kill_switch: true` to force-flatten and stop trading.

## Going further (see the design doc)

Walk-forward + out-of-sample validation, options support, bracket orders,
reconnection/reconciliation hardening, and a monitoring dashboard are the next
milestones in the roadmap before any live capital.
