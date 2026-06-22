"""Persistent risk state: high-water mark and start-of-day equity.

Drives the drawdown and daily-loss circuit breakers. Persisted as JSON so the
breakers survive process restarts (a restart must not silently reset the HWM).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class RiskState:
    high_water_mark: float
    day_start_equity: float
    day: str  # ISO date string, e.g. "2026-06-22"

    @classmethod
    def initialize(cls, equity: float, day: str) -> "RiskState":
        return cls(high_water_mark=equity, day_start_equity=equity, day=day)

    def update(self, equity: float, day: str) -> None:
        if equity > self.high_water_mark:
            self.high_water_mark = equity
        if day != self.day:
            self.day = day
            self.day_start_equity = equity

    @classmethod
    def load_or_init(cls, path: str, equity: float, day: str) -> "RiskState":
        if path and os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            st = cls(**d)
            st.update(equity, day)
            return st
        return cls.initialize(equity, day)

    def save(self, path: str) -> None:
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
