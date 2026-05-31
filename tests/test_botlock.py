import asyncio
import pytest
from src.middleware.botlock import BotLock


# ── Basic acquire / release ───────────────────────────────────────────────────

def test_acquire_yields_true_when_free():
    async def _run():
        bl = BotLock()
        async with bl.acquire("C:EURUSD") as acquired:
            assert acquired is True

    asyncio.run(_run())


def test_lock_is_free_after_context_exits():
    async def _run():
        bl = BotLock()
        async with bl.acquire("C:EURUSD"):
            pass
        lock = bl._get_lock("C:EURUSD")
        assert not lock.locked()

    asyncio.run(_run())


def test_lock_released_on_exception():
    async def _run():
        bl = BotLock()
        try:
            async with bl.acquire("C:EURUSD"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        lock = bl._get_lock("C:EURUSD")
        assert not lock.locked()

    asyncio.run(_run())


# ── Drop behaviour ────────────────────────────────────────────────────────────

def test_second_acquire_yields_false_while_locked():
    """A second coroutine trying to acquire the same symbol gets False."""
    results = []

    async def _run():
        bl = BotLock()
        inner_entered = asyncio.Event()
        outer_can_proceed = asyncio.Event()

        async def holder():
            async with bl.acquire("C:EURUSD") as a:
                inner_entered.set()
                await outer_can_proceed.wait()   # hold lock until told
                results.append(("holder", a))

        async def dropper():
            await inner_entered.wait()           # wait until holder has the lock
            async with bl.acquire("C:EURUSD") as a:
                results.append(("dropper", a))
            outer_can_proceed.set()

        await asyncio.gather(holder(), dropper())

    asyncio.run(_run())
    assert ("holder", True) in results
    assert ("dropper", False) in results


def test_dropped_count_increments():
    async def _run():
        bl = BotLock()
        inner_entered = asyncio.Event()
        outer_done = asyncio.Event()

        async def holder():
            async with bl.acquire("C:EURUSD"):
                inner_entered.set()
                await outer_done.wait()

        async def dropper():
            await inner_entered.wait()
            async with bl.acquire("C:EURUSD"):
                pass
            async with bl.acquire("C:EURUSD"):
                pass
            outer_done.set()

        await asyncio.gather(holder(), dropper())
        assert bl.dropped_count("C:EURUSD") == 2

    asyncio.run(_run())


def test_dropped_count_zero_for_unseen_symbol():
    bl = BotLock()
    assert bl.dropped_count("X:BTCUSD") == 0


# ── Per-symbol independence ───────────────────────────────────────────────────

def test_different_symbols_do_not_block_each_other():
    """Locking one symbol must not prevent another symbol from proceeding."""
    results = []

    async def _run():
        bl = BotLock()
        eur_entered = asyncio.Event()
        eur_can_exit = asyncio.Event()

        async def hold_eur():
            async with bl.acquire("C:EURUSD") as a:
                eur_entered.set()
                await eur_can_exit.wait()
                results.append(("eur", a))

        async def acquire_jpy():
            await eur_entered.wait()
            async with bl.acquire("C:USDJPY") as a:
                results.append(("jpy", a))
            eur_can_exit.set()

        await asyncio.gather(hold_eur(), acquire_jpy())

    asyncio.run(_run())
    assert ("eur", True) in results
    assert ("jpy", True) in results


# ── Lazy lock creation ────────────────────────────────────────────────────────

def test_lock_created_lazily():
    bl = BotLock()
    assert "C:EURUSD" not in bl._locks
    bl._get_lock("C:EURUSD")
    assert "C:EURUSD" in bl._locks


# ── Re-acquirable after release ───────────────────────────────────────────────

def test_lock_reacquirable_after_release():
    async def _run():
        bl = BotLock()
        async with bl.acquire("C:EURUSD") as a1:
            assert a1 is True
        async with bl.acquire("C:EURUSD") as a2:
            assert a2 is True

    asyncio.run(_run())
