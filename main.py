"""
main.py — Trading Engine Entrypoint.

Wires all components together and starts the async event loop.

Usage:
    python main.py                        # reads TRADE_MODE from .env
    TRADE_MODE=simulation python main.py  # force simulation
    TRADE_MODE=live python main.py        # force live (requires OANDA keys)
"""
import asyncio
import logging
import signal
import sys

from src.config import config
from src.state.symbol_state import StateManager, Tick
from src.feeds.polygon_feed import PolygonFeed
from src.strategy.decide import decide_trade_action
from src.execution.engine import ExecutionEngine
from src.display.console import ConsoleDisplay
from src.logging_.trade_logger import setup_logging, TradeLogger
from src.notifications.telegram_bot import TelegramNotifier

# ── Broker factory ────────────────────────────────────────────────────────────
def _build_broker():
    if config.TRADE_MODE == "live":
        from src.broker.oanda import OANDABroker
        return OANDABroker()
    else:
        from src.broker.base import SimulationBroker
        return SimulationBroker()


# ── Tick throttle: only call display every N ticks per symbol ─────────────────
_DISPLAY_THROTTLE = 5
_tick_counters: dict[str, int] = {}


# ── Main orchestrator ─────────────────────────────────────────────────────────

class TradingEngine:

    def __init__(self):
        setup_logging(config.LOG_LEVEL)
        config.validate()

        self._logger = logging.getLogger("main")
        self._display = ConsoleDisplay()
        self._state = StateManager(config.SYMBOLS)
        self._trade_logger = TradeLogger(config.TRADE_MODE)
        self._broker = _build_broker()
        self._notifier = TelegramNotifier(
            token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID,
        )
        self._engine = ExecutionEngine(
            broker=self._broker,
            state_manager=self._state,
            trade_logger=self._trade_logger,
            display=self._display,
            notifier=self._notifier,
        )
        self._notifier.set_open_trades_provider(self._engine.get_open_trades)
        self._notifier.set_shutdown_callback(self.stop)
        self._bot_task: asyncio.Task | None = None
        self._feed_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._feed = PolygonFeed(on_tick=self._on_tick)

    async def _on_tick(self, tick: Tick):
        """Called for every incoming tick from Polygon."""

        # 1. Update state + indicators
        self._state.update(tick)
        sym_state = self._state.get(tick.symbol)

        # 2. Throttled display (avoid flooding console)
        _tick_counters[tick.symbol] = _tick_counters.get(tick.symbol, 0) + 1
        if _tick_counters[tick.symbol] % _DISPLAY_THROTTLE == 0:
            self._display.tick_update(
                symbol=tick.symbol,
                bid=tick.bid,
                ask=tick.ask,
                ema9=sym_state.indicators.ema9 if sym_state else None,
                ema21=sym_state.indicators.ema21 if sym_state else None,
                rsi=sym_state.indicators.rsi14 if sym_state else None,
            )

        # 3. Call black-box strategy
        if sym_state:
            signal = decide_trade_action(
                symbol=tick.symbol,
                tick={"bid": tick.bid, "ask": tick.ask, "mid": tick.mid, "timestamp": tick.timestamp},
                state=sym_state.to_dict(),
            )

            # 4. Route signal to execution engine
            if signal.action != "HOLD":
                await self._engine.handle_signal(signal)

    async def run(self):
        self._display.startup_banner(config.TRADE_MODE, config.SYMBOLS)
        self._logger.info(f"Engine starting | mode={config.TRADE_MODE} | symbols={config.SYMBOLS}")

        if self._notifier and self._notifier.enabled:
            self._bot_task = asyncio.create_task(self._notifier.start_polling())
            telegram_ok = await self._notifier.wait_until_ready(timeout=35.0)
            self._logger.info(f"Telegram notifier health: {self._notifier.get_health_status()}")
            if telegram_ok and self._notifier.get_health_status().startswith("enabled"):
                self._logger.info("Telegram bot is ready for commands.")
            else:
                self._display.error(
                    "Telegram bot could not connect within 35s. Watch for [TELEGRAM] lines — "
                    "often api.telegram.org is blocked (try VPN) or the token in .env is wrong."
                )
        else:
            self._logger.warning(
                "Telegram disabled — set TELEGRAM_BOT_TOKEN in .env and restart."
            )
            self._display.error("Telegram disabled — TELEGRAM_BOT_TOKEN is missing in .env")

        self._feed_task = asyncio.create_task(self._feed.run())
        await self._shutdown_event.wait()

    async def stop(self):
        """Stop the ticker feed and begin graceful shutdown."""
        self._logger.info("Stopping trading engine...")
        self._shutdown_event.set()
        await self._feed.stop()

    async def shutdown(self):
        """Stop Telegram polling and clean up background tasks."""
        if self._feed_task and not self._feed_task.done():
            self._feed_task.cancel()
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass

        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass

        if self._notifier and self._notifier.enabled:
            await self._notifier.stop_polling()


# ── Entry ─────────────────────────────────────────────────────────────────────

async def _main():
    engine = TradingEngine()

    loop = asyncio.get_running_loop()

    def _shutdown():
        print("\n[SHUTDOWN] Signal received. Stopping engine...")
        asyncio.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass     # Windows doesn't support add_signal_handler

    try:
        await engine.run()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] KeyboardInterrupt. Bye!")
    except Exception as e:
        logging.getLogger("main").critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(_main())
