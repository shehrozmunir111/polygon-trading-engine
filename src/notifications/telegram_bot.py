"""
notifications/telegram_bot.py - Optional Telegram bot integration.

Provides trade alerts and operator commands using aiogram 3.x. The notifier is
designed to be non-critical: when Telegram is not configured or an API request
fails, the trading engine continues running.
"""
import asyncio
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from src.broker.base import OrderResult
from src.config import config
from src.strategy.decide import TradeSignal

logger = logging.getLogger(__name__)

TRADES_FILE = Path("trades") / "trades.csv"

SYMBOL_LABELS = {
    "C:EURUSD": "EUR/USD",
    "C:USDJPY": "USD/JPY",
    "C:GBPUSD": "GBP/USD",
    "C:XAUUSD": "XAU/USD",
    "X:BTCUSD": "BTC/USD",
}

ACTION_EMOJIS = {
    "BUY": "🟢",
    "SELL": "🔴",
    "CLOSE": "🟡",
}

OpenTradesProvider = Callable[[], dict[str, dict[str, float | str]]]
ShutdownCallback = Callable[[], Awaitable[None]]


def _proxy_endpoint_label(proxy: str) -> str:
    """Return a log-safe proxy label without credentials."""
    try:
        parsed = urlparse(proxy)
        host = parsed.hostname or "unknown"
        port = parsed.port or ("1080" if parsed.scheme.startswith("socks") else "8080")
        return f"{parsed.scheme}://{host}:{port}"
    except ValueError:
        return "configured proxy"


def _create_telegram_session() -> AiohttpSession:
    """Build an aiogram HTTP session, routing through TELEGRAM_PROXY when set."""
    proxy = (config.TELEGRAM_PROXY or "").strip() or None
    if proxy:
        logger.info(f"[TELEGRAM] Using proxy {_proxy_endpoint_label(proxy)} for api.telegram.org")
        return AiohttpSession(proxy=proxy, timeout=30)

    logger.warning(
        "[TELEGRAM] No proxy configured. If Telegram is blocked in your region, "
        "set TELEGRAM_PROXY in .env (e.g. socks5://127.0.0.1:1080)."
    )
    return AiohttpSession(timeout=30)


