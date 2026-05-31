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
                    await self._logger.log(result, signal)
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
                    sl_mult = (1 - config.STOP_LOSS_PCT) if action == "BUY" else (1 + config.STOP_LOSS_PCT)
                    tp_mult = (1 + config.TAKE_PROFIT_PCT) if action == "BUY" else (1 - config.TAKE_PROFIT_PCT)
                    self._open_trades[symbol] = {
                        "action": action,
                        "entry_price": result.price,
                        "order_id": result.order_id,
                        "stop_loss": round(result.price * sl_mult, 6),
                        "take_profit": round(result.price * tp_mult, 6),
                    }
                    sym_state = self._state.get(symbol)
                    if sym_state:
                        sym_state.open_trade = action
                    self._display.trade_event(result, signal.reason)
                    await self._logger.log(result, signal)
                    if self._notifier:
                        await self._notifier.notify_trade(result, signal)

    async def check_stops(self, symbol: str, price: float):
        """Close an open trade if price has crossed its stop-loss or take-profit level."""
        async with self._lock:
            trade = self._open_trades.get(symbol)
            if not trade:
                return
            action = trade["action"]
            sl = trade.get("stop_loss")
            tp = trade.get("take_profit")
            if sl is None or tp is None:
                return

            if action == "BUY":
                hit = "SL" if price <= sl else ("TP" if price >= tp else None)
            else:  # SELL
                hit = "SL" if price >= sl else ("TP" if price <= tp else None)

        if hit:
            reason = f"{hit} hit @ {price:.6f}"
            signal = TradeSignal(action="CLOSE", symbol=symbol, price=price,
                                 reason=reason, confidence=1.0)
            await self.handle_signal(signal)
