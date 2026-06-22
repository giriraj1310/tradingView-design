# Automated Trading System — Design

A practical, risk-first, auditable engineering design for an automated trading
system that generates signals, manages risk, backtests properly, supports paper
trading, and eventually executes through **Interactive Brokers (IBKR)**.

> **Not financial advice.** This repository documents an *engineering* design.
> It does not promise profits or guaranteed returns. Trading carries
> substantial risk of loss. Backtested/simulated results do not predict live
> performance.

The full design lives in [`content/design.md`](content/design.md) and is
rendered by a small **Next.js** site deployed on **Vercel**.

## What's here

- `content/design.md` — the complete, version-controlled design document
  (architecture, strategy framework, backtesting, risk policy, IBKR execution,
  roadmap, pseudo-code, pre-live checklist).
- `app/` — Next.js (App Router) site that renders the design.
- [`engine/`](engine/) — **the runnable Python trading engine**: honest
  event-driven backtester, the risk gatekeeper (caps, vol-targeting,
  kill-switches), and an `ib_insync` adapter that connects to IBKR **paper
  trading**. The same strategy + risk code runs in backtest, paper, and live.
  See [`engine/README.md`](engine/README.md) to run it, or
  [`engine/RUNBOOK.md`](engine/RUNBOOK.md) to test the live IBKR paper socket
  end to end (`bash engine/quickstart.sh` for one-command setup).

> The Next.js site is **documentation only**. The actual trading engine is
> intended to run on your own always-on host (it needs a persistent socket to
> IB Gateway and durable local state) — never as a public serverless function.

## Run locally

```bash
npm install
npm run dev      # http://localhost:3000
```

## Deploy

Pushes to the connected GitHub repository auto-deploy via Vercel.
