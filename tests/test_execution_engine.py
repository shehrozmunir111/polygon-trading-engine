import asyncio
import time

from src.broker.base import BaseBroker, OrderResult
from src.display.console import ConsoleDisplay
from src.execution.engine import ExecutionEngine
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
