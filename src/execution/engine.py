"""
execution/engine.py — Core execution engine.

Receives TradeSignals from the strategy, enforces risk rules,
then routes to the active broker (simulation or live).
"""
import asyncio
import logging

from src.broker.base import BaseBroker, OrderResult
from src.config import config
from src.strategy.decide import TradeSignal
from src.state.symbol_state import StateManager
from src.logging_.trade_logger import TradeLogger
from src.display.console import ConsoleDisplay

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Routes signals → broker and enforces risk limits.
    Completely broker-agnostic — works with any BaseBroker implementation.
    """

    def __init__(
        self,
        broker: BaseBroker,
        state_manager: StateManager,
        trade_logger: TradeLogger,
        display: ConsoleDisplay,
    ):
        self._broker = broker
        self._state = state_manager
        self._logger = trade_logger
        self._display = display
        self._open_trades: dict[str, str] = {}    # symbol -> action
        self._lock = asyncio.Lock()

    def _open_trade_count(self) -> int:
        return len(self._open_trades)

    async def handle_signal(self, signal: TradeSignal):
        if signal.action == "HOLD":
            return

        async with self._lock:
            symbol = signal.symbol
            action = signal.action

            # ── CLOSE ────────────────────────────────────────────────────────
            if action == "CLOSE":
                if symbol not in self._open_trades:
                    return
                result = await self._broker.close_position(symbol, signal.price)
                if result.success:
                    del self._open_trades[symbol]
                    sym_state = self._state.get(symbol)
                    if sym_state:
                        sym_state.open_trade = None
                    self._display.trade_event(result, signal.reason)
                    self._logger.log(result, signal)

            # ── BUY / SELL ───────────────────────────────────────────────────
            elif action in ("BUY", "SELL"):
                if symbol in self._open_trades:
                    return    # already in a trade on this symbol
                if self._open_trade_count() >= config.MAX_OPEN_TRADES:
                    logger.warning(f"[ENGINE] Max open trades reached ({config.MAX_OPEN_TRADES}). Skipping {symbol}.")
                    return

                result = await self._broker.place_order(
                    symbol=symbol,
                    action=action,
                    units=config.DEFAULT_UNITS,
                    price=signal.price,
                )
                if result.success:
                    self._open_trades[symbol] = action
                    sym_state = self._state.get(symbol)
                    if sym_state:
                        sym_state.open_trade = action
                    self._display.trade_event(result, signal.reason)
                    self._logger.log(result, signal)
