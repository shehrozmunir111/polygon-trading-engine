"""
middleware/botlock.py — Per-symbol async lock that drops duplicate signals.

Signals arriving while a trade is already in progress for a symbol are
dropped immediately (not queued). A watchdog task auto-releases the lock
and logs a warning if any single trade holds it beyond LOCK_TIMEOUT seconds.
"""
import asyncio
import contextlib
import logging
import time
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT: float = 10.0


class BotLock:
    """
    Per-symbol async lock middleware that prevents duplicate order execution.

    Usage::

        async with botlock.acquire("C:EURUSD") as acquired:
            if not acquired:
                return          # signal was dropped; do nothing
            # ... place order ...

    Locks are created lazily on first use for each symbol.
    If the lock is already held when acquire() is called, the signal is
    counted as dropped and the context manager yields False without
    executing the body.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        # Maps symbol -> unique token of the current lock holder.
        # Used to guard against the watchdog releasing a lock that has
        # already been handed to a new holder after auto-release.
        self._holders: dict[str, object] = {}
        self._dropped: dict[str, int] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def acquire(self, symbol: str) -> AsyncIterator[bool]:
        """
        Async context manager for a per-symbol trade lock.

        Yields:
            True  — lock acquired; the caller may proceed with the trade.
            False — lock already held; signal was dropped (logged automatically).
        """
        lock = self._get_lock(symbol)

        if lock.locked():
            self._dropped[symbol] = self._dropped.get(symbol, 0) + 1
            logger.info(f"[BOTLOCK] Signal dropped for {symbol} — trade in progress")
            yield False
            return

        await lock.acquire()
        token = object()                        # unique identity for this acquisition
        self._holders[symbol] = token
        start = time.monotonic()

        watchdog = asyncio.create_task(self._watchdog(symbol, lock, token))
        try:
            yield True
        finally:
            elapsed = time.monotonic() - start
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            # Release only if we still own the lock (watchdog may have released first)
            if self._holders.get(symbol) is token and lock.locked():
                lock.release()
                self._holders.pop(symbol, None)
            if elapsed > _LOCK_TIMEOUT:
                logger.warning(
                    f"[BOTLOCK] Lock for {symbol} held {elapsed:.1f}s "
                    f"(>{_LOCK_TIMEOUT}s) — released."
                )

    def dropped_count(self, symbol: str) -> int:
        """Return the total number of signals dropped for symbol due to an active lock."""
        return self._dropped.get(symbol, 0)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        """Return the asyncio.Lock for symbol, creating it lazily on first call."""
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]

    async def _watchdog(self, symbol: str, lock: asyncio.Lock, token: object) -> None:
        """
        Auto-release the lock after _LOCK_TIMEOUT seconds and emit a warning.

        Checks the holder token before releasing so it never accidentally
        releases a lock acquired by a newer caller after a prior auto-release.
        """
        await asyncio.sleep(_LOCK_TIMEOUT)
        if self._holders.get(symbol) is token and lock.locked():
            logger.warning(
                f"[BOTLOCK] {symbol} lock held >{_LOCK_TIMEOUT}s — "
                "auto-releasing. New signals will now be accepted."
            )
            lock.release()
            self._holders.pop(symbol, None)
