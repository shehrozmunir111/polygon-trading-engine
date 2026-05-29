"""
broker/base.py — Abstract broker interface.

All broker implementations (simulation, OANDA, etc.) must implement this.
The execution engine only talks to this interface — never to broker APIs directly.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class OrderResult:
    success: bool
    order_id: str
    symbol: str
    action: str                  # BUY | SELL | CLOSE
    units: int
    price: float
    timestamp: float
    error: Optional[str] = None


class BaseBroker(ABC):

    @abstractmethod
    async def place_order(self, symbol: str, action: str, units: int, price: float) -> OrderResult:
        ...

    @abstractmethod
    async def close_position(self, symbol: str, price: float) -> OrderResult:
        ...


# ─────────────────────────────────────────────────────────────────────────────
#  SIMULATION BROKER
# ─────────────────────────────────────────────────────────────────────────────

class SimulationBroker(BaseBroker):
    """
    Paper trading broker — executes orders locally, no API calls.
    Perfect for backtesting and GitHub demos.
    """

    def __init__(self):
        self._order_counter = 0
        self._positions: dict[str, dict] = {}

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
        pos = self._positions.pop(symbol, {})
        return OrderResult(
            success=True,
            order_id=f"SIM-CLOSE-{self._order_counter:05d}",
            symbol=symbol,
            action="CLOSE",
            units=pos.get("units", 0),
            price=price,
            timestamp=time.time(),
        )
