"""
broker/oanda.py — OANDA REST API broker implementation (v20).

Uses oandapyV20 SDK for order placement and position management.
Targets OANDA practice (demo) or live environment based on config.
"""
import logging
import time

import oandapyV20
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
from oandapyV20.exceptions import V20Error

from src.config import config
from src.broker.base import BaseBroker, OrderResult

logger = logging.getLogger(__name__)


class OANDABroker(BaseBroker):
    """
    Live/Practice broker via OANDA v20 REST API.
    Supports: market orders, position close.
    """

    def __init__(self):
        environment = "practice" if config.OANDA_ENVIRONMENT == "practice" else "live"
        self._client = oandapyV20.API(
            access_token=config.OANDA_API_KEY,
            environment=environment,
        )
        self._account_id = config.OANDA_ACCOUNT_ID
        logger.info(f"[OANDA] Initialized ({environment}) account={self._account_id}")

    def _instrument(self, symbol: str) -> str:
        """Map internal symbol to OANDA instrument name."""
        return config.OANDA_INSTRUMENTS.get(symbol, symbol)

    async def place_order(self, symbol: str, action: str, units: int, price: float) -> OrderResult:
        instrument = self._instrument(symbol)
        signed_units = units if action == "BUY" else -units

        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(signed_units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }

        try:
            req = orders.OrderCreate(self._account_id, data=body)
            resp = self._client.request(req)
            fill = resp.get("orderFillTransaction", {})
            order_id = fill.get("id", "unknown")
            fill_price = float(fill.get("price", price))

            logger.info(f"[OANDA] Order placed: {action} {units} {instrument} @ {fill_price}")
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                action=action,
                units=units,
                price=fill_price,
                timestamp=time.time(),
            )

        except V20Error as e:
            logger.error(f"[OANDA] Order failed for {symbol}: {e}")
            return OrderResult(
                success=False,
                order_id="",
                symbol=symbol,
                action=action,
                units=units,
                price=price,
                timestamp=time.time(),
                error=str(e),
            )

    async def close_position(self, symbol: str, price: float) -> OrderResult:
        instrument = self._instrument(symbol)
        body = {"longUnits": "ALL", "shortUnits": "ALL"}

        try:
            req = positions.PositionClose(self._account_id, instrument=instrument, data=body)
            resp = self._client.request(req)

            long_fill = resp.get("longOrderFillTransaction", {})
            short_fill = resp.get("shortOrderFillTransaction", {})
            fill = long_fill or short_fill
            order_id = fill.get("id", "unknown")
            fill_price = float(fill.get("price", price))

            logger.info(f"[OANDA] Position closed: {instrument} @ {fill_price}")
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                action="CLOSE",
                units=0,
                price=fill_price,
                timestamp=time.time(),
            )

        except V20Error as e:
            logger.error(f"[OANDA] Close failed for {symbol}: {e}")
            return OrderResult(
                success=False,
                order_id="",
                symbol=symbol,
                action="CLOSE",
                units=0,
                price=price,
                timestamp=time.time(),
                error=str(e),
            )
