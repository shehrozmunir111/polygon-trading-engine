"""
execution/engine.py — Core execution engine.

Receives TradeSignals from the strategy, enforces risk rules,
then routes to the active broker (simulation or live).

Signal execution order
----------------------
1. RateLimiter.is_allowed()      — drop entry signals during cooldown
2. BotLock.acquire()             — drop duplicate signals for the same symbol
3. Trade logic                   — broker call, state update, display
4. RateLimiter.record_trade()    — start cooldown for next entry
5. ReceiptLedger.generate()      — persist signed trade receipt
6. TradeLogger.log()             — append to CSV + structured log
7. TelegramNotifier.notify_trade() — send Telegram alert
"""
import logging

from src.broker.base import BaseBroker, OrderResult
from src.config import config
from src.ledger.receipt import ReceiptLedger
from src.middleware.botlock import BotLock
from src.middleware.rate_limiter import RateLimiter
from src.strategy.decide import TradeSignal
from src.state.symbol_state import StateManager
from src.logging_.trade_logger import TradeLogger
from src.display.console import ConsoleDisplay
from src.notifications.telegram_bot import TelegramNotifier

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Routes signals → broker and enforces risk limits.

    Broker-agnostic — works with any BaseBroker implementation.
    All three middleware components (BotLock, RateLimiter, ReceiptLedger)
    are optional; sensible defaults are created when not provided.
    """

    def __init__(
        self,
        broker: BaseBroker,
        state_manager: StateManager,
        trade_logger: TradeLogger,
        display: ConsoleDisplay,
        notifier: TelegramNotifier | None = None,
        botlock: BotLock | None = None,
        rate_limiter: RateLimiter | None = None,
        receipt_ledger: ReceiptLedger | None = None,
    ) -> None:
        self._broker = broker
        self._state = state_manager
        self._logger = trade_logger
        self._display = display
        self._notifier = notifier
        self._botlock = botlock or BotLock()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._receipt_ledger = receipt_ledger          # None → receipts disabled
        self._open_trades: dict[str, dict[str, float | str]] = {}

    # ── Public helpers ────────────────────────────────────────────────────────

    def _open_trade_count(self) -> int:
        return len(self._open_trades)

    def get_open_trades(self) -> dict[str, dict[str, float | str]]:
        """Return a copy of currently open trades for status displays."""
        return {symbol: trade.copy() for symbol, trade in self._open_trades.items()}

    # ── Signal handler ────────────────────────────────────────────────────────

    async def handle_signal(self, signal: TradeSignal) -> None:
        """
        Process a trade signal through the full middleware stack.

        HOLD signals are short-circuited before any middleware is invoked.
        CLOSE signals bypass the rate limiter so that SL/TP exits are never
        blocked by a cooldown that started when the position was opened.
        """
        if signal.action == "HOLD":
            return

        symbol = signal.symbol
        action = signal.action

        # ── Step 1: Rate limiter (entry signals only) ─────────────────────────
        # CLOSE is exempt so that stop-loss / take-profit exits are never
        # blocked by the cooldown period that started on trade entry.
        if action in ("BUY", "SELL") and not self._rate_limiter.is_allowed(symbol):
            return

        # ── Step 2: BotLock ───────────────────────────────────────────────────
        async with self._botlock.acquire(symbol) as acquired:
            if not acquired:
                return

            # ── Step 3: Trade logic ───────────────────────────────────────────
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
                    await self._post_trade(result, signal)

            elif action in ("BUY", "SELL"):
                if symbol in self._open_trades:
                    return
                if self._open_trade_count() >= config.MAX_OPEN_TRADES:
                    logger.warning(
                        f"[ENGINE] Max open trades reached ({config.MAX_OPEN_TRADES}). "
                        f"Skipping {symbol}."
                    )
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
                    await self._post_trade(result, signal)

    async def check_stops(self, symbol: str, price: float) -> None:
        """Close an open trade if price has crossed its stop-loss or take-profit level."""
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
        else:
            hit = "SL" if price >= sl else ("TP" if price <= tp else None)

        if hit:
            signal = TradeSignal(
                action="CLOSE", symbol=symbol, price=price,
                reason=f"{hit} hit @ {price:.6f}", confidence=1.0,
            )
            await self.handle_signal(signal)

    # ── Post-trade pipeline (steps 4–7) ───────────────────────────────────────

    async def _post_trade(self, result: OrderResult, signal: TradeSignal) -> None:
        """
        Execute the mandatory post-trade steps in order.

        Designed to be called inside the BotLock context, after a successful
        broker call, for both BUY/SELL entries and CLOSE exits.
        """
        # 4. Rate limiter cooldown
        self._rate_limiter.record_trade(result.symbol)

        # 5. Signed trade receipt (fail-safe — never interrupts trading)
        if self._receipt_ledger:
            try:
                self._receipt_ledger.generate(result, signal)
            except Exception as e:
                logger.warning(
                    f"[ENGINE] Receipt generation failed for {result.symbol}: {e}"
                )

        # 6. CSV / structured log
        await self._logger.log(result, signal)

        # 7. Telegram alert
        if self._notifier:
            await self._notifier.notify_trade(result, signal)
