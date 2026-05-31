import asyncio
import time
from pathlib import Path

from src.broker.base import BaseBroker, OrderResult
from src.display.console import ConsoleDisplay
from src.execution.engine import ExecutionEngine
from src.ledger.receipt import ReceiptLedger
from src.middleware.botlock import BotLock
from src.middleware.rate_limiter import RateLimiter
from src.state.symbol_state import StateManager
from src.strategy.decide import TradeSignal


class DummyBroker(BaseBroker):
    def __init__(self):
        self._order_counter = 0
        self._positions = {}

    async def place_order(self, symbol: str, action: str, units: int, price: float) -> OrderResult:
        self._order_counter += 1
        order_id = f"SIM-{self._order_counter:05d}"
        self._positions[symbol] = {
            "action": action,
            "units": units,
            "entry_price": price,
            "order_id": order_id,
        }
        return OrderResult(
            success=True,
            order_id=order_id,
            symbol=symbol,
            action=action,
            units=units,
            price=price,
            timestamp=time.time(),
        )

    async def close_position(self, symbol: str, price: float) -> OrderResult:
        self._order_counter += 1
        pos = self._positions.pop(symbol, {"units": 0})
        order_id = f"SIM-CLOSE-{self._order_counter:05d}"
        return OrderResult(
            success=True,
            order_id=order_id,
            symbol=symbol,
            action="CLOSE",
            units=pos.get("units", 0),
            price=price,
            timestamp=time.time(),
        )


class DummyTradeLogger:
    def __init__(self):
        self.logged = []

    async def log(self, result: OrderResult, signal: TradeSignal):
        self.logged.append((result, signal))


class DummyNotifier:
    def __init__(self):
        self.called = []

    async def notify_trade(self, result: OrderResult, signal: TradeSignal):
        self.called.append((result, signal))


def test_handle_signal_buy_triggers_notifier_and_open_trade():
    broker = DummyBroker()
    notifier = DummyNotifier()
    engine = ExecutionEngine(
        broker=broker,
        state_manager=StateManager(["C:EURUSD"]),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=notifier,
    )

    signal = TradeSignal(
        action="BUY",
        symbol="C:EURUSD",
        price=1.08415,
        reason="EMA cross UP | RSI=58.3",
        confidence=0.72,
    )

    asyncio.run(engine.handle_signal(signal))

    open_trades = engine.get_open_trades()
    assert "C:EURUSD" in open_trades
    assert open_trades["C:EURUSD"]["action"] == "BUY"
    assert open_trades["C:EURUSD"]["entry_price"] == 1.08415
    assert len(notifier.called) == 1


def test_handle_signal_close_removes_open_trade_and_notifies():
    broker = DummyBroker()
    notifier = DummyNotifier()
    engine = ExecutionEngine(
        broker=broker,
        state_manager=StateManager(["C:EURUSD"]),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=notifier,
    )

    buy_signal = TradeSignal(
        action="BUY",
        symbol="C:EURUSD",
        price=1.08415,
        reason="EMA cross UP | RSI=58.3",
        confidence=0.72,
    )
    close_signal = TradeSignal(
        action="CLOSE",
        symbol="C:EURUSD",
        price=1.09000,
        reason="Target reached",
        confidence=0.80,
    )

    asyncio.run(engine.handle_signal(buy_signal))
    asyncio.run(engine.handle_signal(close_signal))

    open_trades = engine.get_open_trades()
    assert "C:EURUSD" not in open_trades
    assert len(notifier.called) == 2


def _make_engine(symbols=None):
    symbols = symbols or ["C:EURUSD"]
    return ExecutionEngine(
        broker=DummyBroker(),
        state_manager=StateManager(symbols),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=DummyNotifier(),
    )


def test_stop_loss_closes_buy_trade():
    engine = _make_engine()
    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08000, confidence=0.8, reason="test")
    ))
    entry = engine.get_open_trades()["C:EURUSD"]["entry_price"]
    sl = engine.get_open_trades()["C:EURUSD"]["stop_loss"]
    assert sl < entry

    # price drops below stop-loss
    asyncio.run(engine.check_stops("C:EURUSD", sl - 0.00001))
    assert "C:EURUSD" not in engine.get_open_trades()


