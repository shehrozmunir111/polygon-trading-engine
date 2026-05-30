#!/usr/bin/env bash
# Run inside Google Cloud Shell (https://shell.cloud.google.com/) — free, no PC VPN.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Polygon Trading Engine — Cloud Shell setup ==="

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — run: nano .env  (add POLYGON_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)"
  exit 0
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Testing Telegram API..."
python scripts/test_telegram_proxy.py && echo "=== Run engine: python main.py ==="
