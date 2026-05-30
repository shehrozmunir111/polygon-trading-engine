# Polygon Trading Engine

An async Python trading engine that ingests live market quotes, maintains per-symbol technical state, evaluates a pluggable strategy, routes orders through a broker abstraction, records every trade, and exposes operator control through Telegram.

**Execution modes**

| Mode | Description |
| :--- | :---------- |
| `simulation` | Paper execution with `SimulationBroker` |
| `live` | OANDA v20 market orders (practice or live account) |

> **Risk disclaimer:** Trading involves substantial risk. Run in `simulation` first, review `logs/engine.log` and `trades/trades.csv`, and validate OANDA practice execution before going live.

## Overview

This repository implements a production oriented trading engine: async I/O, modular boundaries, risk controls, structured logging, CSV trade journal, Docker packaging, and Telegram based operator control.

External services (Polygon.io, OANDA, Telegram) are integrated through configuration. API credentials are supplied via environment variables and are not included with the repository.

## Polygon.io market data integration

The feed layer lives in `src/feeds/polygon_feed.py`. It provides:

1. Separate WebSocket connections for Polygon forex and crypto endpoints
2. Authentication using `POLYGON_API_KEY`
3. Subscription to real time quote channels for each configured symbol
4. Tick parsing and delivery to `StateManager`
5. Automatic reconnection with backoff on disconnect

Polygon.io is the default market data provider. Strategy, execution, broker, and notification modules consume normalized ticks from `PolygonFeed` and remain independent of vendor specific APIs.

### WebSocket plan requirements

Live streaming requires a Polygon.io subscription that includes **WebSocket access**. Keys without WebSocket entitlement produce an authentication status similar to:

`Your plan doesn't include websocket access`

When that occurs:

1. The engine process continues to run
2. Telegram commands and alerts remain available
3. Simulation mode and `SimulationBroker` remain available
4. Live tick ingestion is paused until a valid WebSocket entitlement is configured or the feed module is replaced

The feed implementation can be extended or swapped for another provider without modifying strategy or execution logic.

## Features

1. **Market data:** Polygon.io WebSocket feeds for forex (`C:*`) and crypto (`X:*`)
2. **Indicators:** EMA 9, EMA 21, RSI 14 per symbol
3. **Strategy:** Black box interface via `decide_trade_action(symbol, tick, state)`
4. **Execution:** Max open trades and duplicate symbol protection
5. **Brokers:** `SimulationBroker` and `OANDABroker` behind `BaseBroker`
6. **Observability:** Rich console, rotating logs, CSV trade journal
7. **Telegram:** Trade alerts and operator commands
8. **Proxy support:** HTTP/SOCKS5 for Telegram API on restricted networks
9. **Deployment:** Docker Compose on Python 3.11

### Configured symbols

| Internal | Market | Polygon subscription |
| :--- | :--- | :------------------- |
| `C:USDJPY` | USD/JPY | `C.USD-JPY` |
| `C:EURUSD` | EUR/USD | `C.EUR-USD` |
| `C:GBPUSD` | GBP/USD | `C.GBP-USD` |
| `C:XAUUSD` | XAU/USD | `C.XAU-USD` |
| `X:BTCUSD` | BTC/USD | `XQ.BTC-USD` |

## Architecture

```text
main.py
  PolygonFeed           WebSocket quotes (forex and crypto)
  StateManager          Tick buffers and indicators
  decide_trade_action   Strategy signal (BUY, SELL, CLOSE, HOLD)
  ExecutionEngine       Risk checks and broker routing
  BaseBroker            Simulation or OANDA execution
  ConsoleDisplay        Throttled tick lines and trade banners
  TradeLogger           CSV journal and rotating logs
  TelegramNotifier      Operator commands and trade alerts
```

## Project structure

```text
polygon-trading-engine/
  main.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  .env.example
  src/
    config.py
    broker/
    display/
    execution/
    feeds/                  Polygon WebSocket
    logging_/
    notifications/          Telegram bot
    state/
    strategy/
  scripts/
    test_telegram_proxy.py
  tests/
```

## Requirements

1. **Python 3.11** for local installs (matches Docker image)
2. **Polygon.io API key** with WebSocket entitlement for live tick streaming
3. **OANDA API key and account ID** (required project credentials; practice environment supported)
4. **Telegram bot token and chat ID** (required for alerts and command control)

