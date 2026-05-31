# Polygon Trading Engine

An async Python algorithmic trading engine that streams live market quotes from Polygon.io, computes technical indicators, evaluates a pluggable strategy, routes orders through a broker abstraction, and exposes full operator control via Telegram.

**Execution modes**

| Mode | Description |
| :--- | :---------- |
| `simulation` | Paper execution with `SimulationBroker` — no real orders placed |
| `live` | OANDA v20 market orders (practice or live account) |

> **Risk disclaimer:** Trading involves substantial risk of loss. Always run in `simulation` mode first, review `logs/engine.log` and `trades/trades.csv`, and validate OANDA practice execution thoroughly before switching to a live account.

---

## Overview

This repository implements a production-oriented trading engine with async I/O, modular architecture, layered middleware, risk controls, tamper-proof trade receipts, structured logging, CSV trade journal, Docker packaging, and Telegram-based operator control.

External services (Polygon.io, OANDA, Telegram) are integrated through configuration. All API credentials are supplied via environment variables and are never included in the repository.

---

## Features

| # | Feature | Details |
| :- | :------ | :------ |
| 1 | **Market data** | Polygon.io WebSocket feeds for forex (`C:*`) and crypto (`X:*`) with auto-reconnect |
| 2 | **Indicators** | EMA 9, EMA 21, RSI 14 computed per symbol on a rolling tick buffer |
| 3 | **Strategy** | Black-box interface via `decide_trade_action(symbol, tick, state)` |
| 4 | **Stop-loss / Take-profit** | Per-trade SL/TP levels checked on every tick; configurable via `STOP_LOSS_PCT` and `TAKE_PROFIT_PCT` |
| 5 | **BotLock middleware** | Per-symbol async lock — duplicate signals dropped instantly, never queued |
| 6 | **Rate limiter** | Per-symbol cooldown after every trade prevents signal flooding |
| 7 | **Signed receipts** | HMAC-SHA256 signed JSON receipt for every executed trade, saved to `trades/receipts/` |
| 8 | **Brokers** | `SimulationBroker` and `OANDABroker` behind a common `BaseBroker` interface |
| 9 | **Async broker I/O** | OANDA SDK calls run in a thread pool — the event loop is never blocked |
| 10 | **Observability** | Rich console display, rotating logs (`logs/engine.log`), CSV trade journal |
| 11 | **Telegram** | Trade alerts and operator commands (`/start`, `/status`, `/pnl`, `/stop`) |
| 12 | **Proxy support** | HTTP/SOCKS5 proxy for Telegram API on restricted networks |
| 13 | **Docker** | Single-command deployment with Docker Compose |
| 14 | **Tests** | 74 passing tests covering all components |

### Configured symbols

| Internal | Market | Polygon channel |
| :--- | :--- | :--- |
| `C:USDJPY` | USD/JPY | `C.USD-JPY` |
| `C:EURUSD` | EUR/USD | `C.EUR-USD` |
| `C:GBPUSD` | GBP/USD | `C.GBP-USD` |
| `C:XAUUSD` | XAU/USD | `C.XAU-USD` |
| `X:BTCUSD` | BTC/USD | `XQ.BTC-USD` |

---

## Architecture

```text
Polygon WebSocket
      │
      ▼
  PolygonFeed          Forex and crypto WebSocket client, auto-reconnect
      │
      ▼
  StateManager         Rolling tick buffer → EMA 9, EMA 21, RSI 14
      │
      ▼
  check_stops()        Stop-loss / take-profit check on every tick
      │
      ▼
  decide_trade_action  Strategy signal: BUY | SELL | CLOSE | HOLD
      │
      ▼
  ── Middleware ──────────────────────────────────────────────────
  RateLimiter          Drop entry signals during per-symbol cooldown
  BotLock              Drop duplicate signals while trade is in progress
  ────────────────────────────────────────────────────────────────
      │
      ▼
  ExecutionEngine      Risk enforcement (max trades, no double entry)
      │
      ▼
  BaseBroker           SimulationBroker  │  OANDABroker (async, thread pool)
      │
      ▼
  ── Post-trade pipeline ─────────────────────────────────────────
  RateLimiter.record_trade()   Start cooldown
  ReceiptLedger.generate()     HMAC-signed JSON receipt
  TradeLogger.log()            CSV journal + rotating file log
  TelegramNotifier             Trade alert to operator
  ────────────────────────────────────────────────────────────────
```

---

## Project structure

