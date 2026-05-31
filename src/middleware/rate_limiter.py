"""
middleware/rate_limiter.py — Per-symbol signal cooldown after every trade.

After a BUY, SELL, or CLOSE is executed, the symbol enters a configurable
cooldown window. Entry signals (BUY/SELL) arriving during that window are
rejected to prevent signal flooding and over-trading.
"""
import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Enforces a per-symbol cooldown period after every executed trade.

    Designed for use in the execution engine::

        if not rate_limiter.is_allowed(symbol):
            return
        # ... execute trade ...
        rate_limiter.record_trade(symbol)

    Uses ``time.monotonic()`` exclusively — no external dependencies.
    """

    def __init__(self, cooldown_seconds: float | None = None) -> None:
        """
        Args:
            cooldown_seconds: Override the cooldown duration in seconds.
                              Defaults to ``config.SIGNAL_COOLDOWN_SECONDS``
                              when ``None``.
        """
        from src.config import config
        self._cooldown: float = (
            float(cooldown_seconds)
            if cooldown_seconds is not None
            else float(config.SIGNAL_COOLDOWN_SECONDS)
        )
        self._last_trade: dict[str, float] = {}     # symbol -> monotonic timestamp

    # ── Public API ────────────────────────────────────────────────────────────

    def is_allowed(self, symbol: str) -> bool:
        """
        Return True if a new entry signal for symbol may proceed.

        When the symbol is still in its cooldown window this method logs the
        remaining seconds and returns False.
        """
        last = self._last_trade.get(symbol)
        if last is None:
            return True
        remaining = self._cooldown - (time.monotonic() - last)
        if remaining > 0:
            logger.info(f"[RATELIMIT] {symbol} cooling down — {remaining:.0f}s remaining")
            return False
        return True

    def record_trade(self, symbol: str) -> None:
        """
        Record that a trade just completed for symbol, starting its cooldown.

        Call this after every successful BUY, SELL, or CLOSE.
        """
        self._last_trade[symbol] = time.monotonic()

    def remaining_cooldown(self, symbol: str) -> float:
        """
        Return the number of seconds remaining in the cooldown for symbol.

        Returns 0.0 when the symbol is not currently cooling down.
        """
        last = self._last_trade.get(symbol)
        if last is None:
            return 0.0
        return max(0.0, self._cooldown - (time.monotonic() - last))
