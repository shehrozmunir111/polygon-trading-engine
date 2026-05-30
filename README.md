# Polygon Trading Engine

An async Python trading engine that streams live Polygon.io currency quotes, maintains per-symbol indicator state, routes strategy signals through a broker abstraction, and records every executed trade.

The project supports two execution modes:

- `simulation`: local paper execution with no broker account required.
- `live`: OANDA v20 market-order execution using a practice or live account.

> Trading involves risk. Run the engine in `simulation` mode first, review the generated logs and CSV trades, and use OANDA practice credentials before using a live account.

## Features

- Polygon.io WebSocket ingestion for separate forex and crypto feeds.
- Five configured symbols: `C:USDJPY`, `C:EURUSD`, `C:GBPUSD`, `C:XAUUSD`, `X:BTCUSD`.
- Current Polygon currency quote subscriptions:
  - Forex: `C.USD-JPY`, `C.EUR-USD`, `C.GBP-USD`, `C.XAU-USD`
  - Crypto: `XQ.BTC-USD`
- Auto-reconnect with exponential backoff after WebSocket disconnects.
- Per-symbol state with rolling tick buffers, EMA 9, EMA 21, and RSI 14.
- Black-box strategy interface through `decide_trade_action(symbol, tick, state)`.
- Broker abstraction with simulation and OANDA implementations.
- Risk controls for duplicate symbol entries and maximum open trades.
- Rich console output with throttled tick updates and color-coded trade banners.
- CSV trade journal at `trades/trades.csv`.
- Rotating application log at `logs/engine.log`.
- Docker-ready runtime using Python 3.11.

## Architecture

```text
main.py
  -> PolygonFeed              streams Polygon forex and crypto quotes
  -> StateManager             updates per-symbol tick state and indicators
  -> decide_trade_action      returns BUY, SELL, CLOSE, or HOLD
  -> ExecutionEngine          enforces trade rules and routes orders
  -> BaseBroker               simulation or OANDA execution
  -> ConsoleDisplay           tick and trade output
  -> TradeLogger              CSV and rotating file logs
```

## Project Structure

```text
polygon-trading-engine/
  src/
    broker/
      base.py                 BaseBroker, OrderResult, SimulationBroker
      oanda.py                OANDA v20 broker implementation
    display/
      console.py              Rich console display
    execution/
      engine.py               Signal routing and risk controls
    feeds/
      polygon_feed.py         Polygon.io WebSocket client
    logging_/
      trade_logger.py         CSV trade journal and rotating logs
    state/
      symbol_state.py         Tick model, state manager, indicators
    strategy/
      decide.py               Black-box strategy interface
    config.py                 Environment-backed configuration
  main.py                     Async application entrypoint
  requirements.txt            Python dependencies
  Dockerfile                  Python 3.11 container image
  docker-compose.yml          Runtime service, volumes, env file
  .env.example                Example configuration
```

## Quickstart

### 1. Configure Environment

Copy the example environment file and add your keys:

```bash
cp .env.example .env
```

Minimum configuration for simulation:

```env
POLYGON_API_KEY=your_polygon_api_key
TRADE_MODE=simulation
LOG_LEVEL=INFO
DEFAULT_UNITS=1000
MAX_OPEN_TRADES=3
```

For OANDA practice or live execution, also set:

```env
OANDA_API_KEY=your_oanda_api_key
OANDA_ACCOUNT_ID=your_oanda_account_id
OANDA_ENVIRONMENT=practice
TRADE_MODE=live
```

### Telegram Bot

If you want Telegram trade alerts and command control, add:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

If `TELEGRAM_CHAT_ID` is left blank, the bot can still receive commands; trade alerts require the chat ID.

### 2. Run with Docker

Docker is the recommended way to run the project because the image uses Python 3.11, matching the project dependencies.

```bash
docker compose up --build
```

Follow logs from an already running container:

```bash
docker compose logs -f
```

Stop the engine:

