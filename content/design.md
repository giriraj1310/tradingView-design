# Automated Trading System — Design

> **Disclaimer.** This is an engineering and research design document. It does **not** promise profits or guaranteed returns. Trading involves substantial risk of loss. Capital preservation and risk management are treated as first-class requirements throughout. Nothing here is financial advice. Backtested or simulated results do not predict live performance. Live behavior depends on market conditions that change continuously.

## Explicit assumptions

1. You are an individual / small trader, not an institution; latency in seconds (not microseconds) is acceptable. No HFT.
2. Asset universe is liquid US-listed stocks and ETFs first; options are a later, optional extension.
3. Strategies operate on daily or intraday bars (minutes), not tick data.
4. Single broker to start: **Interactive Brokers (IBKR)** via its API.
5. You want the system auditable: every decision must be reconstructable from logs.
6. Modest capital at risk initially; correctness and safety matter more than throughput.
7. You can run a small always-on machine (VPS or home server) during market hours.

---

## 1. High-level architecture

The system is a set of **decoupled, independently testable modules** communicating through well-defined interfaces (function calls in a monolith to start; a message bus only if you later need it). Each module does one thing.

```
            ┌──────────────────────────────────────────────────────────────┐
            │                        CONFIG / SECRETS                        │
            │     strategy params · risk policy · API keys · universe        │
            └──────────────────────────────────────────────────────────────┘
                                         │
   ┌─────────────┐    bars/quotes   ┌────▼────────┐   signals   ┌────────────────┐
   │ DATA         │ ───────────────▶│ SIGNAL       │ ──────────▶ │ PORTFOLIO &    │
   │ INGESTION    │                 │ GENERATION   │             │ RISK MANAGER   │
   │ (mkt data,   │◀── corp actions │ (strategies) │             │ (sizing,       │
   │  fundamentals)│                └──────────────┘             │  limits, veto) │
   └─────────────┘                                               └───────┬────────┘
         │                                                  target orders │
         │ historical                                                     ▼
         ▼                                                        ┌────────────────┐
   ┌─────────────┐        same interface                         │ EXECUTION      │
   │ BACKTEST     │◀───────── strategies & risk ─────────────────│ ENGINE (IBKR)  │
   │ ENGINE       │                                               │ paper → live   │
   └─────────────┘                                               └───────┬────────┘
                                                                 fills,  │
                                                                 state   ▼
   ┌──────────────────────────────┐                            ┌────────────────┐
   │ MONITORING & ALERTS          │◀───────────────────────────│ STATE STORE +  │
   │ (dashboard, P&L, drawdown,   │                            │ LOGGING /      │
   │  health, kill-switch alerts) │                            │ ANALYTICS      │
   └──────────────────────────────┘                            └────────────────┘
```

**Key principle: the same strategy + risk code runs in backtest, paper, and live.** Only the *data source* and *execution adapter* swap out behind an interface. If backtest and live use different code paths, your backtest is fiction.

### Data ingestion
- **Responsibilities:** fetch historical bars, real-time quotes/bars, corporate actions (splits/dividends), and a tradable universe list. Normalize to a single internal schema (`symbol, timestamp, open, high, low, close, volume, adjusted_close`). Timestamps stored in UTC, always timezone-aware.
- **Sources:** IBKR API for both historical and live (single source of truth, matches what you trade). Yahoo Finance / a vendor for cheap research history and cross-checks. TradingView stays for *discretionary monitoring*, not as a programmatic dependency (no robust official data API).
- **Critical:** use **split/dividend-adjusted** series for signal research, but reconcile against **unadjusted** prices for actual order sizing. Cache raw vendor responses immutably so a backtest is reproducible. Validate on ingest: monotonic timestamps, no duplicate bars, gap detection, outlier/price-spike checks.

### Signal generation
- Pure functions: `signal(history) -> {target_weight or direction, strength, metadata}`. **No I/O, no order placement, no broker calls.** This is what makes them unit-testable and reusable across backtest/live.
- Each strategy declares its required lookback, bar frequency, and warm-up period so the engine can guarantee enough history before emitting signals.
- Output is an *intention* ("I want 5% long SPY"), never a raw order. Translation to orders is the risk manager's + execution engine's job.

### Portfolio & risk management
- The **gatekeeper**. Takes desired signals + current positions + account state and produces **risk-approved target orders**, or vetoes. Enforces position caps, exposure limits, volatility scaling, daily-loss and drawdown kill-switches. (Section 4.)
- This layer has final authority. A strategy can scream "buy"; the risk manager can still say no. It is the most important code to test.