def test_take_profit_closes_buy_trade():
    engine = _make_engine()
    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08000, confidence=0.8, reason="test")
    ))
    tp = engine.get_open_trades()["C:EURUSD"]["take_profit"]

    # price rises above take-profit
    asyncio.run(engine.check_stops("C:EURUSD", tp + 0.00001))
    assert "C:EURUSD" not in engine.get_open_trades()


def test_stop_loss_closes_sell_trade():
    engine = _make_engine()
    asyncio.run(engine.handle_signal(
        TradeSignal(action="SELL", symbol="C:EURUSD", price=1.08000, confidence=0.8, reason="test")
    ))
    sl = engine.get_open_trades()["C:EURUSD"]["stop_loss"]

    # price rises above stop-loss (for a SELL trade)
    asyncio.run(engine.check_stops("C:EURUSD", sl + 0.00001))
    assert "C:EURUSD" not in engine.get_open_trades()


def test_check_stops_no_action_within_range():
    engine = _make_engine()
    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08000, confidence=0.8, reason="test")
    ))
    # price stays between SL and TP
    asyncio.run(engine.check_stops("C:EURUSD", 1.08000))
    assert "C:EURUSD" in engine.get_open_trades()


def test_check_stops_no_open_trade():
    engine = _make_engine()
    # should not raise even with no trade open
    asyncio.run(engine.check_stops("C:EURUSD", 1.08000))


# ── BotLock integration ───────────────────────────────────────────────────────

def test_botlock_drops_duplicate_signal():
    """A second BUY on the same symbol while the first is in progress is dropped."""
    drop_event = asyncio.Event()
    results = []

    async def _run():
        bl = BotLock()
        engine = ExecutionEngine(
            broker=DummyBroker(),
            state_manager=StateManager(["C:EURUSD"]),
            trade_logger=DummyTradeLogger(),
            display=ConsoleDisplay(),
            notifier=DummyNotifier(),
            botlock=bl,
        )

        lock_held = asyncio.Event()
        allow_release = asyncio.Event()

        # Monkey-patch broker to signal when it's "inside" the trade
        original_place = engine._broker.place_order

        async def slow_place(symbol, action, units, price):
            lock_held.set()
            await allow_release.wait()
            return await original_place(symbol, action, units, price)

        engine._broker.place_order = slow_place

        signal = TradeSignal(action="BUY", symbol="C:EURUSD",
                             price=1.08, confidence=0.8, reason="t")

        async def first():
            await engine.handle_signal(signal)
            results.append("first_done")

        async def second():
            await lock_held.wait()          # wait until first is mid-trade
            await engine.handle_signal(signal)
            results.append("second_done")
            allow_release.set()

        await asyncio.gather(first(), second())

    asyncio.run(_run())
    assert "first_done" in results
    assert "second_done" in results


def test_botlock_dropped_count_increments_in_engine():
    async def _run():
        bl = BotLock()
        engine = ExecutionEngine(
            broker=DummyBroker(),
            state_manager=StateManager(["C:EURUSD"]),
            trade_logger=DummyTradeLogger(),
            display=ConsoleDisplay(),
            notifier=DummyNotifier(),
            botlock=bl,
        )

        lock_held = asyncio.Event()
        allow_release = asyncio.Event()
        original_place = engine._broker.place_order

        async def slow_place(symbol, action, units, price):
            lock_held.set()
            await allow_release.wait()
            return await original_place(symbol, action, units, price)

        engine._broker.place_order = slow_place

        sig = TradeSignal(action="BUY", symbol="C:EURUSD",
                          price=1.08, confidence=0.8, reason="t")

        async def holder():
            await engine.handle_signal(sig)

        async def dropper():
            await lock_held.wait()
            await engine.handle_signal(sig)
            allow_release.set()

        await asyncio.gather(holder(), dropper())
        assert bl.dropped_count("C:EURUSD") == 1

    asyncio.run(_run())