```bash
docker compose down
```

### 3. Run Locally

Use Python 3.11 when running outside Docker.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `POLYGON_API_KEY` | Yes | none | Polygon.io API key used for WebSocket auth. |
| `TRADE_MODE` | No | `simulation` | `simulation` or `live`. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. |
| `DEFAULT_UNITS` | No | `1000` | Units sent to the broker per entry order. |
| `MAX_OPEN_TRADES` | No | `3` | Maximum number of simultaneous open trades. |
| `OANDA_API_KEY` | Live only | none | OANDA v20 API token. |
| `OANDA_ACCOUNT_ID` | Live only | none | OANDA account ID. |
| `OANDA_ENVIRONMENT` | Live only | `practice` | `practice` or `live`. |

## Data Flow

For every accepted Polygon tick:

1. `StateManager.update()` stores the tick and recomputes indicators.
2. `ConsoleDisplay.tick_update()` prints a throttled tick line.
3. `decide_trade_action(symbol, tick, state)` evaluates the black-box strategy.
4. `ExecutionEngine.handle_signal()` ignores `HOLD` or routes `BUY`, `SELL`, and `CLOSE`.
5. The active broker returns an `OrderResult`.
6. Successful trades update open-trade state, print a banner, write CSV, and log to file.

## Strategy Contract

The strategy lives in `src/strategy/decide.py` and must expose this exact function:

```python
def decide_trade_action(symbol: str, tick: dict, state: dict) -> TradeSignal:
    ...
```

Input shape:

```python
tick = {
    "bid": float,
    "ask": float,
    "mid": float,
    "timestamp": float,
}

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

Output shape:

```python
TradeSignal(
    action="BUY" | "SELL" | "CLOSE" | "HOLD",
    symbol="C:EURUSD",
    price=1.08415,
    reason="EMA cross UP | RSI=58.3",
    confidence=0.72,
)
```

The execution engine only consumes the returned `TradeSignal`; it does not inspect strategy internals.

## Broker Layer

`BaseBroker` defines the broker contract:

```python
async def place_order(symbol: str, action: str, units: int, price: float) -> OrderResult
async def close_position(symbol: str, price: float) -> OrderResult
```

Implementations:

- `SimulationBroker`: local paper execution with deterministic `SIM-*` order IDs.
- `OANDABroker`: OANDA v20 market orders and position close requests.

Internal symbols are mapped to OANDA instruments in `src/config.py`:

| Internal Symbol | OANDA Instrument |
| --- | --- |
| `C:USDJPY` | `USD_JPY` |
| `C:EURUSD` | `EUR_USD` |
| `C:GBPUSD` | `GBP_USD` |
| `C:XAUUSD` | `XAU_USD` |
| `X:BTCUSD` | `BTC_USD` |

Instrument availability can vary by OANDA account region and account type.

## Logs and Trade Journal

Application logs:

```text
logs/engine.log
```

CSV trade journal:

```text
trades/trades.csv
```

CSV columns:

```csv
timestamp_utc,symbol,action,price,units,order_id,reason,confidence,mode
```

Example row:

```csv
2026-05-30 14:22:01,C:EURUSD,BUY,1.08415,1000,SIM-00001,EMA cross UP | RSI=58.3,0.72,simulation
```

## Docker Notes

The compose service:

- builds from `python:3.11-slim`
- installs `requirements.txt`
- loads `.env` with `env_file`
- mounts `./logs` to `/app/logs`
- mounts `./trades` to `/app/trades`

## Operational Checklist

Before running against OANDA:

1. Run in `simulation` mode and confirm Polygon authentication succeeds.
2. Confirm all expected symbols receive ticks.
3. Review `trades/trades.csv` and `logs/engine.log`.
4. Test with `OANDA_ENVIRONMENT=practice`.
5. Confirm OANDA supports every configured instrument for your account.
6. Set conservative `DEFAULT_UNITS` and `MAX_OPEN_TRADES`.

## License

MIT