### Execution engine
- Translates target positions into broker orders, manages order lifecycle, handles partial fills, reconnects, idempotency. Pluggable adapter: `BacktestBroker`, `PaperBroker (IBKR paper)`, `LiveBroker (IBKR live)` all implement one interface. (Section 5.)

### Monitoring and alerts
- Real-time dashboard (positions, P&L, exposure, drawdown, system health/heartbeat). Push alerts (email / SMS / Telegram / Slack) on: kill-switch trips, disconnects, rejected orders, data staleness, unhandled exceptions, drawdown thresholds.
- A **heartbeat**: if the bot stops emitting "I'm alive," you get paged. Silence is the most dangerous failure.

### Logging and analytics
- Structured, append-only logs of **every decision**: input snapshot, signal, risk decision (and reason for any veto), order sent, fill received, resulting state. This is your audit trail and your post-trade research dataset.
- Separate analytics layer computes performance attribution, slippage vs. expectation, per-strategy stats, and feeds the post-trade review.

---

## 2. Strategy framework

Test a small number of **simple, economically-motivated** strategies. A strategy you can explain in one sentence and whose edge has a plausible cause is far more robust than a fitted curve. Below, 4 families.

### A. Trend following / time-series momentum
- **Idea:** instruments that have risen tend to keep rising over weeks–months (e.g., price > 200-day MA, or 12-1 month momentum).
- **Works when:** strong directional regimes, persistent macro trends, crises (trend-following is often long volatility / crisis-robust on the short side).
- **Failure modes:** choppy, range-bound markets (whipsaws, death by a thousand small losses); sharp V-shaped reversals; high transaction costs erode many small entries/exits.
- **Why it can persist:** behavioral under-reaction, slow diffusion of information, institutional flows.

### B. Cross-sectional momentum (relative strength)
- **Idea:** rank a universe (e.g., sector ETFs or large caps), go long the strongest, optionally short/avoid the weakest; rebalance monthly.
- **Works when:** clear dispersion between winners and losers; trending sectors.
- **Failure modes:** momentum crashes (violent rotations after drawdowns, e.g., 2009), crowding, high turnover costs.

### C. Mean reversion (short-term)
- **Idea:** liquid instruments overshoot and snap back over days (e.g., RSI(2) extremes, distance from a short MA, Bollinger reversion). Often ETF/index level.
- **Works when:** calm, liquid, range-bound markets; intraday/short horizons.
- **Failure modes:** **catastrophic in trends and crashes** — "buying the dip" all the way down. Must be paired with hard stops or a regime filter (e.g., only mean-revert when above the 200-day MA / when VIX is moderate).

### D. Volatility / regime-based allocation
- **Idea:** scale exposure inversely to realized volatility; target a constant portfolio volatility; risk-on/risk-off switching using trend + vol filters.
- **Works when:** as an overlay on any of the above — improves risk-adjusted returns and tames drawdowns more than it boosts raw return.
- **Failure modes:** volatility regime shifts faster than your estimate; correlations go to 1 in crises, defeating diversification assumptions.

### (Optional E) Options income / defined-risk
- E.g., cash-secured puts, covered calls, defined-risk spreads. **Defer until the equity system is proven.** Options add assignment, expiry, Greeks, and far worse modeling/slippage complexity. Never sell naked options in an automated system.

### Ranking — simplicity × robustness (start at the top)

| Rank | Strategy | Simplicity | Robustness | Notes |
|------|----------|-----------|-----------|-------|
| 1 | **Trend following (A)** on ETFs | High | High | Best first strategy; transparent, crisis-aware, few params |
| 2 | **Volatility scaling (D)** as overlay | High | High | Pairs with everything; biggest risk-adjusted bang |
| 3 | **Cross-sectional momentum (B)** | Medium | Medium-High | Monthly rebalance keeps costs low |
| 4 | **Mean reversion (C)** | Medium | Medium | Needs a regime filter + hard stops or it blows up |
| 5 | **Options (E)** | Low | Low (operationally) | Only after 1–4 are live and stable |

**Recommendation:** start with **A + D** (trend following with volatility-scaled sizing) on a handful of liquid ETFs. It is simple, auditable, and risk-first.

---

## 3. Backtesting design

A backtest's only purpose is to *honestly* estimate whether an edge could have existed — and mostly to *reject* bad ideas. Optimize for realism and skepticism, not for pretty equity curves.

