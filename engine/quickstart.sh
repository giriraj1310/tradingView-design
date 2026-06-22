#!/usr/bin/env bash
# One-command setup + verification for the trader engine.
# Run from anywhere:  bash engine/quickstart.sh
#
# It creates a venv, installs deps (picking the right IBKR client for your
# Python version), runs the test suite, runs a backtest on free Yahoo data,
# and finally attempts to connect to IB Gateway/TWS paper trading.
set -euo pipefail
cd "$(dirname "$0")"

echo "=========================================="
echo " trader — quickstart"
echo "=========================================="

# --- pick a Python interpreter -------------------------------------------
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "ERROR: no python3 found. Install Python 3.10+."; exit 1; }
VER=$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
MINOR=$("$PY" -c 'import sys;print(sys.version_info[1])')
echo "Using $PY (Python $VER)"

# --- venv + core deps -----------------------------------------------------
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
echo "Installing core dependencies..."
pip install --quiet -r requirements.txt

# --- IBKR client by version ----------------------------------------------
if python -c 'import ib_insync' 2>/dev/null || python -c 'import ib_async' 2>/dev/null; then
  echo "IBKR client already installed."
elif [ "$MINOR" -ge 12 ]; then
  echo "Installing ib_async (Python 3.$MINOR)..."; pip install --quiet "ib_async>=1.0"
else
  echo "Installing ib_insync (Python 3.$MINOR)..."; pip install --quiet "ib_insync>=0.9.86"
fi

# --- verify ---------------------------------------------------------------
echo; echo "== tests =="; pytest -q
echo; echo "== backtest (Yahoo data) =="; python -m trader.cli backtest

echo
echo "=========================================="
echo " Now test the live IBKR paper socket:"
echo "  1. Launch IB Gateway / TWS, log into your PAPER account"
echo "     (NOT behind a corporate VPN that blocks IBKR servers)."
echo "  2. Enable API: Configure > Settings > API > Settings"
echo "       - Enable ActiveX and Socket Clients"
echo "       - Socket port = 4002 (IB Gateway paper) or 7497 (TWS paper)"
echo "       - Trusted IPs: add 127.0.0.1"
echo "  3. Then run:"
echo "       source engine/.venv/bin/activate"
echo "       python -m trader.cli check-ibkr        # read account (safe)"
echo "       python -m trader.cli paper             # dry-run (sends nothing)"
echo "       python -m trader.cli paper --live-send # send to PAPER account"
echo "=========================================="
echo
echo "Attempting a connection check now (will fail cleanly if Gateway is off)..."
python -m trader.cli check-ibkr || true
