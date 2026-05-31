import pytest
from src.state.symbol_state import SymbolState, StateManager, Tick


def _make_tick(symbol: str, price: float, ts: float = 0.0) -> Tick:
    return Tick(symbol=symbol, bid=price - 0.0001, ask=price + 0.0001, mid=price, timestamp=ts)


def test_indicators_none_before_warmup():
    state = SymbolState(symbol="C:EURUSD")
    state.update(_make_tick("C:EURUSD", 1.08))
    assert state.indicators.ema9 is None
    assert state.indicators.ema21 is None
    assert state.indicators.rsi14 is None


def test_ema_available_after_21_ticks():
    state = SymbolState(symbol="C:EURUSD")
    for i in range(21):
        state.update(_make_tick("C:EURUSD", 1.08 + i * 0.0001))
    assert state.indicators.ema9 is not None
    assert state.indicators.ema21 is not None


def test_rsi_available_after_15_ticks():
    state = SymbolState(symbol="C:EURUSD")
    for i in range(15):
        state.update(_make_tick("C:EURUSD", 1.08 + i * 0.0001))
    assert state.indicators.rsi14 is not None


def test_ema_flat_series_equals_price():
    state = SymbolState(symbol="C:EURUSD")
    price = 1.08000
    for _ in range(50):
        state.update(_make_tick("C:EURUSD", price))
    # EMA of a constant series must equal the constant
    assert abs(state.indicators.ema9 - price) < 1e-5
    assert abs(state.indicators.ema21 - price) < 1e-5


def test_rsi_flat_series_returns_50():
    state = SymbolState(symbol="C:EURUSD")
    for _ in range(30):
        state.update(_make_tick("C:EURUSD", 1.08000))
    assert state.indicators.rsi14 == 50.0


def test_rsi_all_gains_returns_100():
    state = SymbolState(symbol="C:EURUSD")
    for i in range(30):
        state.update(_make_tick("C:EURUSD", 1.0 + i * 0.01))
    assert state.indicators.rsi14 == 100.0


def test_rsi_all_losses_returns_0():
    prices = [1.0 - i * 0.01 for i in range(30)]
    result = SymbolState._rsi(prices, 14)
    assert result == 0.0


def test_tick_count_in_dict():
    state = SymbolState(symbol="C:EURUSD")
    for i in range(5):
        state.update(_make_tick("C:EURUSD", 1.08))
    d = state.to_dict()
    assert d["tick_count"] == 5


def test_state_manager_routes_by_symbol():
    manager = StateManager(["C:EURUSD", "C:USDJPY"])
    tick = _make_tick("C:EURUSD", 1.08)
    manager.update(tick)
    assert manager.get("C:EURUSD").last_tick == tick
    assert manager.get("C:USDJPY").last_tick is None


def test_state_manager_ignores_unknown_symbol():
    manager = StateManager(["C:EURUSD"])
    manager.update(_make_tick("X:BTCUSD", 42000))  # should not raise
    assert manager.get("X:BTCUSD") is None