### Avoiding look-ahead bias
- **Point-in-time data only.** At decision time `t`, the strategy may use information available *at or before `t`*. A signal computed from today's close can only trade at the next available price (next open or with a realistic delay).
- **Bar discipline:** decide on bar `t`'s close → execute at bar `t+1`'s open (or VWAP). Never fill at the same close you used to decide.
- Use **as-of/point-in-time** fundamentals (avoid restated financials and survivorship in the universe — include delisted symbols).
- Beware indicators that implicitly peek (e.g., centered moving averages, signals normalized by full-sample mean/std).

### Transaction costs, slippage, spreads
- Model explicitly; default to **pessimistic** assumptions:
  - **Commissions:** IBKR per-share/percentage tiers.
  - **Spread:** pay (or cross) half-to-full bid/ask; wider for less liquid names.
  - **Slippage:** model as a function of order size vs. average volume and of volatility; add a fixed component for market impact.
  - **Borrow costs / financing** for shorts and leverage; **dividends** on both sides.
- Run sensitivity: if the edge vanishes when you double costs, it isn't real.

### Position sizing
- Sizing is part of the strategy and must be backtested with it. Options: fixed fractional risk per trade (e.g., risk 0.5–1% of equity to the stop), volatility targeting (size so each position contributes equal risk), or capped target weights. **Avoid full Kelly** — fractional Kelly (¼–½) at most; Kelly assumes you know the true edge, which you don't.

### Walk-forward testing
- Don't optimize once over all history. **Roll:** optimize on an in-sample window, test on the next out-of-sample window, step forward, repeat. Concatenate the out-of-sample segments — *that* stitched curve is your realistic estimate. Anchored or rolling windows both fine; document which.

### Out-of-sample validation
- Hold out a final chunk of recent history (e.g., last 1–2 years) that you **never** touch during development. You get to look at it essentially **once**. If you iterate against it, it's no longer out-of-sample.

### Overfitting prevention
- Few parameters; prefer round, robust values over knife-edge optima; check that nearby parameters give similar results (a **parameter plateau**, not a spike).
- Track the **number of trials**; the more configurations you try, the more a good result is luck (multiple-testing / deflated Sharpe).
- Require an **economic rationale** before believing any result.
- Test across multiple instruments and regimes; an edge that only works on one ticker in one decade is noise.
- Compare against honest **benchmarks** (buy-and-hold SPY, risk-free rate) on a risk-adjusted basis.

---

## 4. Risk management

Risk rules are **hard constraints enforced in code**, independent of any strategy, and checked on every cycle. When a rule and a signal conflict, the rule wins.

