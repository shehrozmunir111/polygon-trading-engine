"""
feeds/polygon_feed.py — Polygon.io WebSocket client.

Connects to wss://socket.polygon.io/forex (and crypto)
Subscribes to real-time quote events (Q.*) for all configured symbols.
Auto-reconnects on disconnect with exponential backoff.
"""
import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed

from src.config import config
from src.state.symbol_state import Tick

logger = logging.getLogger(__name__)

FOREX_WS_URL = "wss://socket.polygon.io/forex"
CRYPTO_WS_URL = "wss://socket.polygon.io/crypto"

# Separate symbols by feed
FOREX_SYMBOLS = [s for s in config.SYMBOLS if s.startswith("C:")]
CRYPTO_SYMBOLS = [s for s in config.SYMBOLS if s.startswith("X:")]


class PolygonFeed:
    """
    Streams real-time tick data from Polygon.io WebSocket.

    Usage:
        feed = PolygonFeed(on_tick=my_async_handler)
        await feed.run()
    """

    def __init__(self, on_tick: Callable[[Tick], Awaitable[None]]):
        self._on_tick = on_tick
        self._running = False
        self._connections = set()

    async def run(self):
        self._running = True
        tasks = []
        if FOREX_SYMBOLS:
            tasks.append(self._connect(FOREX_WS_URL, FOREX_SYMBOLS, feed="forex"))
        if CRYPTO_SYMBOLS:
            tasks.append(self._connect(CRYPTO_WS_URL, CRYPTO_SYMBOLS, feed="crypto"))
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        await asyncio.gather(
            *(ws.close() for ws in list(self._connections)),
            return_exceptions=True,
        )

    async def _connect(self, url: str, symbols: list[str], feed: str):
        backoff = 1
        while self._running:
            try:
                logger.info(f"[{feed.upper()}] Connecting to Polygon WebSocket...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._connections.add(ws)
                    try:
                        backoff = 1  # reset on successful connect
                        await self._authenticate(ws, feed)
                        await self._subscribe(ws, symbols, feed)
                        await self._listen(ws, feed)
                    finally:
                        self._connections.discard(ws)
            except ConnectionClosed as e:
                logger.warning(f"[{feed.upper()}] Connection closed: {e}. Reconnecting in {backoff}s...")
            except Exception as e:
                logger.error(f"[{feed.upper()}] Unexpected error: {e}. Reconnecting in {backoff}s...")
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)   # exponential backoff, cap 60s

    async def _authenticate(self, ws, feed: str):
        msg = await ws.recv()
        data = json.loads(msg)
        logger.debug(f"[{feed.upper()}] Auth handshake: {data}")

        await ws.send(json.dumps({"action": "auth", "params": config.POLYGON_API_KEY}))
        resp = json.loads(await ws.recv())

        if any(r.get("status") == "auth_success" for r in resp):
            logger.info(f"[{feed.upper()}] Authenticated ✓")
        else:
            raise ConnectionError(f"[{feed.upper()}] Auth failed: {resp}")

    async def _subscribe(self, ws, symbols: list[str], feed: str):
        channels = ",".join(self._subscription_channel(symbol, feed) for symbol in symbols)
        await ws.send(json.dumps({"action": "subscribe", "params": channels}))
        resp = json.loads(await ws.recv())
        logger.info(f"[{feed.upper()}] Subscribed to {channels}")
        logger.debug(f"[{feed.upper()}] Subscribe response: {resp}")

    async def _listen(self, ws, feed: str):
        logger.info(f"[{feed.upper()}] Listening for ticks...")
        async for raw in ws:
            if not self._running:
                break
            try:
                messages = json.loads(raw)
                for msg in messages:
                    tick = self._parse(msg)
                    if tick:
                        await self._on_tick(tick)
            except Exception as e:
                logger.error(f"[{feed.upper()}] Parse error: {e} | raw={raw}")

    @staticmethod
    def _parse(msg: dict) -> Tick | None:
        """Parse a Polygon quote event into a Tick."""
        ev = msg.get("ev")
        if ev not in ("C", "XQ"):      # forex quote | crypto quote
            return None

        symbol = (msg.get("pair") or msg.get("p") or "").replace("-", "")
        # Normalize: Polygon sends "EURUSD" — we prefix it
        if not symbol.startswith(("C:", "X:")):
            if ev == "C":
                symbol = f"C:{symbol}"
            else:
                symbol = f"X:{symbol}"

        bid = float(msg.get("bp", 0) or msg.get("b", 0))
        ask = float(msg.get("ap", 0) or msg.get("a", 0))
        mid = round((bid + ask) / 2, 6)
        ts = float(msg.get("t", time.time() * 1000))

        if bid == 0 or ask == 0:
            return None

        return Tick(symbol=symbol, bid=bid, ask=ask, mid=mid, timestamp=ts)

    @staticmethod
    def _subscription_channel(symbol: str, feed: str) -> str:
        """Convert internal symbols into Polygon currency websocket channels."""
        if ":" not in symbol:
            raise ValueError(f"Invalid symbol format: {symbol}")

        _, pair = symbol.split(":", 1)
        if len(pair) < 6:
            raise ValueError(f"Invalid currency pair format: {symbol}")

        polygon_pair = f"{pair[:3]}-{pair[3:]}"
        prefix = "C" if feed == "forex" else "XQ"
        return f"{prefix}.{polygon_pair}"
