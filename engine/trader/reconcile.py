"""Position reconciliation. The broker is the source of truth; this compares
what the broker reports against what our local store expected, and surfaces any
drift (missed fills, manual trades, partial fills) so a human is alerted rather
than the bot trading on a stale view of the world.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Discrepancy:
    symbol: str
    expected: int  # what our local store believed we held
    actual: int    # what the broker actually reports (authoritative)

    @property
    def delta(self) -> int:
        return self.actual - self.expected


def reconcile_positions(
    broker_positions: Dict[str, int],
    expected_positions: Dict[str, int],
) -> List[Discrepancy]:
    """Return the set of symbols where broker truth != local expectation."""
    out: List[Discrepancy] = []
    for sym in sorted(set(broker_positions) | set(expected_positions)):
        actual = int(broker_positions.get(sym, 0))
        expected = int(expected_positions.get(sym, 0))
        if actual != expected:
            out.append(Discrepancy(sym, expected, actual))
    return out
