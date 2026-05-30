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
from src.notifications.telegram_bot import TelegramNotifier

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
        notifier: TelegramNotifier | None = None,
    ):
        self._broker = broker
        self._state = state_manager
        self._logger = trade_logger
        self._display = display
        self._notifier = notifier
        self._open_trades: dict[str, dict[str, float | str]] = {}    # symbol -> trade snapshot
        self._lock = asyncio.Lock()

    def _open_trade_count(self) -> int:
        return len(self._open_trades)

    def get_open_trades(self) -> dict[str, dict[str, float | str]]:
        """Return a copy of currently open trades for status displays."""
        return {symbol: trade.copy() for symbol, trade in self._open_trades.items()}

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
                    if self._notifier:
                        await self._notifier.notify_trade(result, signal)

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
                    self._open_trades[symbol] = {
                        "action": action,
                        "entry_price": result.price,
                        "order_id": result.order_id,
                    }
                    sym_state = self._state.get(symbol)
                    if sym_state:
                        sym_state.open_trade = action
                    self._display.trade_event(result, signal.reason)
                    self._logger.log(result, signal)
                    if self._notifier:
                        await self._notifier.notify_trade(result, signal)
