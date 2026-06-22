"""Structured-ish logging to both console and a rotating file."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def setup(log_file: str = ".logs/trader.log", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("trader")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
