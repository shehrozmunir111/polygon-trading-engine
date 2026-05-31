from src.strategy.decide import decide_trade_action, _MIN_TICKS, _RSI_OVERSOLD, _RSI_OVERBOUGHT


def _state(ema9, ema21, rsi, open_trade=None, tick_count=None):
    return {
        "ema9": ema9,
        "ema21": ema21,
        "rsi14": rsi,
        "open_trade": open_trade,
        "tick_count": tick_count if tick_count is not None else _MIN_TICKS,
    }


TICK = {"bid": 1.07990, "ask": 1.08010, "mid": 1.08000, "timestamp": 0}
SYM = "C:EURUSD"


def test_hold_during_warmup():
    state = _state(ema9=1.08, ema21=1.07, rsi=50, tick_count=_MIN_TICKS - 1)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"
    assert "Warming up" in sig.reason


def test_hold_when_indicators_missing():
    state = _state(ema9=None, ema21=None, rsi=None)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"


def test_buy_on_bullish_cross_rsi_not_overbought():
    state = _state(ema9=1.0810, ema21=1.0800, rsi=_RSI_OVERBOUGHT - 1)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "BUY"
    assert sig.confidence > 0


def test_no_buy_when_rsi_overbought():
    state = _state(ema9=1.0810, ema21=1.0800, rsi=_RSI_OVERBOUGHT)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"


def test_sell_on_bearish_cross_rsi_not_oversold():
    state = _state(ema9=1.0790, ema21=1.0800, rsi=_RSI_OVERSOLD + 1)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "SELL"
    assert sig.confidence > 0


def test_no_sell_when_rsi_oversold():
    state = _state(ema9=1.0790, ema21=1.0800, rsi=_RSI_OVERSOLD)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"


def test_hold_when_trade_already_open():
    state = _state(ema9=1.0810, ema21=1.0800, rsi=50, open_trade="BUY")
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"
    assert "already open" in sig.reason


def test_close_buy_on_bearish_cross_and_overbought():
    state = _state(ema9=1.0790, ema21=1.0800, rsi=_RSI_OVERBOUGHT + 1, open_trade="BUY")
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "CLOSE"


def test_no_close_buy_when_rsi_not_overbought():
    state = _state(ema9=1.0790, ema21=1.0800, rsi=_RSI_OVERBOUGHT - 1, open_trade="BUY")
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"


def test_close_sell_on_bullish_cross_and_oversold():
    state = _state(ema9=1.0810, ema21=1.0800, rsi=_RSI_OVERSOLD - 1, open_trade="SELL")
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "CLOSE"


def test_no_close_sell_when_rsi_not_oversold():
    state = _state(ema9=1.0810, ema21=1.0800, rsi=_RSI_OVERSOLD + 1, open_trade="SELL")
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"


def test_hold_when_no_signal():
    # EMA9 == EMA21 → no cross → HOLD
    state = _state(ema9=1.0800, ema21=1.0800, rsi=50)
    sig = decide_trade_action(SYM, TICK, state)
    assert sig.action == "HOLD"
    assert sig.reason == "No signal"
