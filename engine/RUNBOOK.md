# Runbook — test the live IBKR paper socket on a personal machine

The engine, backtester, risk gatekeeper, and signal generation are all verified.
The one thing that needs a real IBKR connection is the **live socket**. On a
corporate-managed machine an always-on VPN (e.g. GlobalProtect) + endpoint
security typically **block IB Gateway from reaching IBKR's trading servers**
("cannot connect to server" at login). Run this on a **personal Mac/PC on a
home network** instead.

> Not financial advice. Use a **paper** account. Backtested results do not
> predict live performance.

## 0. Prerequisites
- A personal machine **not** on a corporate VPN/proxy.
- Python **3.10+** (3.11 or 3.12 recommended).
- An IBKR account with **paper trading enabled** and your **paper** username/password.
- **IB Gateway** installed: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
  (TWS works too; just use port 7497 for its paper mode.)

## 1. Get the code
```bash
git clone https://github.com/giriraj1310/tradingView-design.git
cd tradingView-design
```

## 2. One command to set up + verify (no broker needed yet)
```bash
bash engine/quickstart.sh
```
This creates a venv, installs deps (auto-picks `ib_insync` or `ib_async` for your
Python version), runs the tests, runs a backtest on free Yahoo data, and then
tries a connection check (which will fail cleanly until Gateway is up — expected).

## 3. Start IB Gateway and log into PAPER
1. Launch **IB Gateway**. In the login window set **Trading Mode = Paper Trading**.
2. Enter your **paper** username + password; complete 2FA if prompted.
3. After login: **Configure → Settings → API → Settings**:
   - ✅ **Enable ActiveX and Socket Clients**
   - **Socket port** = **4002** (IB Gateway paper). *(TWS paper = 7497.)*
   - **Trusted IPs**: add `127.0.0.1`
   - **Read-Only API**: leave **unchecked** if you want to place a test paper order.
   - Click **OK / Apply**.

If login shows "cannot connect to server": you're likely behind a VPN/proxy or
firewall. Disconnect the VPN and retry. (IBKR also has a brief daily reset around
~23:45 ET and a longer Saturday maintenance window — avoid those.)

## 4. Test the live socket
```bash
source engine/.venv/bin/activate
cd engine

python -m trader.cli check-ibkr        # connects, prints account/cash/positions/prices (READ-ONLY)
python -m trader.cli paper             # full cycle, DRY-RUN: computes real orders, sends NOTHING
python -m trader.cli paper --live-send # actually transmits orders to your PAPER account
```

### What success looks like
- `check-ibkr` prints your paper account id, Net Liquidation, cash, any positions,
  and latest prices for the universe — ending with "OK — the engine can connect."
- `paper` (dry-run) logs the risk decision and the orders it *would* send.
- `paper --live-send` places small orders you can see fill in the Gateway / Client Portal.

## 5. Config you may want to change
- Connection: `engine/config/config.yaml` → `ibkr.port` (4002 GW-paper / 7497 TWS-paper), `host`, `client_id`.
- Universe: `engine/config/config.yaml` → `universe`.
- Risk limits: `engine/config/risk_policy.yaml` (enforced regardless of strategy).
  Set `manual_overrides.global_kill_switch: true` to force-flatten and stop trading.

## Safety
- Always run `check-ibkr` and `paper` (dry-run) before `--live-send`.
- Keep it on **paper** until you've watched it across multiple sessions and the
  pre-live checklist in [`../content/design.md`](../content/design.md) is fully green.