- **Max position size:** cap any single name at e.g. **5–10% of equity** (lower for single stocks, higher for broad ETFs). Hard reject orders that would breach it.
- **Max gross / net exposure:** e.g., gross ≤ 100% (no leverage initially), net within a band. Sector/asset-class concentration caps.
- **Max daily loss (kill-switch):** if realized+unrealized P&L for the day ≤ **−X%** (e.g., −2%), flatten new risk / stop opening positions for the day and alert.
- **Max drawdown rule:** if equity falls **Y%** from its high-water mark (e.g., −15%), de-risk to a fraction of normal size or halt and require **manual re-enable**. Tiered: soft de-risk at one level, hard stop at a deeper one.
- **Volatility scaling:** target a portfolio volatility (e.g., 10% annualized); when realized vol rises, sizes shrink automatically. Single biggest lever for taming drawdowns.
- **Stop-loss / take-profit:** define per-strategy. Prefer volatility-based stops (e.g., N×ATR) over fixed %; consider time stops (exit if thesis hasn't played out in M bars). Take-profits optional and strategy-dependent; trend strategies usually *don't* cap upside.
- **Correlation / portfolio heat:** limit total risk across correlated positions, not just per-position — five "different" trades that are really one bet on tech is one position.
- **Unusual market conditions:** define triggers — extreme gaps, halted/limit-up-down, abnormal spreads, data staleness, VIX spikes, failed broker reconnect. Default action under uncertainty is **reduce or stop, never increase**. Around major scheduled events (FOMC, earnings, CPI) optionally widen stops or stand aside. **A documented, automatic "do nothing / flatten" path is itself a feature.**

See the sample **Risk Policy** in Section 8.

---

## 5. IBKR execution plan

### Connecting (conceptually)
- IBKR exposes its API through **Trader Workstation (TWS)** or the headless **IB Gateway**. Your bot connects over a local socket to that running client; the client talks to IBKR servers. Recommended Python library: **`ib_insync`** (or the official `ibapi`).
- **IB Gateway** (lightweight, no GUI) is preferred for automation. It requires a **daily restart/re-auth** (or use IBKR's auto-restart config) — plan around the scheduled maintenance window.
- The execution adapter exposes: `connect()`, `get_account()`, `get_positions()`, `place_order()`, `cancel_order()`, `on_fill()`, `on_disconnect()`.

### Order types to support (minimum viable set)
- **Market** (use sparingly — slippage), **Limit** (default), **Marketable limit** (limit with a buffer = controlled aggression, preferred for liquid names), **Stop / Stop-limit** for protective exits, **MOC/LOC** if you trade on the close. Add **bracket orders** (entry + attached stop + target) once basics are solid.

### Failures, partial fills, reconnects — make it boring and safe
- **Idempotency:** every order carries a client-generated unique ID; on reconnect, **reconcile** broker state vs. your state store before doing anything. Never assume; always re-read positions and open orders.
- **Partial fills:** track filled vs. remaining; decide policy (chase, wait, or cancel-replace). Position sizing must use *actual* filled quantity.
- **Disconnects:** on disconnect, **stop emitting new orders**, attempt bounded reconnect with backoff, and on reconnect reconcile. If reconciliation can't be confirmed, **halt and alert a human** — do not guess.
- **Timeouts / rejects:** every order has an expected-ack timeout; unacknowledged or rejected orders raise alerts. Log the broker's reason code.
- **Single source of truth:** the broker is authoritative for positions/fills; your store mirrors it and is reconciled at startup and on every reconnect.

### Paper first, then live
1. **IBKR paper account** with the *same code* and the live data feed. Run for a meaningful period across different regimes.
2. Compare paper fills/slippage against your backtest assumptions; reconcile differences before risking a cent.
3. Go live with **minimal capital** and tight global caps; scale only after the live track record matches expectations. (Section 7.)

---

## 6. Suggested tech stack

- **Language:** **Python** — best ecosystem for data, backtesting, and IBKR (`ib_insync`). Keep it boring and well-typed.
- **Data / storage:**
  - Market & research data: **Parquet** files (immutable, cached) for bars; **DuckDB** or **SQLite/Postgres** for queryable history.
  - Operational state (orders, fills, positions, decisions): a transactional DB — **SQLite** to start, **Postgres** (e.g., Neon on Vercel Marketplace) when multi-process/hosted.
  - Time series at scale (optional later): TimescaleDB.
- **Scheduler / orchestration:** **cron**/systemd timers for daily strategies; a long-running event loop for intraday. **APScheduler** within the app for in-process scheduling. Add a process supervisor (systemd / Docker restart policy) so it self-heals.
- **Backtesting libraries (ideas):**
  - **`vectorbt`** — fast vectorized research/sweeps.
  - **`backtrader`** — event-driven, realistic, broker-like (and has IB integration), good for the bar `t`→`t+1` discipline.
  - **`zipline-reloaded`** — point-in-time, pipeline API.
  - Recommendation: prototype/sweep in **vectorbt**, validate the winners event-driven in **backtrader** (closer to live mechanics). Long term, an in-house event-driven engine that *shares code with live* is ideal.
- **Dashboard / monitoring:** **Streamlit** or **FastAPI + React** for an internal dashboard; **Grafana + Prometheus** for system metrics/heartbeat; alerting via **Telegram bot / email / PagerDuty**. *(This repo's public site — the design doc you're reading — is a **Next.js app deployed on Vercel**; the trading engine itself runs on your own always-on host, never as a public serverless function.)*
- **Testing/quality:** `pytest`, `mypy`, deterministic seeds, golden-file backtests in CI.

---

## 7. Build roadmap

**Phase 1 — Prototype (research harness).** Data ingestion + clean storage; implement 1–2 strategies as pure functions; quick vectorized backtest; basic plots. *Exit criteria:* you can go from data → signal → naive equity curve reproducibly.

**Phase 2 — Backtest properly.** Event-driven backtest with realistic costs/slippage, `t`→`t+1` execution, position sizing, the full risk module wired in. Walk-forward + held-out OOS. *Exit criteria:* a strategy survives honest costs, walk-forward, and OOS, with an economic rationale and parameter plateau.

**Phase 3 — Paper trade.** Wire the **same** strategy+risk code to IBKR **paper** via the execution adapter. Run live data, real order lifecycle, monitoring, alerts, reconciliation, logging. *Exit criteria:* weeks of unattended paper running; paper slippage ≈ backtest assumptions; kill-switches and reconnects proven by fault injection.

**Phase 4 — Small live deployment.** Tiny capital, conservative global caps, manual daily review. *Exit criteria:* live behavior matches paper; no operational surprises over a meaningful sample; all alerts/kill-switches fired correctly at least once in drills.

**Phase 5 — Scale carefully.** Increase size in small steps gated by realized risk metrics (not just returns). Add strategies/instruments one at a time, each re-validated. Keep a hard global drawdown halt. Review and re-test on a schedule; markets regime-shift.

---

## 8. Output artifacts

### 8.1 Sample system design (deployment shape)

```
research host / VPS (always-on, private)          public (Vercel)
┌───────────────────────────────────────┐         ┌──────────────────────┐
│  IB Gateway  ◀── socket ──  trader-bot │         │  Next.js design site │
│                              │         │         │  (this repo)         │
│  trader-bot:                 ▼         │         └──────────────────────┘
│   data → signal → risk → execution     │
│   state: SQLite/Postgres               │   alerts → Telegram/email
│   APScheduler loop + systemd supervisor │
│   structured logs → analytics          │
└───────────────────────────────────────┘
```
The engine is **never** exposed publicly and never runs as a serverless function (it needs a persistent socket to IB Gateway and durable local state). Vercel hosts only the documentation/monitoring read-views.

### 8.2 Pseudo-code — main trading loop

```python
def trading_cycle(clock, data, strategies, risk, broker, store, alerts):
    # 0. Safety preconditions — bail before doing anything risky
    if not broker.is_connected():
        broker.reconnect_with_backoff() or halt_and_alert("broker down", alerts)
    reconcile(store, broker)                 # broker is source of truth
    account = broker.get_account()
    positions = broker.get_positions()

    if risk.kill_switch_active(account, store):     # daily loss / drawdown / manual
        cancel_all_open_orders(broker)
        alerts.notify("kill-switch active — standing down")
        return

    # 1. Fresh, validated data only (no look-ahead, no stale bars)
    history = data.get_history(universe, asof=clock.now())
    if data.is_stale(history, clock.now()):
        return halt_and_alert("stale data", alerts)

    # 2. Strategies emit *intentions* (pure functions, no side effects)
    desired = {}
    for strat in strategies:
        if strat.has_warmup(history):
            desired[strat.name] = strat.signal(history)   # target weights/direction

    # 3. Risk manager has final authority -> approved target orders (or veto)
    target_orders = risk.build_orders(
        desired_signals=desired,
        positions=positions,
        account=account,
        market_state=data.market_state(),     # vol, spreads, halts, events
    )                                          # enforces caps, vol-scaling, stops

    # 4. Execute with idempotent, reconcilable orders
    for order in target_orders:
        order.client_id = make_idempotent_id(order)
        try:
            ack = broker.place_order(order)        # limit/marketable-limit default
            store.record_decision(history_snapshot, desired, order, ack)
        except BrokerError as e:
            alerts.notify(f"order failed {order}: {e}")
            store.record_error(order, e)

    # 5. Lifecycle + monitoring handled via callbacks (fills, partials, rejects)
    store.heartbeat(clock.now())               # silence => paging
```
The loop is intentionally dull: check safety → read truth → compute intention → let risk veto → execute idempotently → log everything → heartbeat. Backtest, paper, and live differ only in which `data`/`broker` adapters are injected.

### 8.3 Sample risk policy (config, version-controlled)

```yaml
risk_policy:
  account_currency: USD
  leverage:
    max_gross_exposure: 1.00        # no leverage to start
    max_net_exposure: 1.00
  position_limits:
    max_weight_single_etf: 0.20
    max_weight_single_stock: 0.08
    max_positions: 12
    max_sector_weight: 0.35
  sizing:
    method: volatility_target
    target_annual_vol: 0.10
    risk_per_trade: 0.0075          # 0.75% of equity to the stop
    kelly_fraction_cap: 0.25
  stops:
    type: atr
    atr_multiple: 3.0
    time_stop_bars: 20
  circuit_breakers:
    max_daily_loss_pct: 0.02        # stop opening new risk for the day
    drawdown_soft_pct: 0.10         # halve sizes
    drawdown_hard_pct: 0.15         # halt; require manual re-enable
  market_guards:
    max_spread_bps: 25              # skip if spread wider
    halt_on_stale_data_seconds: 120
    stand_aside_around_events: [FOMC, CPI, earnings]
    on_uncertainty: reduce_or_halt  # never increase risk
  manual_overrides:
    global_kill_switch: false       # human can force-flatten
```

### 8.4 Pre-live checklist (all must pass)

- [ ] Backtest uses point-in-time data; no look-ahead (decide `t`, fill `t+1`).
- [ ] Costs, spread, slippage modeled pessimistically; edge survives 2× costs.
- [ ] Walk-forward + untouched out-of-sample both pass; parameter plateau confirmed.
- [ ] Strategy has a written economic rationale; number of trials tracked.
- [ ] **Identical** strategy+risk code runs in backtest, paper, and live (adapters only differ).
- [ ] Risk module unit-tested: every limit, kill-switch, and veto path has a test.
- [ ] Kill-switches proven via fault injection (simulated loss, drawdown, stale data).
- [ ] Reconnect + reconciliation tested by killing IB Gateway mid-cycle; no double orders (idempotency verified).
- [ ] Partial-fill handling tested; sizing uses actual filled quantity.
- [ ] Monitoring live: dashboard, heartbeat paging, alerts on reject/disconnect/drawdown.
- [ ] Structured decision log captures input→signal→risk→order→fill→state, reproducibly.
- [ ] Secrets are not in code/repo; least-privilege API permissions.
- [ ] Paper-traded across multiple regimes; paper slippage ≈ backtest assumptions.
- [ ] Documented manual kill-switch and "flatten everything" runbook.
- [ ] Time zones/DST handled; corporate actions (splits/divs) handled in data + P&L.

---

## 9. Questions for you (minimum set to tailor the design)

1. **Capital & risk tolerance:** rough account size and the maximum drawdown you could stomach without abandoning the system?
2. **Time horizon / frequency:** daily/swing (minutes-to-days of attention) or intraday (needs an always-on event loop)?
3. **Universe:** which instruments first — broad ETFs, a specific stock list, sectors?
4. **Automation level:** fully automatic execution, or human-approves-each-order to start?
5. **Infra:** do you have an always-on machine / VPS, and which OS? (IB Gateway needs to run somewhere persistent.)
6. **IBKR account type & data subscriptions:** cash vs. margin, and do you have the market-data subscriptions you'll need?
7. **Options:** in scope now, or explicitly deferred?
8. **Constraints:** tax/account rules (e.g., PDT rule under $25k, wash sales, retirement-account restrictions) that should be encoded as hard limits?

---

## Biggest risks in the design — and mitigations

| Risk | Why it's dangerous | Mitigation |
|------|--------------------|-----------|
| **Overfitting / fake edge** | Backtest looks great, live loses; the #1 killer of retail systems | Few params, economic rationale, walk-forward, untouched OOS, 2× cost sensitivity, track trial count |
| **Backtest ≠ live (code drift)** | You validate one thing and trade another | One shared strategy+risk codebase; adapters swap only data/broker; golden-file tests in CI |
| **Silent failures / disconnects** | Bot dies or desyncs and you don't notice; positions drift unmanaged | Heartbeat paging, startup+reconnect reconciliation, "halt & alert" on any uncertainty, process supervisor |
| **Look-ahead bias** | Inflated results that can't exist live | Strict `t`→`t+1` execution, point-in-time data, no centered/full-sample-normalized indicators |
| **Underestimated costs/slippage** | Thin real edges evaporate after fills | Pessimistic cost model, marketable-limit orders, reconcile paper slippage before live |
| **Tail / regime risk** | Mean-reversion and leverage blow up in crashes | Vol targeting, hard drawdown halt, regime filters, no naked options, market-condition guards |
| **Operational / order bugs** | Duplicate or runaway orders, double-fills | Idempotent client IDs, broker-as-source-of-truth reconciliation, global kill-switch, small live caps |
| **Single broker / data dependency** | Outage or bad tick cascades | Data validation on ingest, broker reconciliation, conservative default actions, manual override path |

**Bottom line:** the engineering goal is a *boring, observable, hard-to-break* system that fails safe. Edge is hypothesized and tested skeptically; risk control is guaranteed in code. Build A+D on ETFs, prove it through backtest → paper → tiny live, and only then scale.
