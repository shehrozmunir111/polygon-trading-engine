"""
Test whether Python can reach Telegram API using .env proxy settings.

Usage (from project root, venv activated):
    python scripts/test_telegram_proxy.py
"""
import asyncio
import sys
from pathlib import Path

# Allow `from src...` when this file is run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import config
from src.notifications.telegram_bot import TelegramNotifier, _proxy_endpoint_label


async def main() -> int:
    if not config.TELEGRAM_BOT_TOKEN:
        print("FAIL: TELEGRAM_BOT_TOKEN is not set in .env")
        return 1

    if config.TELEGRAM_PROXY:
        print(f"Proxy: {_proxy_endpoint_label(config.TELEGRAM_PROXY)}")
    else:
        print("Proxy: (none) — add TELEGRAM_PROXY=socks5://127.0.0.1:PORT to .env")

    notifier = TelegramNotifier()
    ok = await notifier._prepare_bot_session()
    if notifier._bot:
        await notifier._bot.session.close()

    if ok:
        print("OK: Python reached Telegram API. Run: python main.py")
        return 0

    print("FAIL: Could not connect. Check proxy host/port and that the VPN app is running.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