# ── RateLimiter integration ───────────────────────────────────────────────────

def test_rate_limiter_blocks_second_buy_during_cooldown():
    rl = RateLimiter(cooldown_seconds=60.0)
    engine = _make_engine()
    engine._rate_limiter = rl

    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08, confidence=0.8, reason="t")
    ))
    # Close the trade so a second BUY would be allowed by trade-state checks
    asyncio.run(engine.handle_signal(
        TradeSignal(action="CLOSE", symbol="C:EURUSD", price=1.09, confidence=1.0, reason="exit")
    ))
    assert "C:EURUSD" not in engine.get_open_trades()

    # Now try to BUY again — should be blocked by cooldown
    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.09, confidence=0.8, reason="t2")
    ))
    assert "C:EURUSD" not in engine.get_open_trades()


def test_rate_limiter_close_bypasses_cooldown():
    """CLOSE signals must always execute regardless of rate-limiter state."""
    rl = RateLimiter(cooldown_seconds=60.0)
    engine = _make_engine()
    engine._rate_limiter = rl

    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08, confidence=0.8, reason="t")
    ))
    # Cooldown is now active; CLOSE must still go through
    asyncio.run(engine.handle_signal(
        TradeSignal(action="CLOSE", symbol="C:EURUSD", price=1.09, confidence=1.0, reason="exit")
    ))
    assert "C:EURUSD" not in engine.get_open_trades()


# ── ReceiptLedger integration ─────────────────────────────────────────────────

def test_receipt_generated_for_buy(tmp_path):
    ledger = ReceiptLedger(secret_key="s", mode="simulation", receipts_dir=tmp_path)
    engine = ExecutionEngine(
        broker=DummyBroker(),
        state_manager=StateManager(["C:EURUSD"]),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=DummyNotifier(),
        receipt_ledger=ledger,
    )

    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08, confidence=0.8, reason="t")
    ))

    receipts = list(tmp_path.glob("*.json"))
    assert len(receipts) == 1
    data = __import__("json").loads(receipts[0].read_text())
    assert data["action"] == "BUY"
    assert data["symbol"] == "C:EURUSD"
    assert ledger.verify(data) is True


def test_receipt_generated_for_close(tmp_path):
    ledger = ReceiptLedger(secret_key="s", mode="simulation", receipts_dir=tmp_path)
    engine = ExecutionEngine(
        broker=DummyBroker(),
        state_manager=StateManager(["C:EURUSD"]),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=DummyNotifier(),
        receipt_ledger=ledger,
    )

    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08, confidence=0.8, reason="buy")
    ))
    asyncio.run(engine.handle_signal(
        TradeSignal(action="CLOSE", symbol="C:EURUSD", price=1.09, confidence=1.0, reason="close")
    ))

    receipts = list(tmp_path.glob("*.json"))
    assert len(receipts) == 2
    actions = {__import__("json").loads(r.read_text())["action"] for r in receipts}
    assert actions == {"BUY", "CLOSE"}


def test_engine_continues_when_receipt_save_fails(tmp_path):
    """Trading must not be interrupted when the ledger cannot save a receipt."""
    ledger = ReceiptLedger(secret_key="s", mode="simulation", receipts_dir=tmp_path)
    block = tmp_path / "block.txt"
    block.write_text("x")
    ledger._receipts_dir = block   # replace with a file to trigger OSError on write

    engine = ExecutionEngine(
        broker=DummyBroker(),
        state_manager=StateManager(["C:EURUSD"]),
        trade_logger=DummyTradeLogger(),
        display=ConsoleDisplay(),
        notifier=DummyNotifier(),
        receipt_ledger=ledger,
    )

    asyncio.run(engine.handle_signal(
        TradeSignal(action="BUY", symbol="C:EURUSD", price=1.08, confidence=0.8, reason="t")
    ))
    assert "C:EURUSD" in engine.get_open_trades()
