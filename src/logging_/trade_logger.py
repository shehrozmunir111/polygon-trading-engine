"""
logging_/trade_logger.py — Structured logging + CSV trade recorder.

Every executed trade is appended to trades/trades.csv.
Application logs go to logs/engine.log (and console).
"""
import csv
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

from src.broker.base import OrderResult
from src.strategy.decide import TradeSignal

# ── Paths ─────────────────────────────────────────────────────────────────────
LOGS_DIR = Path("logs")
TRADES_DIR = Path("trades")
LOG_FILE = LOGS_DIR / "engine.log"
TRADES_FILE = TRADES_DIR / "trades.csv"

LOGS_DIR.mkdir(exist_ok=True)
TRADES_DIR.mkdir(exist_ok=True)

# ── CSV columns ───────────────────────────────────────────────────────────────
CSV_HEADERS = [
    "timestamp_utc", "symbol", "action", "price",
    "units", "order_id", "reason", "confidence", "mode",
]


def setup_logging(level: str = "INFO"):
    """Configure root logger: rotating file + rich console."""
    numeric = getattr(logging, level.upper(), logging.INFO)

    # File handler — rotates at 5MB, keeps 5 backups
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s | %(name)s | %(message)s"))

    logging.basicConfig(level=numeric, handlers=[file_handler, console_handler])
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("oandapyV20").setLevel(logging.WARNING)


class TradeLogger:
    """Appends executed trades to CSV + writes to structured log."""

    def __init__(self, mode: str):
        self._mode = mode
        self._logger = logging.getLogger("trade_logger")
        self._init_csv()

    def _init_csv(self):
        if not TRADES_FILE.exists():
            with open(TRADES_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()

    def log(self, result: OrderResult, signal: TradeSignal):
        ts = datetime.utcfromtimestamp(result.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "timestamp_utc": ts,
            "symbol": result.symbol,
            "action": result.action,
            "price": result.price,
            "units": result.units,
            "order_id": result.order_id,
            "reason": signal.reason,
            "confidence": signal.confidence,
            "mode": self._mode,
        }
        with open(TRADES_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writerow(row)

        self._logger.info(
            f"TRADE | {result.action} {result.symbol} @ {result.price} "
            f"| units={result.units} | id={result.order_id} | reason={signal.reason}"
        )
