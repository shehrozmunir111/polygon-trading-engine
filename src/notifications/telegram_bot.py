"""
notifications/telegram_bot.py — Telegram bot integration.

Provides trade alerts and operator commands using aiogram 3.x.
The notifier is non-critical: when Telegram is not configured or an API
request fails, the trading engine continues running uninterrupted.

Commands
--------
/start       Welcome message and engine status
/help        List all commands
/status      Currently open trades with entry price, SL, TP
/symbols     Live market snapshot — price, spread, indicators per symbol
/trades [n]  Last N executed trades from CSV (default 5, max 20)
/pnl         Today's win/loss summary
/performance All-time win/loss stats with per-symbol breakdown
/risk        Current risk and engine configuration
/dropped     BotLock dropped signal counts per symbol
/pause       Pause new BUY/SELL entries (authorized chat only)
/resume      Resume signal processing (authorized chat only)
/stop        Gracefully stop the engine (authorized chat only)
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
from aiogram.filters import Command, CommandObject
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

# ── Callback / provider type aliases ─────────────────────────────────────────

OpenTradesProvider  = Callable[[], dict[str, dict[str, float | str]]]
ShutdownCallback    = Callable[[], Awaitable[None]]
StateProvider       = Callable[[], dict[str, dict]]          # symbol -> SymbolState.to_dict()
DroppedCountsProvider = Callable[[], dict[str, int]]         # symbol -> dropped count
PauseCallback       = Callable[[], None]
ResumeCallback      = Callable[[], None]
PausedProvider      = Callable[[], bool]


# ── Module helpers ────────────────────────────────────────────────────────────

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
    return AiohttpSession(timeout=30)


# ── Main class ────────────────────────────────────────────────────────────────

class TelegramNotifier:
    """
    Sends Telegram trade alerts and serves operator bot commands.

    The bot is enabled when TELEGRAM_BOT_TOKEN is set. Trade alerts also
    require TELEGRAM_CHAT_ID; commands can reply to any chat that sends them.
    All provider callbacks are optional and can be attached after construction
    via the set_*() setter methods.
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        mode: str | None = None,
        open_trades_provider: Optional[OpenTradesProvider] = None,
        shutdown_callback: Optional[ShutdownCallback] = None,
    ) -> None:
        self._token   = token   if token   is not None else config.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID
        self._mode    = mode    if mode    is not None else config.TRADE_MODE

        # Providers / callbacks (set via setters after construction)
        self._open_trades_provider:   Optional[OpenTradesProvider]   = open_trades_provider
        self._shutdown_callback:      Optional[ShutdownCallback]     = shutdown_callback
        self._state_provider:         Optional[StateProvider]        = None
        self._dropped_counts_provider: Optional[DroppedCountsProvider] = None
        self._pause_callback:         Optional[PauseCallback]        = None
        self._resume_callback:        Optional[ResumeCallback]       = None
        self._paused_provider:        Optional[PausedProvider]       = None

        self._enabled = bool(self._token)
        self._polling_started = False
        self._ready_event = asyncio.Event()
        self._last_command: str | None = None
        self._last_command_time: datetime | None = None

        self._bot: Bot | None = (
            Bot(token=self._token, session=_create_telegram_session())
            if self._enabled else None
        )
        self._dispatcher: Dispatcher | None = Dispatcher() if self._enabled else None
        self._router = Router()
        self._register_handlers()

        if self._dispatcher:
            self._dispatcher.include_router(self._router)

    # ── Public properties and setters ─────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Return True when Telegram is configured and the bot is enabled."""
        return self._enabled

    def set_open_trades_provider(self, provider: OpenTradesProvider) -> None:
        """Attach the open-trades provider used by /status."""
        self._open_trades_provider = provider

    def set_shutdown_callback(self, callback: ShutdownCallback) -> None:
        """Attach the graceful shutdown callback used by /stop."""
        self._shutdown_callback = callback

    def set_state_provider(self, provider: StateProvider) -> None:
        """Attach the market-state provider used by /symbols."""
        self._state_provider = provider

    def set_dropped_counts_provider(self, provider: DroppedCountsProvider) -> None:
        """Attach the BotLock dropped-counts provider used by /dropped."""
        self._dropped_counts_provider = provider

    def set_pause_callback(self, callback: PauseCallback) -> None:
        """Attach the engine pause callback used by /pause."""
        self._pause_callback = callback

    def set_resume_callback(self, callback: ResumeCallback) -> None:
        """Attach the engine resume callback used by /resume."""
        self._resume_callback = callback

    def set_paused_provider(self, provider: PausedProvider) -> None:
        """Attach a provider that returns the engine's current paused state."""
        self._paused_provider = provider

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def _record_command(self, command: str) -> None:
        self._last_command = command
        self._last_command_time = datetime.utcnow()
        logger.info(f"[TELEGRAM] Command received: /{command} at {self._last_command_time.isoformat()}")

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Block until polling has started, or return False on timeout."""
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
        """Return a short runtime status string for the notifier."""
        if not self._enabled:
            return "disabled"
        if not self._polling_started:
            return "polling not started"
        if self._last_command:
            return (
                f"enabled, last_command={self._last_command}, "
                f"last_time={self._last_command_time.isoformat()}"
            )
        return "enabled, no commands received yet"

    # ── Polling lifecycle ─────────────────────────────────────────────────────

    async def _prepare_bot_session(self) -> bool:
        """Verify the token and clear any active webhook before polling."""
        if not self._bot:
            return False
        logger.info("[TELEGRAM] Connecting to api.telegram.org...")
        try:
            me = await self._bot.get_me()
            logger.info(f"[TELEGRAM] Connected as @{me.username} (id={me.id})")
            webhook = await self._bot.get_webhook_info()
            if webhook.url:
                logger.warning(f"[TELEGRAM] Removing active webhook ({webhook.url}).")
            await self._bot.delete_webhook(drop_pending_updates=False)
            return True
        except TelegramAPIError as e:
            logger.error(f"[TELEGRAM] Telegram API error: {e}")
            return False
        except Exception as e:
            logger.error(
                f"[TELEGRAM] Cannot reach api.telegram.org ({type(e).__name__}: {e}). "
                "Check internet/VPN if Telegram is blocked in your region."
            )
            return False

    async def _register_bot_commands(self) -> None:
        """Register the BotFather command menu (non-critical)."""
        if not self._bot:
            return
        try:
            await self._bot.set_my_commands([
                BotCommand(command="start",       description="Welcome message and engine status"),
                BotCommand(command="status",      description="Show open trades with SL/TP levels"),
                BotCommand(command="symbols",     description="Live market snapshot for all symbols"),
                BotCommand(command="trades",      description="Last N executed trades (default 5)"),
                BotCommand(command="pnl",         description="Today's win/loss summary"),
                BotCommand(command="performance", description="All-time performance by symbol"),
                BotCommand(command="risk",        description="Current risk and engine settings"),
                BotCommand(command="dropped",     description="BotLock dropped signal counts"),
                BotCommand(command="pause",       description="Pause new trade entries"),
                BotCommand(command="resume",      description="Resume signal processing"),
                BotCommand(command="stop",        description="Gracefully stop the engine"),
                BotCommand(command="help",        description="List all commands"),
            ])
            logger.info("[TELEGRAM] Bot commands registered.")
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to register bot commands: {e}")

    async def start_polling(self) -> None:
        """Start Telegram long polling. Retries automatically on transient errors."""
        if not self._enabled or not self._bot or not self._dispatcher:
            logger.info("[TELEGRAM] Bot token not configured; Telegram disabled.")
            return

        try:
            while self._enabled:
                if not await self._prepare_bot_session():
                    logger.warning("[TELEGRAM] Connect failed — retrying in 10s...")
                    await asyncio.sleep(10)
                    continue

                self._polling_started = True
                self._ready_event.set()
                logger.info("[TELEGRAM] Bot polling started.")
                asyncio.create_task(self._register_bot_commands())

                try:
                    await self._dispatcher.start_polling(
                        self._bot, polling_timeout=30, handle_signals=False,
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except TelegramAPIError as e:
                    logger.warning(f"[TELEGRAM] Polling API error: {e}. Retrying in 10s.")
                    self._polling_started = False
                    self._ready_event.clear()
                    await asyncio.sleep(10)
                except Exception as e:
                    logger.warning(f"[TELEGRAM] Polling stopped unexpectedly: {e}. Retrying in 10s.")
                    self._polling_started = False
                    self._ready_event.clear()
                    await asyncio.sleep(10)
        finally:
            self._polling_started = False
            self._ready_event.clear()
            if self._bot:
                await self._bot.session.close()
            logger.info("[TELEGRAM] Bot polling stopped.")

    async def stop_polling(self) -> None:
        """Stop long polling cleanly."""
        if not self._enabled or not self._dispatcher:
            return
        try:
            if self._polling_started:
                await self._dispatcher.stop_polling()
        except RuntimeError:
            pass
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to stop polling cleanly: {e}")

    # ── Trade alert ───────────────────────────────────────────────────────────

    async def notify_trade(self, result: OrderResult, signal: TradeSignal) -> None:
        """Push a formatted trade alert to the configured Telegram chat."""
        if not self._enabled or not self._bot or not self._chat_id:
            return
        message = self._format_trade_alert(result, signal)
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=message)
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to send trade alert: {e}")
        except Exception as e:
            logger.warning(f"[TELEGRAM] Unexpected trade alert error: {e}")

    # ── Command handlers ──────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        """Register all aiogram Router command handlers."""

        # ── /start ────────────────────────────────────────────────────────────
        @self._router.message(Command("start"))
        async def start(message: Message) -> None:
            self._record_command("start")
            is_paused = self._paused_provider() if self._paused_provider else False
            engine_status = "PAUSED (no new entries)" if is_paused else "running"
            await self._safe_reply(
                message,
                "Polygon Trading Engine\n\n"
                f"Status: {engine_status}\n"
                f"Mode:   {self._mode.upper()}\n"
                f"Symbols: {', '.join(SYMBOL_LABELS.get(s, s) for s in config.SYMBOLS)}\n\n"
                "Send /help to see all available commands.",
            )

        # ── /help ─────────────────────────────────────────────────────────────
        @self._router.message(Command("help"))
        async def help_command(message: Message) -> None:
            self._record_command("help")
            await self._safe_reply(
                message,
                "Available commands:\n\n"
                "Market\n"
                "/symbols         Live prices and indicators\n"
                "/status          Open trades with SL/TP\n"
                "/trades [n]      Last N trades (default 5)\n\n"
                "Analytics\n"
                "/pnl             Today's summary\n"
                "/performance     All-time win rate by symbol\n"
                "/dropped         BotLock dropped signal counts\n"
                "/risk            Current risk settings\n\n"
                "Control  (authorized chat only)\n"
                "/pause           Stop new entries\n"
                "/resume          Restart entries\n"
                "/stop            Shut down engine\n\n"
                "/help            Show this message",
            )

        # ── /status ───────────────────────────────────────────────────────────
        @self._router.message(Command("status"))
        async def status(message: Message) -> None:
            self._record_command("status")
            open_trades = self._open_trades_provider() if self._open_trades_provider else {}
            if not open_trades:
                await self._safe_reply(message, "No open trades.")
                return

            lines = ["Open trades:\n"]
            for symbol, trade in open_trades.items():
                label  = SYMBOL_LABELS.get(symbol, symbol)
                action = trade.get("action", "?")
                entry  = float(trade.get("entry_price", 0))
                sl     = trade.get("stop_loss")
                tp     = trade.get("take_profit")
                emoji  = ACTION_EMOJIS.get(action, "⚪")
                line   = f"{emoji} {label}  {action}  @ {entry:.6f}"
                if sl is not None:
                    line += f"\n   SL: {float(sl):.6f}  TP: {float(tp):.6f}"
                lines.append(line)

            await self._safe_reply(message, "\n".join(lines))

        # ── /symbols ──────────────────────────────────────────────────────────
        @self._router.message(Command("symbols"))
        async def symbols(message: Message) -> None:
            self._record_command("symbols")
            await self._safe_reply(message, self._format_symbols_snapshot())

        # ── /trades [n] ───────────────────────────────────────────────────────
        @self._router.message(Command("trades"))
        async def trades(message: Message, command: CommandObject) -> None:
            self._record_command("trades")
            n = 5
            if command.args:
                try:
                    n = min(max(int(command.args.strip()), 1), 20)
                except ValueError:
                    pass
            await self._safe_reply(message, self._recent_trades(n))

        # ── /pnl ──────────────────────────────────────────────────────────────
        @self._router.message(Command("pnl"))
        async def pnl(message: Message) -> None:
            self._record_command("pnl")
            await self._safe_reply(message, self._today_trade_summary())

        # ── /performance ──────────────────────────────────────────────────────
        @self._router.message(Command("performance"))
        async def performance(message: Message) -> None:
            self._record_command("performance")
            await self._safe_reply(message, self._all_time_performance())

        # ── /risk ─────────────────────────────────────────────────────────────
        @self._router.message(Command("risk"))
        async def risk(message: Message) -> None:
            self._record_command("risk")
            is_paused = self._paused_provider() if self._paused_provider else False
            await self._safe_reply(
                message,
                "Risk and engine settings:\n\n"
                f"Mode:              {self._mode.upper()}\n"
                f"Engine state:      {'PAUSED' if is_paused else 'running'}\n"
                f"Stop-loss:         {config.STOP_LOSS_PCT * 100:.2f}%\n"
                f"Take-profit:       {config.TAKE_PROFIT_PCT * 100:.2f}%\n"
                f"Max open trades:   {config.MAX_OPEN_TRADES}\n"
                f"Units per trade:   {config.DEFAULT_UNITS:,}\n"
                f"Signal cooldown:   {config.SIGNAL_COOLDOWN_SECONDS}s\n"
                f"Symbols:           {len(config.SYMBOLS)}",
            )

        # ── /dropped ──────────────────────────────────────────────────────────
        @self._router.message(Command("dropped"))
        async def dropped(message: Message) -> None:
            self._record_command("dropped")
            if not self._dropped_counts_provider:
                await self._safe_reply(message, "Dropped-counts data not available.")
                return
            counts = self._dropped_counts_provider()
            total = sum(counts.values())
            lines = ["Dropped signals (BotLock):\n"]
            for symbol in config.SYMBOLS:
                label = SYMBOL_LABELS.get(symbol, symbol)
                n = counts.get(symbol, 0)
                lines.append(f"{label}: {n}")
            lines.append(f"\nTotal: {total}")
            await self._safe_reply(message, "\n".join(lines))

        # ── /pause ────────────────────────────────────────────────────────────
        @self._router.message(Command("pause"))
        async def pause(message: Message) -> None:
            self._record_command("pause")
            if not self._is_authorized_chat(message):
                await self._safe_reply(message, "This chat is not authorized to pause the engine.")
                return
            if self._pause_callback:
                self._pause_callback()
                await self._safe_reply(
                    message,
                    "Engine paused.\n"
                    "No new BUY/SELL positions will be opened.\n"
                    "Existing trades and SL/TP exits continue normally.\n\n"
                    "Send /resume to restart entries.",
                )
            else:
                await self._safe_reply(message, "Pause callback is not configured.")

        # ── /resume ───────────────────────────────────────────────────────────
        @self._router.message(Command("resume"))
        async def resume(message: Message) -> None:
            self._record_command("resume")
            if not self._is_authorized_chat(message):
                await self._safe_reply(message, "This chat is not authorized to resume the engine.")
                return
            if self._resume_callback:
                self._resume_callback()
                await self._safe_reply(
                    message,
                    "Engine resumed.\n"
                    "Signal processing is now active.",
                )
            else:
                await self._safe_reply(message, "Resume callback is not configured.")

        # ── /stop ─────────────────────────────────────────────────────────────
        @self._router.message(Command("stop"))
        async def stop(message: Message) -> None:
            self._record_command("stop")
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

        # ── Fallback ──────────────────────────────────────────────────────────
        @self._router.message()
        async def fallback(message: Message) -> None:
            if not message.text:
                return
            logger.info(f"[TELEGRAM] Message from chat={message.chat.id}: {message.text!r}")
            if message.text.startswith("/"):
                await self._safe_reply(message, "Unknown command. Send /help to list all commands.")

        logger.info("[TELEGRAM] Command handlers registered.")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _safe_reply(self, message: Message, text: str) -> None:
        """Reply to a command; log Telegram API errors instead of raising."""
        try:
            await message.answer(text)
            logger.info(f"[TELEGRAM] Replied to chat={message.chat.id}")
        except TelegramAPIError as e:
            logger.warning(f"[TELEGRAM] Failed to reply: {e}")
        except Exception as e:
            logger.warning(f"[TELEGRAM] Unexpected reply error: {e}")

    def _is_authorized_chat(self, message: Message) -> bool:
        """Return True only for TELEGRAM_CHAT_ID when one is configured."""
        if not self._chat_id:
            return True
        return str(message.chat.id) == str(self._chat_id)

    def _format_trade_alert(self, result: OrderResult, signal: TradeSignal) -> str:
        """Build a human-readable trade alert message."""
        label      = SYMBOL_LABELS.get(result.symbol, result.symbol)
        emoji      = ACTION_EMOJIS.get(result.action, "⚪")
        confidence = round(signal.confidence * 100)
        ts         = datetime.utcfromtimestamp(result.timestamp).strftime("%H:%M:%S UTC")
        return (
            f"{emoji} {result.action} | {label}\n"
            f"💰 Price:      {result.price:.6f}\n"
            f"📊 Reason:     {signal.reason}\n"
            f"🎯 Confidence: {confidence}%\n"
            f"🕐 Time:       {ts}\n"
            f"📋 Order ID:   {result.order_id}"
        )

    def _format_symbols_snapshot(self) -> str:
        """Build a live market snapshot string for /symbols."""
        if not self._state_provider:
            return "Symbol data not available (state provider not configured)."

        states = self._state_provider()
        if not states:
            return "No symbol data received yet."

        lines = ["Live Market Snapshot\n"]
        for symbol in config.SYMBOLS:
            data       = states.get(symbol)
            label      = SYMBOL_LABELS.get(symbol, symbol)
            if not data:
                lines.append(f"{label}: no data\n")
                continue

            last_tick  = data.get("last_tick")
            if not last_tick:
                lines.append(f"{label}: no ticks yet\n")
                continue

            bid        = last_tick.get("bid", 0.0)
            ask        = last_tick.get("ask", 0.0)
            spread     = round((ask - bid) * 10000, 1)
            ema9       = data.get("ema9")
            ema21      = data.get("ema21")
            rsi        = data.get("rsi14")
            open_trade = data.get("open_trade")
            ticks      = data.get("tick_count", 0)

            ema_str    = (
                f"EMA9={ema9:.5f}  EMA21={ema21:.5f}" if ema9 and ema21 else "warming up"
            )
            rsi_str    = f"  RSI={rsi:.1f}" if rsi else ""
            trade_str  = f"{ACTION_EMOJIS.get(open_trade, '')} {open_trade}" if open_trade else "—"

            lines.append(
                f"{label}\n"
                f"  Bid: {bid}  Ask: {ask}  Spread: {spread}p\n"
                f"  {ema_str}{rsi_str}\n"
                f"  Position: {trade_str}  Ticks: {ticks}\n"
            )

        return "\n".join(lines)

    def _recent_trades(self, n: int) -> str:
        """Return a formatted string of the last n trades from CSV."""
        if not TRADES_FILE.exists():
            return "No trades recorded yet."
        try:
            with open(TRADES_FILE, newline="") as f:
                rows = list(csv.DictReader(f))
        except (OSError, csv.Error) as e:
            logger.warning(f"[TELEGRAM] Failed to read trade history: {e}")
            return "Trade history unavailable. Check engine logs."

        if not rows:
            return "No trades recorded yet."

        recent = rows[-n:]
        lines  = [f"Last {len(recent)} trade(s):\n"]
        for row in reversed(recent):
            action = row.get("action", "")
            symbol = row.get("symbol", "")
            price  = row.get("price", "")
            ts     = row.get("timestamp_utc", "")[:16]
            label  = SYMBOL_LABELS.get(symbol, symbol)
            emoji  = ACTION_EMOJIS.get(action, "⚪")
            reason = row.get("reason", "")
            lines.append(f"{ts}  {emoji} {action:<5}  {label}  @ {price}")
            if reason:
                lines.append(f"  {reason}")
        return "\n".join(lines)

    def _today_trade_summary(self) -> str:
        """Compute today's closed-trade win/loss counts from CSV."""
        if not TRADES_FILE.exists():
            return "Today's summary:\nTotal trades: 0\nWins: 0\nLosses: 0"

        today = datetime.utcnow().date()
        total, wins, losses = 0, 0, 0
        open_entries: dict[str, dict] = {}

        try:
            with open(TRADES_FILE, newline="") as f:
                for row in csv.DictReader(f):
                    if not self._is_today(row.get("timestamp_utc", ""), today):
                        continue
                    symbol = row.get("symbol", "")
                    action = row.get("action", "")
                    price  = float(row.get("price") or 0.0)
                    if action in ("BUY", "SELL"):
                        open_entries[symbol] = {"action": action, "entry_price": price}
                    elif action == "CLOSE" and symbol in open_entries:
                        entry = open_entries.pop(symbol)
                        total += 1
                        is_win = (
                            price > float(entry["entry_price"])
                            if entry["action"] == "BUY"
                            else price < float(entry["entry_price"])
                        )
                        wins += is_win
                        losses += not is_win
        except (OSError, ValueError, csv.Error) as e:
            logger.warning(f"[TELEGRAM] Failed to read today's PnL: {e}")
            return "Today's summary is unavailable. Check engine logs."

        return f"Today's summary:\nTotal trades: {total}\nWins: {wins}\nLosses: {losses}"

    def _all_time_performance(self) -> str:
        """Compute all-time win/loss stats with a per-symbol breakdown from CSV."""
        if not TRADES_FILE.exists():
            return "No trades recorded yet."

        total, wins, losses = 0, 0, 0
        by_symbol: dict[str, dict[str, int]] = {}
        open_entries: dict[str, dict] = {}

        try:
            with open(TRADES_FILE, newline="") as f:
                for row in csv.DictReader(f):
                    symbol = row.get("symbol", "")
                    action = row.get("action", "")
                    price  = float(row.get("price") or 0.0)
                    if action in ("BUY", "SELL"):
                        open_entries[symbol] = {"action": action, "entry_price": price}
                    elif action == "CLOSE" and symbol in open_entries:
                        entry   = open_entries.pop(symbol)
                        is_win  = (
                            price > float(entry["entry_price"])
                            if entry["action"] == "BUY"
                            else price < float(entry["entry_price"])
                        )
                        total  += 1
                        wins   += is_win
                        losses += not is_win
                        sym    = by_symbol.setdefault(symbol, {"total": 0, "wins": 0, "losses": 0})
                        sym["total"]  += 1
                        sym["wins"]   += is_win
                        sym["losses"] += not is_win
        except (OSError, ValueError, csv.Error) as e:
            logger.warning(f"[TELEGRAM] Failed to compute performance: {e}")
            return "Performance data unavailable. Check engine logs."

        if total == 0:
            return "No completed trades yet."

        win_rate = round(wins / total * 100, 1)
        lines = [
            "All-time performance:\n",
            f"Total trades: {total}",
            f"Wins: {wins}  Losses: {losses}",
            f"Win rate: {win_rate}%\n",
            "By symbol:",
        ]
        for symbol, s in by_symbol.items():
            label = SYMBOL_LABELS.get(symbol, symbol)
            sr    = round(s["wins"] / s["total"] * 100, 1) if s["total"] else 0
            lines.append(f"  {label}: {s['total']} trades  {s['wins']}W/{s['losses']}L  {sr}%")

        return "\n".join(lines)

    @staticmethod
    def _is_today(timestamp_utc: str, today) -> bool:
        """Return True when a CSV timestamp string falls on today's UTC date."""
        try:
            return datetime.strptime(timestamp_utc, "%Y-%m-%d %H:%M:%S").date() == today
        except ValueError:
            return False
