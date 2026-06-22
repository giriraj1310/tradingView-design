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
    ibkr_broker.py     # ib_insync adapter (paper/live) + reconnect w/ backoff
  backtest/
    engine.py          # event-driven, strict t -> t+1, no look-ahead
    walkforward.py     # walk-forward + out-of-sample stitching
  store.py             # SQLite audit log: decisions/orders/fills + idempotency
  reconcile.py         # broker-vs-local position reconciliation
  loop.py              # the paper/live cycle (injectable broker/store)
  cli.py               # entrypoints
config/config.yaml      # universe, broker, backtest settings
config/risk_policy.yaml # the hard risk limits
tests/                  # incl. a direct no-look-ahead proof
```

## Setup

Fastest path (sets up the venv, installs deps, runs tests + a backtest, then a
connection check):

```bash
bash engine/quickstart.sh
```

Or manually:

```bash
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# IBKR client (auto-detected at runtime — install the one for your Python):
pip install "ib_insync>=0.9.86"   # Python <= 3.11
# pip install "ib_async>=1.0"     # Python >= 3.12 (maintained fork)
```

To test the **live IBKR paper socket** end to end, follow
[`RUNBOOK.md`](RUNBOOK.md). Note: a corporate VPN (e.g. GlobalProtect) usually
blocks IB Gateway from reaching IBKR's servers — run on a personal machine.

## 1) Backtest (no broker needed)

```bash
python -m trader.cli backtest        # downloads Yahoo data, prints metrics vs SPY
python -m trader.cli walkforward     # walk-forward + out-of-sample validation
python -m trader.cli signals         # today's target weights/orders on a flat book
pytest                               # run the test suite (incl. no-look-ahead proof)
```

`backtest` uses **point-in-time slicing** (decide on close `t`, fill at open
`t+1`), pessimistic commission + slippage, volatility-scaled sizing, a
**no-trade band** (only rebalance when a name drifts > `no_trade_band` from
target — cuts turnover dramatically), and the full risk module. It writes
`equity_curve.csv`.

`walkforward` is the honest test: for each rolling fold it picks the best
parameter on the in-sample window, then evaluates it on the **next, unseen**
window, and stitches those out-of-sample segments into one curve. It also
prints the parameter chosen per fold — if it jumps around, the "edge" is likely
noise. Tune with `--train-years/--test-years/--step-years/--grid/--select-by`.

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

### Operational safety (built in)

- **Reconnect with backoff** — the IBKR adapter retries the connection with
  exponential backoff; the cycle reads broker truth on every run.
- **Reconciliation** — on each cycle, broker positions (the source of truth) are
  compared to the local store; any drift (missed fills, manual trades) is logged
  and the broker view is trusted.
- **Idempotent orders** — every order gets a deterministic `client_id`; if it was
  already transmitted live, a restart/reconnect re-derives the same id and
  **skips** it, so you never double-send.
- **Audit log** — every decision, order, and fill is written to a SQLite db
  (`store_db` in config) for post-trade analysis. Dry-run orders are recorded but
  never block live sends.

## Going further (see the design doc)

Walk-forward + out-of-sample validation, options support, bracket orders,
reconnection/reconciliation hardening, and a monitoring dashboard are the next
milestones in the roadmap before any live capital.
