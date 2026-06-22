"""Import shim for the Interactive Brokers Python client.

Prefers `ib_insync` (works on Python <= 3.11), falls back to `ib_async`
(the maintained drop-in fork, recommended on Python >= 3.12). Both expose the
same public API, so the rest of the engine imports from here and doesn't care
which one is installed.
"""
from __future__ import annotations

try:  # pragma: no cover - import resolution depends on the environment
    import ib_insync as _ib
except ImportError:
    try:
        import ib_async as _ib  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "No IBKR client found. Install one of:\n"
            "  pip install ib_insync   # Python <= 3.11\n"
            "  pip install ib_async    # Python >= 3.12 (maintained fork)"
        ) from e

IB = _ib.IB
Stock = _ib.Stock
Option = _ib.Option
MarketOrder = _ib.MarketOrder
LimitOrder = _ib.LimitOrder
util = _ib.util
BACKEND = _ib.__name__
