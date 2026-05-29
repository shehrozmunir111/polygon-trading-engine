"""
config.py — Central config loader.
All settings come from environment variables (.env file).
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Polygon
    POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")

    # OANDA
    OANDA_API_KEY: str = os.getenv("OANDA_API_KEY", "")
    OANDA_ACCOUNT_ID: str = os.getenv("OANDA_ACCOUNT_ID", "")
    OANDA_ENVIRONMENT: str = os.getenv("OANDA_ENVIRONMENT", "practice")

    # Engine
    TRADE_MODE: str = os.getenv("TRADE_MODE", "simulation")   # simulation | live
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Risk
    DEFAULT_UNITS: int = int(os.getenv("DEFAULT_UNITS", "1000"))
    MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "3"))

    # Symbols — Polygon currency pair format
    SYMBOLS: list[str] = [
        "C:USDJPY",
        "C:EURUSD",
        "C:GBPUSD",
        "C:XAUUSD",
        "X:BTCUSD",
    ]

    # OANDA instrument names (same order as SYMBOLS)
    OANDA_INSTRUMENTS: dict[str, str] = {
        "C:USDJPY": "USD_JPY",
        "C:EURUSD": "EUR_USD",
        "C:GBPUSD": "GBP_USD",
        "C:XAUUSD": "XAU_USD",
        "X:BTCUSD": "BTC_USD",
    }

    @classmethod
    def validate(cls):
        if not cls.POLYGON_API_KEY:
            raise ValueError("POLYGON_API_KEY is not set in .env")
        if cls.TRADE_MODE == "live" and not cls.OANDA_API_KEY:
            raise ValueError("OANDA_API_KEY is required for live mode")
        if cls.TRADE_MODE == "live" and not cls.OANDA_ACCOUNT_ID:
            raise ValueError("OANDA_ACCOUNT_ID is required for live mode")
        if cls.TRADE_MODE not in ("simulation", "live"):
            raise ValueError("TRADE_MODE must be 'simulation' or 'live'")


config = Config()
