"""
ledger/receipt.py — Tamper-proof signed JSON receipt for every executed trade.

Each receipt is signed with HMAC-SHA256 and saved as an individual JSON file
under trades/receipts/{receipt_id}.json.  If the file write fails the receipt
dict is still returned and a warning is logged — trading is never interrupted.
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.broker.base import OrderResult
from src.config import config
from src.strategy.decide import TradeSignal

logger = logging.getLogger(__name__)

RECEIPTS_DIR = Path("trades") / "receipts"


class ReceiptLedger:
    """
    Generates and persists a signed JSON receipt for every executed trade.

    Receipt fields
    --------------
    receipt_id      UUID4 string
    timestamp_utc   ISO 8601 string (UTC)
    symbol          e.g. "C:EURUSD"
    action          BUY | SELL | CLOSE
    price           float
    units           int
    order_id        str
    reason          strategy signal reason
    confidence      float 0.0–1.0
    mode            simulation | live
    signature       HMAC-SHA256 hex digest of all other fields

    The signature is computed over a deterministic JSON serialisation
    (keys sorted, separators compact) of all fields except ``signature``
    itself, keyed with ``RECEIPT_SECRET_KEY``.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        mode: str | None = None,
        receipts_dir: Path | str | None = None,
    ) -> None:
        """
        Args:
            secret_key:   HMAC secret. Defaults to ``config.RECEIPT_SECRET_KEY``.
            mode:         Trade mode label. Defaults to ``config.TRADE_MODE``.
            receipts_dir: Directory for receipt files. Defaults to ``RECEIPTS_DIR``
                          (``trades/receipts/``). Override in tests for isolation.
        """
        self._secret: bytes = (
            secret_key if secret_key is not None else config.RECEIPT_SECRET_KEY
        ).encode()
        self._mode: str = mode if mode is not None else config.TRADE_MODE
        self._receipts_dir: Path = Path(receipts_dir) if receipts_dir is not None else RECEIPTS_DIR
        self._receipts_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, result: OrderResult, signal: TradeSignal) -> dict:
        """
        Build, sign, persist, and return a receipt dict for an executed trade.

        The receipt is written to ``trades/receipts/{receipt_id}.json``.
        A failed write logs a warning but does not raise.

        Returns:
            The complete receipt dict including the ``signature`` field.
        """
        receipt: dict = {
            "receipt_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "action": result.action,
            "price": result.price,
            "units": result.units,
            "order_id": result.order_id,
            "reason": signal.reason,
            "confidence": signal.confidence,
            "mode": self._mode,
        }
        receipt["signature"] = self._sign(receipt)
        self._save(receipt)
        return receipt

    def verify(self, receipt: dict) -> bool:
        """
        Verify the HMAC-SHA256 signature of a receipt.

        Uses ``hmac.compare_digest`` to prevent timing attacks.

        Returns:
            True if the signature is valid, False otherwise.
        """
        payload = {k: v for k, v in receipt.items() if k != "signature"}
        expected = self._sign(payload)
        return hmac.compare_digest(receipt.get("signature", ""), expected)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _sign(self, data: dict) -> str:
        """Return an HMAC-SHA256 hex digest of the deterministically serialised data."""
        message = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _save(self, receipt: dict) -> None:
        """Write the receipt JSON to disk; log a warning on any I/O failure."""
        path = self._receipts_dir / f"{receipt['receipt_id']}.json"
        try:
            path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            logger.debug(f"[LEDGER] Receipt saved: {path.name}")
        except OSError as e:
            logger.warning(f"[LEDGER] Failed to save receipt {receipt['receipt_id']}: {e}")
