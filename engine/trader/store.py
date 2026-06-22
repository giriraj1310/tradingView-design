"""Durable audit + idempotency store (SQLite, stdlib only).

Records every decision, order, and fill so the system is auditable and so a
restart/reconnect cannot double-send an order. The broker remains the source of
truth for positions; this store is the local mirror + audit trail.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict

from .types import Fill, Order

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, asof TEXT, mode TEXT, equity REAL,
    drawdown REAL, daily_pnl REAL, payload TEXT
);
CREATE TABLE IF NOT EXISTS orders(
    client_id TEXT PRIMARY KEY,
    ts TEXT, symbol TEXT, action TEXT, quantity INTEGER,
    order_type TEXT, status TEXT, reason TEXT, dry_run INTEGER
);
CREATE TABLE IF NOT EXISTS fills(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, client_id TEXT, symbol TEXT,
    quantity INTEGER, price REAL, commission REAL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrderStore:
    def __init__(self, path: str = ".state/trader.db"):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- idempotency ---------------------------------------------------
    def already_sent(self, client_id: str) -> bool:
        """True only if this order was already transmitted live (not dry-run)."""
        row = self.conn.execute(
            "SELECT 1 FROM orders WHERE client_id=? AND dry_run=0", (client_id,)
        ).fetchone()
        return row is not None

    # --- writes --------------------------------------------------------
    def record_decision(self, decision: dict) -> None:
        self.conn.execute(
            "INSERT INTO decisions(ts, asof, mode, equity, drawdown, daily_pnl, payload)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                _now(), str(decision.get("asof")), decision.get("mode"),
                decision.get("equity"), decision.get("drawdown"),
                decision.get("daily_pnl"), json.dumps(decision),
            ),
        )
        self.conn.commit()

    def record_order(self, order: Order, status: str, dry_run: bool) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO orders"
            "(client_id, ts, symbol, action, quantity, order_type, status, reason, dry_run)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                order.client_id, _now(), order.symbol, order.action, order.quantity,
                order.order_type, status, order.reason, 1 if dry_run else 0,
            ),
        )
        self.conn.commit()

    def record_fill(self, fill: Fill) -> None:
        self.conn.execute(
            "INSERT INTO fills(ts, client_id, symbol, quantity, price, commission)"
            " VALUES(?,?,?,?,?,?)",
            (
                (fill.timestamp or datetime.now(timezone.utc)).isoformat()
                if hasattr(fill.timestamp, "isoformat") else _now(),
                fill.order_client_id, fill.symbol, fill.quantity,
                fill.price, fill.commission,
            ),
        )
        self.conn.commit()

    # --- reads ---------------------------------------------------------
    def expected_positions(self) -> Dict[str, int]:
        """Net positions implied by recorded fills (our local mirror)."""
        rows = self.conn.execute(
            "SELECT symbol, SUM(quantity) AS q FROM fills GROUP BY symbol"
        ).fetchall()
        return {r["symbol"]: int(r["q"]) for r in rows if r["q"]}

    def close(self) -> None:
        self.conn.close()
