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
