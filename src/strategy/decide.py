"""
strategy/decide.py — Black-box trading strategy interface.

PUBLIC CONTRACT:
    decide_trade_action(symbol: str, tick: dict, state: dict) -> TradeSignal

    Input:
        symbol  — e.g. "C:EURUSD"
        tick    — {"bid", "ask", "mid", "timestamp"}
        state   — {"ema9", "ema21", "rsi14", "open_trade", "tick_count", ...}

    Output:
        TradeSignal with action: "BUY" | "SELL" | "CLOSE" | "HOLD"

The internals of this function are the protected strategy logic.
The rest of the framework ONLY calls decide_trade_action() — nothing inside here
is visible or accessible to the execution layer.
"""
from dataclasses import dataclass
from typing import Literal


# ── Output contract ───────────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    action: Literal["BUY", "SELL", "CLOSE", "HOLD"]
    symbol: str
    price: float
    reason: str = ""
    confidence: float = 0.0          # 0.0 – 1.0, informational


# ── Strategy constants ────────────────────────────────────────────────────────

_RSI_OVERSOLD = 35
_RSI_OVERBOUGHT = 65
_MIN_TICKS = 25          # Minimum ticks before signals fire


# ── Black-box function ────────────────────────────────────────────────────────

def decide_trade_action(symbol: str, tick: dict, state: dict) -> TradeSignal:
    """
    Protected strategy logic — EMA Crossover + RSI confirmation.

    Strategy rules:
      BUY  — EMA9 crosses above EMA21  AND  RSI < 65 (not overbought)
      SELL — EMA9 crosses below EMA21  AND  RSI > 35 (not oversold)
      CLOSE — Opposite crossover detected while in a trade
      HOLD — No actionable signal
    """
    price = tick.get("mid", 0.0)
    ema9 = state.get("ema9")
    ema21 = state.get("ema21")
    rsi = state.get("rsi14")
    open_trade = state.get("open_trade")       # "BUY" | "SELL" | None
    tick_count = state.get("tick_count", 0)

    # ── Guard: not enough data yet ────────────────────────────────────────────
    if tick_count < _MIN_TICKS or ema9 is None or ema21 is None or rsi is None:
        return TradeSignal(action="HOLD", symbol=symbol, price=price,
                           reason="Warming up indicators")

    bullish_cross = ema9 > ema21
    bearish_cross = ema9 < ema21

    # ── Close existing trade on reversal ─────────────────────────────────────
    if open_trade == "BUY" and bearish_cross and rsi > _RSI_OVERBOUGHT:
        return TradeSignal(action="CLOSE", symbol=symbol, price=price,
                           reason=f"Bearish cross | RSI={rsi:.1f}",
                           confidence=0.75)

    if open_trade == "SELL" and bullish_cross and rsi < _RSI_OVERSOLD:
        return TradeSignal(action="CLOSE", symbol=symbol, price=price,
                           reason=f"Bullish cross | RSI={rsi:.1f}",
                           confidence=0.75)

    # ── No double-entry ───────────────────────────────────────────────────────
    if open_trade is not None:
        return TradeSignal(action="HOLD", symbol=symbol, price=price,
                           reason="Trade already open")

    # ── New entry signals ─────────────────────────────────────────────────────
    if bullish_cross and rsi < _RSI_OVERBOUGHT:
        confidence = round(min(1.0, (ema9 - ema21) / ema21 * 1000 + 0.5), 2)
        return TradeSignal(action="BUY", symbol=symbol, price=price,
                           reason=f"EMA cross UP | RSI={rsi:.1f}",
                           confidence=confidence)

    if bearish_cross and rsi > _RSI_OVERSOLD:
        confidence = round(min(1.0, (ema21 - ema9) / ema21 * 1000 + 0.5), 2)
        return TradeSignal(action="SELL", symbol=symbol, price=price,
                           reason=f"EMA cross DOWN | RSI={rsi:.1f}",
                           confidence=confidence)

    return TradeSignal(action="HOLD", symbol=symbol, price=price,
                       reason="No signal")