Create the Telegram bot with [@BotFather](https://t.me/BotFather). Obtain your chat ID via the Bot API `getUpdates` method after messaging the bot.

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
```

Required variables:

```env
POLYGON_API_KEY=your_polygon_api_key
OANDA_API_KEY=your_oanda_api_key
OANDA_ACCOUNT_ID=your_oanda_account_id
OANDA_ENVIRONMENT=practice
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TRADE_MODE=simulation
LOG_LEVEL=INFO
DEFAULT_UNITS=1000
MAX_OPEN_TRADES=3
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

The service loads `.env`, mounts `./logs` and `./trades`, and runs on Python 3.11.

## Telegram integration

The engine includes a Telegram bot built with aiogram. It runs in the same process as the trading loop and uses long polling to receive operator commands. Trade fills can be pushed to the configured chat when `TELEGRAM_CHAT_ID` is set.

**Setup**

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token into `TELEGRAM_BOT_TOKEN`.
2. Message the bot once, then read your chat ID from the Bot API `getUpdates` response and set `TELEGRAM_CHAT_ID`.
3. Start the engine. Logs should show a successful connection and `Run polling for bot @YourBotUsername`.

**Connectivity test**

```bash
PYTHONPATH=. python scripts/test_telegram_proxy.py
```

Expected output includes `OK: Python reached Telegram API`.

**Proxy for restricted networks**

If `api.telegram.org` is blocked on the host, set a proxy. Browser VPN extensions do not apply to Python.

```env
TELEGRAM_PROXY=socks5://127.0.0.1:1080
```

`HTTPS_PROXY` and `HTTP_PROXY` are also read when `TELEGRAM_PROXY` is empty. The `aiohttp-socks` package is included in `requirements.txt`.

### Bot commands

| Command | Description |
| :--- | :---------- |
| `/start` | Welcome message and engine status |
| `/help` | List available commands |
| `/status` | Show open trades |
| `/pnl` | Today's trade summary from CSV |
| `/stop` | Gracefully stop the engine (authorized chat only) |

## Configuration reference

| Variable | Required | Default | Description |
| :--- | :--- | :------ | :---------- |
| `POLYGON_API_KEY` | Yes | none | Polygon.io API key |
| `OANDA_API_KEY` | Yes | none | OANDA v20 API token |
| `OANDA_ACCOUNT_ID` | Yes | none | OANDA account ID |
| `OANDA_ENVIRONMENT` | Yes | `practice` | `practice` or `live` |
| `TELEGRAM_BOT_TOKEN` | Yes | none | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Yes | none | Telegram chat ID for alerts |
| `TRADE_MODE` | No | `simulation` | `simulation` or `live` |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `DEFAULT_UNITS` | No | `1000` | Order size per entry |
| `MAX_OPEN_TRADES` | No | `3` | Max simultaneous positions |
| `TELEGRAM_PROXY` | No | none | HTTP/SOCKS5 proxy for Telegram API |

Never commit `.env` or API tokens to version control.

## Data flow

For each accepted tick from the feed layer:

1. `StateManager.update()` stores the tick and recomputes indicators.
2. `ConsoleDisplay.tick_update()` prints a throttled status line.
3. `decide_trade_action()` returns a `TradeSignal`.
4. `ExecutionEngine.handle_signal()` enforces risk rules and calls the broker.
5. On success: update state, print a trade banner, append CSV, log to file, notify Telegram.

## Strategy contract

The strategy in `src/strategy/decide.py` must implement:

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

The execution layer only consumes `TradeSignal`. Strategy internals stay isolated.

## Broker layer

```python
async def place_order(symbol: str, action: str, units: int, price: float) -> OrderResult
async def close_position(symbol: str, price: float) -> OrderResult
```

| Implementation | Use case |
| :--- | :------- |
| `SimulationBroker` | Local paper fills with `SIM` order IDs |
| `OANDABroker` | OANDA v20 market orders |

| Internal symbol | OANDA instrument |
| :--- | :--------------- |
| `C:USDJPY` | `USD_JPY` |
| `C:EURUSD` | `EUR_USD` |
| `C:GBPUSD` | `GBP_USD` |
| `C:XAUUSD` | `XAU_USD` |
| `X:BTCUSD` | `BTC_USD` |

Instrument availability depends on the OANDA account region and type.

## Logs and trade journal

| Path | Purpose |
| :--- | :------ |
| `logs/engine.log` | Rotating application log |
| `trades/trades.csv` | Executed trade journal |

CSV columns: `timestamp_utc`, `symbol`, `action`, `price`, `units`, `order_id`, `reason`, `confidence`, `mode`

## Testing

```bash
pip install -r requirements.txt
pytest
```

## Operational checklist

Before live trading:

1. Run in `simulation` and confirm Polygon WebSocket authentication succeeds (or confirm feed replacement).
2. Verify ticks arrive for all configured symbols.
3. Review `trades/trades.csv` and `logs/engine.log`.
4. Test all Telegram commands and trade alerts.
5. Switch to `OANDA_ENVIRONMENT=practice` and validate order flow in `live` mode.
6. Confirm OANDA supports every configured instrument for the account.
7. Set conservative `DEFAULT_UNITS` and `MAX_OPEN_TRADES`.

## Updating a deployment

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The `.env` file is local to each environment and is excluded from version control.

## License

MIT
