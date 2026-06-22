"""Historical bars from Yahoo Finance (free, for research/backtesting).

Returns one DataFrame per symbol with a normalized, timezone-naive
DatetimeIndex and columns: open, high, low, close, volume.
`close` is split/dividend-adjusted (auto_adjust=True) for signal research.
Responses are cached to disk so backtests are reproducible offline.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, Optional

import pandas as pd

_COLS = ["open", "high", "low", "close", "volume"]


def _cache_path(cache_dir: str, symbol: str) -> str:
    return os.path.join(cache_dir, f"{symbol.upper()}.csv")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: c.lower() for c in df.columns})
    # yfinance may return 'adj close'; with auto_adjust=True 'close' is adjusted.
    keep = [c for c in _COLS if c in df.columns]
    df = df[keep].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    return df


def load(
    symbols: Iterable[str],
    cache_dir: str = ".cache",
    start: Optional[str] = None,
    end: Optional[str] = None,
    use_cache: bool = True,
    refresh: bool = False,
) -> Dict[str, pd.DataFrame]:
    os.makedirs(cache_dir, exist_ok=True)
    out: Dict[str, pd.DataFrame] = {}
    to_fetch = []

    for sym in symbols:
        path = _cache_path(cache_dir, sym)
        if use_cache and not refresh and os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            out[sym] = _normalize(df)
        else:
            to_fetch.append(sym)

    if to_fetch:
        import yfinance as yf  # imported lazily so tests don't require network

        for sym in to_fetch:
            raw = yf.download(
                sym,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )
            if raw is None or len(raw) == 0:
                raise RuntimeError(f"No data returned for {sym}")
            df = _normalize(raw)
            df.to_csv(_cache_path(cache_dir, sym))
            out[sym] = df

    # apply start/end filtering uniformly (covers cached + fetched)
    for sym, df in out.items():
        if start:
            df = df[df.index >= pd.to_datetime(start)]
        if end:
            df = df[df.index <= pd.to_datetime(end)]
        out[sym] = df
    return out
