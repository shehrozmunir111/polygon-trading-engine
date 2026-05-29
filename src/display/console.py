"""
display/console.py — Real-time Rich console display.

Shows live tick feed, indicator values, and trade alerts
in a clean, color-coded terminal UI.
"""
import time
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from src.broker.base import OrderResult
from src.strategy.decide import TradeSignal

console = Console()

ACTION_COLORS = {
    "BUY": "bold green",
    "SELL": "bold red",
    "CLOSE": "bold yellow",
    "HOLD": "dim white",
}

SYMBOL_LABELS = {
    "C:EURUSD": "EUR/USD",
    "C:USDJPY": "USD/JPY",
    "C:GBPUSD": "GBP/USD",
    "C:XAUUSD": "XAU/USD",
    "X:BTCUSD": "BTC/USD",
}


class ConsoleDisplay:

    def tick_update(self, symbol: str, bid: float, ask: float,
                    ema9: float | None, ema21: float | None, rsi: float | None):
        """Print a single tick line — lightweight, not spammy."""
        label = SYMBOL_LABELS.get(symbol, symbol)
        spread = round((ask - bid) * 10000, 1)      # pips
        ts = datetime.utcnow().strftime("%H:%M:%S")

        ema_str = f"EMA9={ema9:.5f} EMA21={ema21:.5f}" if ema9 else "EMA warming up"
        rsi_str = f"RSI={rsi:.1f}" if rsi else ""

        console.print(
            f"[dim]{ts}[/dim]  "
            f"[cyan]{label:<10}[/cyan]  "
            f"B:[white]{bid}[/white]  A:[white]{ask}[/white]  "
            f"Spread:[yellow]{spread}p[/yellow]  "
            f"[blue]{ema_str}[/blue]  [magenta]{rsi_str}[/magenta]",
            highlight=False,
        )

    def trade_event(self, result: OrderResult, reason: str = ""):
        """Big visible banner when a trade fires."""
        color = ACTION_COLORS.get(result.action, "white")
        label = SYMBOL_LABELS.get(result.symbol, result.symbol)
        ts = datetime.utcfromtimestamp(result.timestamp).strftime("%Y-%m-%d %H:%M:%S UTC")

        table = Table(box=box.DOUBLE_EDGE, border_style=color, show_header=False, width=60)
        table.add_column("Key", style="bold", width=18)
        table.add_column("Value")

        table.add_row("🚀 ACTION", Text(result.action, style=color))
        table.add_row("Symbol", label)
        table.add_row("Price", f"{result.price:.6f}")
        table.add_row("Units", str(result.units))
        table.add_row("Order ID", result.order_id)
        table.add_row("Reason", reason)
        table.add_row("Time", ts)

        console.print()
        console.print(table)
        console.print()

    def startup_banner(self, mode: str, symbols: list[str]):
        labels = [SYMBOL_LABELS.get(s, s) for s in symbols]
        console.rule("[bold cyan]Polygon Trading Engine[/bold cyan]")
        console.print(f"  Mode:    [bold {'green' if mode == 'live' else 'yellow'}]{mode.upper()}[/bold {'green' if mode == 'live' else 'yellow'}]")
        console.print(f"  Symbols: [cyan]{', '.join(labels)}[/cyan]")
        console.print(f"  Strategy: EMA Crossover + RSI Confirmation")
        console.rule()
        console.print()

    def error(self, msg: str):
        console.print(f"[bold red][ERROR][/bold red] {msg}")