```text
polygon-trading-engine/
├── main.py                       Engine entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── src/
│   ├── config.py                 Central .env loader
│   ├── broker/
│   │   ├── base.py               BaseBroker ABC + SimulationBroker
│   │   └── oanda.py              OANDABroker (async via run_in_executor)
│   ├── display/
│   │   └── console.py            Rich terminal UI
│   ├── execution/
│   │   └── engine.py             ExecutionEngine — risk rules and routing
│   ├── feeds/
│   │   └── polygon_feed.py       Polygon.io WebSocket client
│   ├── ledger/
│   │   └── receipt.py            ReceiptLedger — HMAC-signed trade receipts
│   ├── logging_/
│   │   └── trade_logger.py       Async CSV journal + rotating log
│   ├── middleware/
│   │   ├── botlock.py            BotLock — per-symbol duplicate signal guard
│   │   └── rate_limiter.py       RateLimiter — per-symbol cooldown
│   ├── notifications/
│   │   └── telegram_bot.py       aiogram bot — alerts and operator commands
│   ├── state/
│   │   └── symbol_state.py       Tick buffer and indicator computation
│   └── strategy/
│       └── decide.py             EMA crossover + RSI strategy
├── tests/
│   ├── test_botlock.py
│   ├── test_execution_engine.py
│   ├── test_polygon_feed.py
│   ├── test_rate_limiter.py
│   ├── test_receipt_ledger.py
│   ├── test_strategy.py
│   ├── test_symbol_state.py
│   └── test_telegram_bot.py
└── trades/
    ├── trades.csv                Executed trade journal
    └── receipts/                 Signed JSON receipt per trade
```

---

## Requirements

1. **Python 3.11** (matches the Docker image)
2. **Polygon.io API key** with WebSocket entitlement for live tick streaming
3. **OANDA API key and account ID** — required only for `TRADE_MODE=live`; practice environment is supported
4. **Telegram bot token and chat ID** — required for alerts and command control