class TelegramNotifier:
    """
    Sends Telegram trade alerts and serves operator bot commands.

    The bot is enabled when TELEGRAM_BOT_TOKEN is set. Trade alerts also require
    TELEGRAM_CHAT_ID, while commands can still reply to the chat that sent them.
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        mode: str | None = None,
        open_trades_provider: Optional[OpenTradesProvider] = None,
        shutdown_callback: Optional[ShutdownCallback] = None,
    ):
        """Create a notifier and register aiogram command handlers."""
        self._token = token if token is not None else config.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID
        self._mode = mode if mode is not None else config.TRADE_MODE
        self._open_trades_provider = open_trades_provider
        self._shutdown_callback = shutdown_callback
        self._enabled = bool(self._token)
        self._polling_started = False
        self._ready_event = asyncio.Event()

        self._bot: Bot | None = (
            Bot(token=self._token, session=_create_telegram_session())
            if self._enabled
            else None
        )
        self._dispatcher: Dispatcher | None = Dispatcher() if self._enabled else None
        self._router = Router()
        self._last_command: str | None = None
        self._last_command_time: datetime | None = None
        self._register_handlers()

        if self._dispatcher:
            self._dispatcher.include_router(self._router)

    @property
    def enabled(self) -> bool:
        """Return True when Telegram is configured and the bot is enabled."""
        return self._enabled

    def set_open_trades_provider(self, provider: OpenTradesProvider):
        """Attach the engine status provider used by the /status command."""
        self._open_trades_provider = provider

    def set_shutdown_callback(self, callback: ShutdownCallback):
        """Attach the graceful engine shutdown callback used by /stop."""
        self._shutdown_callback = callback

    def _record_command(self, command: str) -> None:
        """Record the last Telegram command received for diagnostics."""
        self._last_command = command
        self._last_command_time = datetime.utcnow()
        logger.info(f"[TELEGRAM] Command recorded: {command} at {self._last_command_time.isoformat()}")

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Wait until Telegram polling has started, or return False on timeout."""
        if not self._enabled:
            return False
        if self._ready_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def get_health_status(self) -> str:
        """Return a short runtime status for the Telegram notifier."""
        if not self._enabled:
            return "disabled"
        if not self._polling_started:
            return "polling not started"
        if self._last_command:
            return f"enabled, last_command={self._last_command}, last_time={self._last_command_time.isoformat()}"
        return "enabled, no commands received yet"

    async def _prepare_bot_session(self) -> bool:
        """
        Verify the token and ensure long polling can receive updates.

        Telegram delivers updates to a webhook OR to getUpdates — not both.
        """
        if not self._bot:
            return False

        logger.info("[TELEGRAM] Connecting to api.telegram.org...")
        try:
            me = await self._bot.get_me()
            logger.info(f"[TELEGRAM] Connected as @{me.username} (id={me.id})")

            webhook = await self._bot.get_webhook_info()
            if webhook.url:
                logger.warning(
                    f"[TELEGRAM] Webhook was active ({webhook.url}); removing so polling works."
                )
            await self._bot.delete_webhook(drop_pending_updates=False)
            return True
        except TelegramAPIError as e:
            logger.error(f"[TELEGRAM] Telegram API error: {e}")
            return False
        except Exception as e:
            logger.error(
                f"[TELEGRAM] Cannot reach api.telegram.org ({type(e).__name__}: {e}). "
                "Check internet/VPN if you are in a region that blocks Telegram."
            )
            return False

    async def _register_bot_commands(self) -> None:
        """Register BotFather menu commands (non-critical)."""
        if not self._bot:
            return

        try:
            await self._bot.set_my_commands([
                BotCommand(command="start", description="Welcome message + engine status"),
                BotCommand(command="status", description="Show currently open trades"),
                BotCommand(command="help", description="Show available commands"),
                BotCommand(command="pnl", description="Show today's trade summary"),
                BotCommand(command="stop", description="Stop the trading engine"),
            ])
            logger.info("[TELEGRAM] Bot commands registered.")
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to register bot commands: {e}")

    async def start_polling(self):
        """Start Telegram long polling if the bot token is configured."""
        if not self._enabled or not self._bot or not self._dispatcher:
            logger.info("[TELEGRAM] Bot token not configured; Telegram disabled.")
            return

        try:
            while self._enabled:
                if not await self._prepare_bot_session():
                    logger.warning("[TELEGRAM] Connect failed — retrying in 10 seconds...")
                    await asyncio.sleep(10)
                    continue

                self._polling_started = True
                self._ready_event.set()
                logger.info(
                    "[TELEGRAM] Bot polling started — open t.me/PolygonTradingEngine_bot and send /start"
                )
                asyncio.create_task(self._register_bot_commands())

                try:
                    await self._dispatcher.start_polling(
                        self._bot,
                        polling_timeout=30,
                        handle_signals=False,
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except TelegramAPIError as e:
                    logger.warning(
                        f"[TELEGRAM] Polling failed with Telegram API error: {e}. Retrying in 10s."
                    )
                    self._polling_started = False
                    self._ready_event.clear()
                    await asyncio.sleep(10)
                except Exception as e:
                    logger.warning(
                        f"[TELEGRAM] Polling stopped unexpectedly: {e}. Retrying in 10s."
                    )
                    self._polling_started = False
                    self._ready_event.clear()
                    await asyncio.sleep(10)
        finally:
            self._polling_started = False
            self._ready_event.clear()
            if self._bot:
                await self._bot.session.close()
            logger.info("[TELEGRAM] Bot polling stopped.")

    async def stop_polling(self):
        """Stop Telegram long polling cleanly."""
        if not self._enabled or not self._dispatcher:
            return

        try:
            if self._polling_started:
                await self._dispatcher.stop_polling()
        except RuntimeError:
            # aiogram raises when stop_polling is called before polling starts.
            pass
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to stop polling cleanly: {e}")

    async def notify_trade(self, result: OrderResult, signal: TradeSignal):
        """Send a formatted Telegram alert for a successful trade."""
        if not self._enabled or not self._bot or not self._chat_id:
            return

        message = self._format_trade_alert(result, signal)
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=message)
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to send trade alert: {e}")
        except Exception as e:
            logger.warning(f"[TELEGRAM] Unexpected trade alert error: {e}")

    def _register_handlers(self):
        """Register aiogram Router command handlers."""

        @self._router.message(Command("start"))
        async def start(message: Message):
            """Reply with a welcome message and engine status."""
            self._record_command("start")
            logger.info(f"[TELEGRAM] /start received from chat={message.chat.id}")
            await self._safe_reply(
                message,
                "Welcome to Polygon Trading Engine.\n\n"
                f"Status: running\n"
                f"Mode: {self._mode}\n"
                f"Symbols: {', '.join(SYMBOL_LABELS.get(s, s) for s in config.SYMBOLS)}\n\n"
                "Use /help to see available commands.",
            )

        @self._router.message(Command("help"))
        async def help_command(message: Message):
            """List supported Telegram bot commands."""
            self._record_command("help")
            logger.info(f"[TELEGRAM] /help received from chat={message.chat.id}")
            await self._safe_reply(
                message,
                "Commands:\n"
                "/start - Welcome message and engine status\n"
                "/status - Show currently open trades\n"
                "/pnl - Show today's trade summary\n"
                "/stop - Gracefully stop the engine\n"
                "/help - List all commands",
            )

        @self._router.message(Command("status"))
        async def status(message: Message):
            """Reply with currently open trades from the execution engine."""
            self._record_command("status")
            logger.info(f"[TELEGRAM] /status received from chat={message.chat.id}")
            open_trades = self._open_trades_provider() if self._open_trades_provider else {}
            if not open_trades:
                await self._safe_reply(message, "No open trades.")
                return

            lines = ["Open trades:"]
            for symbol, trade in open_trades.items():
                label = SYMBOL_LABELS.get(symbol, symbol)
                action = trade.get("action", "UNKNOWN")
                entry_price = trade.get("entry_price", 0.0)
                lines.append(f"{label} | {action} | Entry: {float(entry_price):.6f}")

            await self._safe_reply(message, "\n".join(lines))

        @self._router.message(Command("pnl"))
        async def pnl(message: Message):
            """Reply with today's CSV-based trade summary."""
            self._record_command("pnl")
            logger.info(f"[TELEGRAM] /pnl received from chat={message.chat.id}")
            summary = self._today_trade_summary()
            await self._safe_reply(message, summary)

        @self._router.message(Command("stop"))
        async def stop(message: Message):
            """Request graceful engine shutdown."""
            self._record_command("stop")
            logger.info(f"[TELEGRAM] /stop received from chat={message.chat.id}")
            if not self._is_authorized_chat(message):
                await self._safe_reply(message, "This chat is not authorized to stop the engine.")
                return

            await self._safe_reply(message, "Shutdown requested. Stopping engine gracefully.")
            if self._shutdown_callback:
                try:
                    await self._shutdown_callback()
                except Exception as e:
                    logger.warning(f"[TELEGRAM] Shutdown callback failed: {e}")
                    await self._safe_reply(message, "Shutdown request failed. Check engine logs.")
            else:
                await self._safe_reply(message, "Shutdown callback is not configured.")

        @self._router.message()
        async def fallback(message: Message):
            """Log all incoming messages for diagnostics."""
            if not message.text:
                return

            logger.info(
                f"[TELEGRAM] Received message from chat={message.chat.id} text={message.text!r}"
            )
            if message.text.startswith("/"):
                logger.info(f"[TELEGRAM] Unrecognized command: {message.text!r}")
                await self._safe_reply(message, "Unknown command. Use /help to list available commands.")

        logger.info("[TELEGRAM] Command handlers registered.")

    async def _safe_reply(self, message: Message, text: str):
        """Reply to a command and log Telegram API errors instead of raising."""
        try:
            await message.answer(text)
            logger.info(f"[TELEGRAM] Replied successfully to chat={message.chat.id}")
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to reply to command: {e}")
        except Exception as e:
            logger.warning(f"[TELEGRAM] Unexpected reply error: {e}")

    def _is_authorized_chat(self, message: Message) -> bool:
        """Allow /stop only from TELEGRAM_CHAT_ID when a chat ID is configured."""
        if not self._chat_id:
            return True
        return str(message.chat.id) == str(self._chat_id)

    def _format_trade_alert(self, result: OrderResult, signal: TradeSignal) -> str:
        """Build the required human-readable trade alert message."""
        label = SYMBOL_LABELS.get(result.symbol, result.symbol)
        emoji = ACTION_EMOJIS.get(result.action, "⚪")
        confidence = round(signal.confidence * 100)
        ts = datetime.utcfromtimestamp(result.timestamp).strftime("%H:%M:%S UTC")

        return (
            f"{emoji} {result.action} | {label}\n"
            f"💰 Price: {result.price:.6f}\n"
            f"📊 Reason: {signal.reason}\n"
            f"🎯 Confidence: {confidence}%\n"
            f"🕐 Time: {ts}\n"
            f"📋 Order ID: {result.order_id}"
        )

    def _today_trade_summary(self) -> str:
        """Compute today's trade count and closed-trade wins/losses from CSV."""
        if not TRADES_FILE.exists():
            return "Today's summary:\nTotal trades: 0\nWins: 0\nLosses: 0"

        today = datetime.utcnow().date()
        total_trades = 0
        wins = 0
        losses = 0
        open_entries: dict[str, dict[str, float | str]] = {}

        try:
            with open(TRADES_FILE, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not self._is_today(row.get("timestamp_utc", ""), today):
                        continue

                    symbol = row.get("symbol", "")
                    action = row.get("action", "")
                    price = float(row.get("price") or 0.0)

                    if action in ("BUY", "SELL"):
                        open_entries[symbol] = {"action": action, "entry_price": price}
                    elif action == "CLOSE" and symbol in open_entries:
                        entry = open_entries.pop(symbol)
                        entry_action = entry["action"]
                        entry_price = float(entry["entry_price"])
                        total_trades += 1
                        is_win = (
                            price > entry_price if entry_action == "BUY"
                            else price < entry_price
                        )
                        if is_win:
                            wins += 1
                        else:
                            losses += 1
        except (OSError, ValueError, csv.Error) as e:
            logger.warning(f"[TELEGRAM] Failed to read PnL summary: {e}")
            return "Today's summary is unavailable. Check engine logs."

        return (
            "Today's summary:\n"
            f"Total trades: {total_trades}\n"
            f"Wins: {wins}\n"
            f"Losses: {losses}"
        )

    @staticmethod
    def _is_today(timestamp_utc: str, today) -> bool:
        """Return True when a CSV timestamp belongs to today's UTC date."""
        try:
            return datetime.strptime(timestamp_utc, "%Y-%m-%d %H:%M:%S").date() == today
        except ValueError:
            return False
