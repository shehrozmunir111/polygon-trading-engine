"""
state/symbol_state.py — Per-symbol real-time state and indicator engine.

Maintains a rolling tick buffer per symbol and computes:
  - EMA (9, 21)
  - RSI (14)
  - Latest bid/ask/mid
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class Tick:
    symbol: str
    bid: float
    ask: float
    mid: float
    timestamp: float          # Unix ms


@dataclass
class IndicatorSnapshot:
    ema9: Optional[float] = None
    ema21: Optional[float] = None
    rsi14: Optional[float] = None


@dataclass
class SymbolState:
    symbol: str
    tick_buffer: deque = field(default_factory=lambda: deque(maxlen=200))
    last_tick: Optional[Tick] = None
    indicators: IndicatorSnapshot = field(default_factory=IndicatorSnapshot)
    open_trade: Optional[str] = None    # "BUY" | "SELL" | None

    def update(self, tick: Tick):
        self.last_tick = tick
        self.tick_buffer.append(tick.mid)
        self._compute_indicators()

    def _compute_indicators(self):
        prices = list(self.tick_buffer)
        if len(prices) >= 21:
            self.indicators.ema9 = self._ema(prices, 9)
            self.indicators.ema21 = self._ema(prices, 21)
        if len(prices) >= 15:
            self.indicators.rsi14 = self._rsi(prices, 14)

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        k = 2 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return round(ema, 6)

    @staticmethod
    def _rsi(prices: list[float], period: int) -> float:
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_gain == 0 and avg_loss == 0:
            return 50.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def to_dict(self) -> dict:
        """Serialisable snapshot — passed into decide_trade_action()."""
        return {
            "symbol": self.symbol,
            "last_tick": {
                "bid": self.last_tick.bid,
                "ask": self.last_tick.ask,
                "mid": self.last_tick.mid,
                "timestamp": self.last_tick.timestamp,
            } if self.last_tick else None,
            "ema9": self.indicators.ema9,
            "ema21": self.indicators.ema21,
            "rsi14": self.indicators.rsi14,
            "open_trade": self.open_trade,
            "tick_count": len(self.tick_buffer),
        }


class StateManager:
    """Holds SymbolState for all tracked symbols."""

    def __init__(self, symbols: list[str]):
        self._states: dict[str, SymbolState] = {s: SymbolState(symbol=s) for s in symbols}

    def update(self, tick: Tick):
        if tick.symbol in self._states:
            self._states[tick.symbol].update(tick)

    def get(self, symbol: str) -> Optional[SymbolState]:
        return self._states.get(symbol)

    def all(self) -> dict[str, SymbolState]:
        return self._states