Create the Telegram bot with [@BotFather](https://t.me/BotFather). Obtain your chat ID via the Bot API `getUpdates` method after sending the bot a message.

---

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Market data
POLYGON_API_KEY=your_polygon_api_key

# Broker (required only for live mode)
OANDA_API_KEY=your_oanda_api_key
OANDA_ACCOUNT_ID=your_oanda_account_id
OANDA_ENVIRONMENT=practice

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Engine
TRADE_MODE=simulation
LOG_LEVEL=INFO

# Risk
DEFAULT_UNITS=1000
MAX_OPEN_TRADES=3
STOP_LOSS_PCT=0.005
TAKE_PROFIT_PCT=0.01

# Middleware
SIGNAL_COOLDOWN_SECONDS=60

# Ledger (generate a strong random key)
RECEIPT_SECRET_KEY=your_secret_key_here
```

Generate a strong `RECEIPT_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Install and run locally

**Linux / macOS**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Windows (PowerShell)**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

### 3. Run with Docker

```bash
docker compose up --build
docker compose logs -f
docker compose down
```

The service loads `.env`, mounts `./logs` and `./trades`, and restarts automatically unless stopped.

---

## Middleware

### BotLock

Prevents duplicate orders when a strategy fires multiple signals for the same symbol before the first trade completes.

```python
async with botlock.acquire("C:EURUSD") as acquired:
    if not acquired:
        return   # signal dropped — trade already in progress
    # ... place order
```

- Lock is acquired per symbol; different symbols proceed concurrently
- Duplicate signal → logged as `[BOTLOCK] Signal dropped for {symbol}` and counted
- Watchdog auto-releases after **10 seconds** with a warning log

### RateLimiter

Enforces a cooldown period after every trade to prevent signal flooding.

- Default cooldown: **60 seconds** (configurable via `SIGNAL_COOLDOWN_SECONDS`)
- Applies to **BUY/SELL entry signals only** — CLOSE signals always pass so that stop-loss and take-profit exits are never blocked
- Logs `[RATELIMIT] {symbol} cooling down — Ns remaining` when a signal is dropped

### Stop-loss / Take-profit

Hard exit levels are computed at trade entry and checked on every tick:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `STOP_LOSS_PCT` | `0.005` | 0.5% adverse move closes the trade |
| `TAKE_PROFIT_PCT` | `0.01` | 1.0% favourable move closes the trade |

---

## Trade receipts

Every executed trade (BUY, SELL, or CLOSE) generates a signed JSON receipt saved to `trades/receipts/{uuid}.json`.

```json
{
  "receipt_id": "a1b2c3d4-...",
  "timestamp_utc": "2025-01-15T10:30:00.123456+00:00",
  "symbol": "C:EURUSD",
  "action": "BUY",
  "price": 1.084150,
  "units": 1000,
  "order_id": "SIM-00001",
  "reason": "EMA cross UP | RSI=58.3",
  "confidence": 0.72,
  "mode": "simulation",
  "signature": "3a4b5c..."
}
```

The `signature` field is an HMAC-SHA256 digest of all other fields (keys sorted, signed with `RECEIPT_SECRET_KEY`). Verify integrity programmatically:

```python
from src.ledger.receipt import ReceiptLedger
import json

ledger = ReceiptLedger()
receipt = json.loads(Path("trades/receipts/some-id.json").read_text())
print(ledger.verify(receipt))   # True if untampered
```

If a receipt cannot be saved to disk, a warning is logged and trading continues uninterrupted.

---

## Polygon.io WebSocket plan

Live streaming requires a Polygon.io subscription that includes **WebSocket access**. Keys without WebSocket entitlement receive an authentication response of:

```
Your plan doesn't include websocket access
```

When that occurs, the engine continues running — Telegram commands, simulation mode, and all non-feed components remain fully operational. Live tick ingestion resumes once a valid WebSocket key is configured.

---

## Telegram integration

The engine includes an aiogram 3.x bot that runs in the same process as the trading loop. Trade fills are pushed to `TELEGRAM_CHAT_ID` automatically.

**Setup**

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token to `TELEGRAM_BOT_TOKEN`.
2. Message the bot, then read your chat ID from the Bot API `getUpdates` response and set `TELEGRAM_CHAT_ID`.
3. Start the engine. Logs should confirm `Authenticated ✓` and polling started.

**Connectivity test**

```bash
PYTHONPATH=. python scripts/test_telegram_proxy.py
```

Expected: `OK: Python reached Telegram API`

**Proxy for restricted networks**

If `api.telegram.org` is blocked on the host, configure a proxy:

```env
TELEGRAM_PROXY=socks5://127.0.0.1:1080
```

`HTTPS_PROXY` and `HTTP_PROXY` are also read as fallbacks. The `aiohttp-socks` package is included in `requirements.txt`.

### Bot commands

| Command | Description |
| :--- | :---------- |
| `/start` | Welcome message and engine status |
| `/help` | List available commands |
| `/status` | Show currently open trades |
| `/pnl` | Today's trade summary from CSV |
| `/stop` | Gracefully stop the engine (authorised chat only) |

---

## Configuration reference

| Variable | Required | Default | Description |
| :--- | :---: | :------ | :---------- |
| `POLYGON_API_KEY` | Yes | — | Polygon.io API key |
| `OANDA_API_KEY` | Live only | — | OANDA v20 API token |
| `OANDA_ACCOUNT_ID` | Live only | — | OANDA account ID |
| `OANDA_ENVIRONMENT` | No | `practice` | `practice` or `live` |
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Yes | — | Telegram chat ID for alerts |
| `TELEGRAM_PROXY` | No | — | HTTP/SOCKS5 proxy for Telegram API |
| `TRADE_MODE` | No | `simulation` | `simulation` or `live` |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `DEFAULT_UNITS` | No | `1000` | Order size per entry |
| `MAX_OPEN_TRADES` | No | `3` | Maximum simultaneous open positions |
| `STOP_LOSS_PCT` | No | `0.005` | Stop-loss as fraction of entry price (0.5%) |
| `TAKE_PROFIT_PCT` | No | `0.01` | Take-profit as fraction of entry price (1.0%) |
| `SIGNAL_COOLDOWN_SECONDS` | No | `60` | Per-symbol cooldown after each trade |
| `RECEIPT_SECRET_KEY` | No | `trading-engine-secret` | HMAC key for signing trade receipts |

> Never commit `.env` or API credentials to version control.

---

## Data flow

For each accepted tick from the feed layer:

1. `StateManager.update()` stores the tick and recomputes EMA/RSI indicators.
2. `ExecutionEngine.check_stops()` closes any open trade that has hit its SL/TP level.
3. `ConsoleDisplay.tick_update()` prints a throttled status line (every 5 ticks).
4. `decide_trade_action()` returns a `TradeSignal`.
5. `RateLimiter.is_allowed()` — entry signals dropped if symbol is cooling down.
6. `BotLock.acquire()` — signal dropped if a trade for this symbol is in progress.
7. Broker executes the order (`SimulationBroker` or `OANDABroker`).
8. On success: `RateLimiter.record_trade()` → `ReceiptLedger.generate()` → `TradeLogger.log()` → `TelegramNotifier.notify_trade()`.

---

## Strategy contract

The strategy in `src/strategy/decide.py` implements the EMA crossover + RSI confirmation logic and must satisfy:

```python
def decide_trade_action(symbol: str, tick: dict, state: dict) -> TradeSignal:
    ...
```

**Tick input**

```python
tick = {"bid": float, "ask": float, "mid": float, "timestamp": float}
```

**State input**

```python
state = {
    "symbol": str,
    "last_tick": dict | None,
    "ema9": float | None,
    "ema21": float | None,
    "rsi14": float | None,
    "open_trade": "BUY" | "SELL" | None,
    "tick_count": int,
}
```

**Output**

```python
TradeSignal(
    action="BUY" | "SELL" | "CLOSE" | "HOLD",
    symbol="C:EURUSD",
    price=1.08415,
    reason="EMA cross UP | RSI=58.3",
    confidence=0.72,
)
```

The execution layer consumes only `TradeSignal`. Strategy internals remain fully isolated.

**Current strategy rules**

| Signal | Condition |
| :----- | :-------- |
| BUY | EMA9 > EMA21 and RSI < 65 |
| SELL | EMA9 < EMA21 and RSI > 35 |
| CLOSE BUY | EMA9 < EMA21 and RSI > 65 |
| CLOSE SELL | EMA9 > EMA21 and RSI < 35 |
| HOLD | No actionable signal or warmup period (< 25 ticks) |

---

## Broker layer

```python
async def place_order(symbol: str, action: str, units: int, price: float) -> OrderResult
async def close_position(symbol: str, price: float) -> OrderResult
```

| Implementation | Use case |
| :--- | :------- |
| `SimulationBroker` | Local paper fills with `SIM-XXXXX` order IDs |
| `OANDABroker` | OANDA v20 market orders via `run_in_executor` (non-blocking) |

| Internal symbol | OANDA instrument |
| :--- | :--- |
| `C:USDJPY` | `USD_JPY` |
| `C:EURUSD` | `EUR_USD` |
| `C:GBPUSD` | `GBP_USD` |
| `C:XAUUSD` | `XAU_USD` |
| `X:BTCUSD` | `BTC_USD` |

---

## Logs and trade journal

| Path | Purpose |
| :--- | :------ |
| `logs/engine.log` | Rotating application log (5 MB × 5 backups) |
| `trades/trades.csv` | Executed trade journal |
| `trades/receipts/*.json` | HMAC-signed receipt per trade |

CSV columns: `timestamp_utc`, `symbol`, `action`, `price`, `units`, `order_id`, `reason`, `confidence`, `mode`

---

## Testing

```bash
pip install -r requirements.txt
pytest
```

**74 tests** across 8 test files:

| File | Coverage |
| :--- | :------- |
| `test_botlock.py` | Lock acquire/drop, watchdog, dropped count, per-symbol isolation |
| `test_execution_engine.py` | Signal routing, SL/TP, BotLock integration, rate limiter, receipt generation |
| `test_polygon_feed.py` | Tick parsing, symbol normalisation, subscription channels |
| `test_rate_limiter.py` | Cooldown enforcement, expiry, `remaining_cooldown` |
| `test_receipt_ledger.py` | Field presence, HMAC signing, tamper detection, I/O failure safety |
| `test_strategy.py` | All BUY/SELL/CLOSE/HOLD signal conditions |
| `test_symbol_state.py` | EMA/RSI computation, indicator warmup, StateManager routing |
| `test_telegram_bot.py` | Trade alert formatting, PnL summary |

---

## Operational checklist

Before switching to live trading:

1. Run in `simulation` and confirm Polygon WebSocket authentication succeeds.
2. Verify ticks arrive for all configured symbols.
3. Review `trades/trades.csv`, `logs/engine.log`, and `trades/receipts/`.
4. Test all Telegram commands (`/start`, `/status`, `/pnl`, `/stop`).
5. Switch to `OANDA_ENVIRONMENT=practice` and validate order flow in `live` mode.
6. Confirm OANDA supports every configured instrument for your account type.
7. Set conservative `DEFAULT_UNITS`, `STOP_LOSS_PCT`, and `MAX_OPEN_TRADES`.
8. Set a strong random `RECEIPT_SECRET_KEY` and keep it secret.

---

## Updating a deployment

```bash
git pull
source .venv/bin/activate   # or .venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
python main.py
```

The `.env` file is local to each environment and excluded from version control.

---

## License

MIT
